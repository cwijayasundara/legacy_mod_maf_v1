from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import azure.functions as func
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusMessage, ServiceBusClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


@dataclass(frozen=True)
class ValidationConfig:
    cosmos_endpoint: str
    cosmos_database: str
    cosmos_container: str
    service_bus_namespace: str
    service_bus_queue_name: str


@dataclass(frozen=True)
class ValidationResult:
    success: bool
    errors: list[str]


@dataclass
class ValidationService:
    container: Any
    sender: Any

    def load_record(self, ddb_id: str) -> dict[str, Any]:
        return self.container.read_item(item=ddb_id, partition_key=ddb_id)

    def save_validation_failure(self, ddb_id: str, errors: list[str]) -> None:
        self.container.upsert_item(
            {
                "ID": ddb_id,
                "mergedJSONValidationErrors": errors,
                "finalStatus": "EXCEPTION",
                "status": {"validated": int(time.time())},
            }
        )

    def save_validation_success(self, ddb_id: str) -> None:
        self.container.upsert_item(
            {"ID": ddb_id, "finalStatus": "VALIDATED", "status": {"validated": int(time.time())}}
        )

    def publish(self, service_type: str, jurisdiction: str, payload: dict[str, Any], *, group_id: str | None = None, deduplication_id: str | None = None) -> None:
        message = {
            "serviceType": service_type,
            "jurisdiction": jurisdiction,
            "payload": payload,
            "groupId": group_id,
            "deduplicationId": deduplication_id,
            "enqueuedAt": int(time.time()),
        }
        self.sender.send_messages(ServiceBusMessage(json.dumps(message), session_id=group_id))


def _parse_body(req: func.HttpRequest) -> dict[str, Any]:
    try:
        return req.get_json()
    except ValueError:
        return {}


@lru_cache(maxsize=1)
def _config() -> ValidationConfig:
    return ValidationConfig(
        cosmos_endpoint=os.environ["COSMOS_ENDPOINT"],
        cosmos_database=os.environ["COSMOS_DATABASE"],
        cosmos_container=os.environ["COSMOS_CONTAINER"],
        service_bus_namespace=os.environ["SERVICE_BUS_NAMESPACE"],
        service_bus_queue_name=os.environ["SERVICE_BUS_QUEUE_NAME"],
    )


@lru_cache(maxsize=1)
def _cosmos_client() -> CosmosClient:
    return CosmosClient(_config().cosmos_endpoint, credential=DefaultAzureCredential())


@lru_cache(maxsize=1)
def _service_bus_client() -> ServiceBusClient:
    return ServiceBusClient(_config().service_bus_namespace, credential=DefaultAzureCredential())


@lru_cache(maxsize=1)
def _service() -> ValidationService:
    container = _cosmos_client().get_database_client(_config().cosmos_database).get_container_client(_config().cosmos_container)
    sender = _service_bus_client().get_queue_sender(queue_name=_config().service_bus_queue_name)
    return ValidationService(container=container, sender=sender)


def validate(merged_json: dict[str, Any]) -> ValidationResult:
    errors: list[str] = []
    entity = merged_json.get("entity") or {}
    meta = merged_json.get("_meta") or {}
    if not entity.get("name"):
        errors.append("entity.name is required")
    if not meta.get("jurisdiction"):
        errors.append("jurisdiction is required")
    return ValidationResult(success=not errors, errors=errors)


def handle_error(ddb_id: str, error: Exception) -> None:
    try:
        _service().save_validation_failure(ddb_id, [str(error)])
    except CosmosResourceNotFoundError:
        log.warning("validation error update skipped because record %s was not found", ddb_id)
    log.exception("validation failed for %s", ddb_id)


def push_item_to_common_queue(*, service_type: str, jurisdiction: str, payload: dict[str, Any], group_id: str | None = None, deduplication_id: str | None = None) -> None:
    resolved_group_id = group_id or f"{jurisdiction}#{service_type}"
    resolved_dedup_id = deduplication_id or str(uuid.uuid4())
    _service().publish(service_type, jurisdiction, payload, group_id=resolved_group_id, deduplication_id=resolved_dedup_id)


@app.function_name(name="validation")
@app.route(route="validation", methods=[func.HttpMethod.POST])
def handler(req: func.HttpRequest) -> func.HttpResponse:
    body = _parse_body(req)
    detail = body.get("detail") or {}
    ddb_id = detail.get("ddbId")
    if not ddb_id:
        return func.HttpResponse(json.dumps({"ok": False, "reason": "missing ddbId"}), status_code=200, mimetype="application/json")

    try:
        service = _service()
        record = service.load_record(ddb_id)
        if not record:
            raise RuntimeError(f"record {ddb_id} not found")
        merged = record.get("mergedJSON") or {}
        result = validate(merged)
        if not result.success:
            service.save_validation_failure(ddb_id, result.errors)
            return func.HttpResponse(json.dumps({"ok": False, "ddbId": ddb_id, "errors": result.errors}), status_code=200, mimetype="application/json")
        service.save_validation_success(ddb_id)
        service.publish(record["serviceType"], record.get("jurisdiction", ""), {"ddbId": ddb_id, **merged})
        return func.HttpResponse(json.dumps({"ok": True, "ddbId": ddb_id}), status_code=200, mimetype="application/json")
    except RuntimeError:
        raise
    except Exception as exc:
        handle_error(ddb_id, exc)
        return func.HttpResponse(json.dumps({"ok": False, "ddbId": ddb_id, "error": str(exc)}), status_code=500, mimetype="application/json")
