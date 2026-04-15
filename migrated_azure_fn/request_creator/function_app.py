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
from azure.eventgrid import EventGridPublisherClient, EventGridEvent
from azure.core.credentials import AzureKeyCredential

from .services.constants import DDBStatus, EventType

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


@dataclass(frozen=True)
class RequestCreatorConfig:
    cosmos_endpoint: str
    cosmos_database: str
    request_container: str
    settings_container: str
    event_grid_endpoint: str
    event_grid_key: str
    event_grid_topic: str


@lru_cache(maxsize=1)
def _config() -> RequestCreatorConfig:
    return RequestCreatorConfig(
        cosmos_endpoint=os.environ["COSMOS_ENDPOINT"],
        cosmos_database=os.environ["COSMOS_DATABASE"],
        request_container=os.environ["REQUEST_CONTAINER_NAME"],
        settings_container=os.environ["SETTINGS_CONTAINER_NAME"],
        event_grid_endpoint=os.environ["EVENT_GRID_ENDPOINT"],
        event_grid_key=os.environ.get("EVENT_GRID_KEY", ""),
        event_grid_topic=os.environ["EVENT_GRID_TOPIC"],
    )


@lru_cache(maxsize=1)
def _cosmos_client() -> CosmosClient:
    return CosmosClient(_config().cosmos_endpoint, credential=DefaultAzureCredential())


@lru_cache(maxsize=1)
def _event_grid_client() -> EventGridPublisherClient:
    credential = AzureKeyCredential(_config().event_grid_key)
    return EventGridPublisherClient(_config().event_grid_endpoint, credential)


def _settings_container() -> Any:
    return _cosmos_client().get_database_client(_config().cosmos_database).get_container_client(_config().settings_container)


def _request_container() -> Any:
    return _cosmos_client().get_database_client(_config().cosmos_database).get_container_client(_config().request_container)


def _parse_body(req: func.HttpRequest) -> dict[str, Any]:
    try:
        body = req.get_json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _error_response(status_code: int, code: str, message: str) -> func.HttpResponse:
    payload = {"error": {"code": code, "message": message, "details": []}}
    return func.HttpResponse(json.dumps(payload), status_code=status_code, mimetype="application/json")


def _lookup_jurisdiction_settings(jurisdiction: str | None, service_type: str) -> dict[str, Any]:
    if not jurisdiction:
        return {}
    container = _settings_container()
    item = container.read_item(item=f"{jurisdiction}#{service_type}", partition_key=f"{jurisdiction}#{service_type}")
    return item or {}


def _upsert_request_record(*, ddb_id: str, request_body: dict[str, Any], source_system: str, event_type: str | None) -> None:
    container = _request_container()
    container.upsert_item(
        {
            "id": ddb_id,
            "ID": ddb_id,
            "reqInputJSON": request_body,
            "serviceType": request_body.get("serviceType"),
            "jurisdiction": request_body.get("jurisdiction"),
            "sourceSystem": source_system,
            "eventType": event_type,
            "status": {"created": int(time.time())},
            "finalStatus": DDBStatus.CREATED.value,
            "createdAt": int(time.time()),
        }
    )


def _publish_downstream_event(*, ddb_id: str, event_type: str | None) -> None:
    detail: dict[str, Any] = {"ddbId": ddb_id}
    if event_type in {EventType.MERGE_EVIDENCE.value, EventType.ORDER_RESUBMIT.value}:
        detail["branch"] = event_type
    event = EventGridEvent(
        subject="requestCreator",
        data=detail,
        event_type="requestPipeline",
        data_version="1.0",
    )
    _event_grid_client().send([event])


@app.function_name(name="request_creator")
@app.route(route="filing/request", methods=[func.HttpMethod.POST])
def handler(req: func.HttpRequest) -> func.HttpResponse:
    body = _parse_body(req)
    event_type = body.get("eventType")
    source_system = body.get("source", "UPSTREAM")
    service_type = body.get("serviceType")
    jurisdiction = body.get("jurisdiction")

    if not service_type:
        return _error_response(400, "BAD_REQUEST", "serviceType required")

    ddb_id = str(uuid.uuid4())

    try:
        if source_system == "UPSTREAM" and event_type == EventType.UPSTREAM.value:
            settings = _lookup_jurisdiction_settings(jurisdiction, service_type)
            if not settings.get("enabled", True):
                return _error_response(409, "CONFLICT", f"{jurisdiction}/{service_type} not enabled")
            if settings.get("cidPinRequired") and not body.get("cidPin"):
                return _error_response(400, "BAD_REQUEST", "CID/PIN required")

        _upsert_request_record(ddb_id=ddb_id, request_body={**body, "source": source_system}, source_system=source_system, event_type=event_type)
        _publish_downstream_event(ddb_id=ddb_id, event_type=event_type)
        return func.HttpResponse(json.dumps({"ddbId": ddb_id, "status": "CREATED"}), status_code=200, mimetype="application/json")
    except CosmosResourceNotFoundError as exc:
        log.exception("request_creator settings or request record missing for %s", ddb_id)
        return func.HttpResponse(json.dumps({"error": str(exc), "ddbId": ddb_id}), status_code=500, mimetype="application/json")
    except ValueError as exc:
        log.exception("request_creator validation failed for %s", ddb_id)
        return func.HttpResponse(json.dumps({"error": str(exc), "ddbId": ddb_id}), status_code=500, mimetype="application/json")
    except json.JSONDecodeError as exc:
        log.exception("request_creator body decode failed for %s", ddb_id)
        return func.HttpResponse(json.dumps({"error": str(exc), "ddbId": ddb_id}), status_code=500, mimetype="application/json")
    except Exception as exc:
        log.exception("request_creator failed for %s", ddb_id)
        return func.HttpResponse(json.dumps({"error": str(exc), "ddbId": ddb_id}), status_code=500, mimetype="application/json")
