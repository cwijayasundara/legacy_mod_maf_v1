from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache
from dataclasses import dataclass
from typing import Any

import azure.functions as func
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.servicebus.exceptions import ServiceBusError

from .services.constants import DDBStatus
from .services.transformer import TransformerFactory

app = func.FunctionApp()
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


@dataclass(frozen=True)
class DataGeneratorConfig:
    cosmos_endpoint: str
    cosmos_database: str
    cosmos_container: str
    service_bus_connection: str
    service_bus_topic: str


@lru_cache(maxsize=1)
def _config() -> DataGeneratorConfig:
    return DataGeneratorConfig(
        cosmos_endpoint=os.environ["COSMOS_ENDPOINT"],
        cosmos_database=os.environ["COSMOS_DATABASE"],
        cosmos_container=os.environ["COSMOS_CONTAINER"],
        service_bus_connection=os.environ["SERVICE_BUS_CONNECTION"],
        service_bus_topic=os.environ["VALIDATOR_TOPIC_NAME"],
    )


@lru_cache(maxsize=1)
def _cosmos_client() -> CosmosClient:
    return CosmosClient(_config().cosmos_endpoint, DefaultAzureCredential())


@lru_cache(maxsize=1)
def _service_bus_client() -> ServiceBusClient:
    return ServiceBusClient.from_connection_string(_config().service_bus_connection)


def _request_detail(event: dict[str, Any]) -> dict[str, Any]:
    detail = event.get("detail")
    return detail if isinstance(detail, dict) else {}


def _ddb_id_from_event(event: dict[str, Any]) -> str | None:
    detail = _request_detail(event)
    raw_ddb_id = detail.get("ddbId")
    if raw_ddb_id is None:
        return None
    ddb_id = str(raw_ddb_id).strip()
    return ddb_id or None


def _load_request_record(ddb_id: str) -> dict[str, Any]:
    container = _cosmos_client().get_database_client(_config().cosmos_database).get_container_client(
        _config().cosmos_container
    )
    item = container.read_item(item=ddb_id, partition_key=ddb_id)
    if not item:
        raise RuntimeError(f"record {ddb_id} not found")
    return item


def _write_success_state(ddb_id: str, merged: dict[str, Any]) -> None:
    container = _cosmos_client().get_database_client(_config().cosmos_database).get_container_client(
        _config().cosmos_container
    )
    container.upsert_item(
        {
            "id": ddb_id,
            "ID": ddb_id,
            "mergedJSON": merged,
            "transformedJSON": merged,
            "status": {"transformed": int(time.time())},
            "finalStatus": DDBStatus.TRANSFORMED.value,
        }
    )


async def _send_validator_event(ddb_id: str) -> None:
    message = ServiceBusMessage(json.dumps({"ddbId": ddb_id, "source": "dataGenerator", "destination": "validator"}))
    try:
        with _service_bus_client() as client:
            sender = client.get_topic_sender(topic_name=_config().service_bus_topic)
            with sender:
                sender.send_messages(message)
    except ServiceBusError as exc:
        log.exception("dataGenerator failed to publish validator event for %s", ddb_id)
        raise RuntimeError(str(exc)) from exc


def _handle_failure(ddb_id: str | None, error: str) -> None:
    if not ddb_id:
        return
    try:
        container = _cosmos_client().get_database_client(_config().cosmos_database).get_container_client(
            _config().cosmos_container
        )
        container.upsert_item(
            {
                "id": ddb_id,
                "ID": ddb_id,
                "finalStatus": DDBStatus.EXCEPTION.value,
                "errorDetails": error,
                "updatedAt": int(time.time()),
            }
        )
    except CosmosResourceNotFoundError:
        log.warning("dataGenerator could not mark %s as EXCEPTION because the record was missing", ddb_id)


@app.function_name(name="data_generator")
@app.service_bus_topic_trigger(arg_name="msg", topic_name="data-generator", subscription_name="data-generator", connection="SERVICE_BUS_CONNECTION")
def data_generator_trigger(msg: func.ServiceBusMessage) -> dict[str, Any]:
    payload = json.loads(msg.get_body().decode("utf-8"))
    return handler(payload, None)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    ddb_id = _ddb_id_from_event(event)
    if not ddb_id:
        log.error("dataGenerator: missing ddbId in detail %s", _request_detail(event))
        return {"ok": False, "reason": "missing ddbId"}

    try:
        record = _load_request_record(ddb_id)
        merged = TransformerFactory.transform_to_filer_json(
            raw_payload=record.get("reqInputJSON", {}),
            service_type=record["serviceType"],
            jurisdiction=record.get("jurisdiction", ""),
            source_system=record.get("sourceSystem", "UPSTREAM"),
        )
        _write_success_state(ddb_id, merged)
        import asyncio

        asyncio.run(_send_validator_event(ddb_id))
        return {"ok": True, "ddbId": ddb_id}
    except (CosmosResourceNotFoundError, RuntimeError, KeyError, ValueError, json.JSONDecodeError, ServiceBusError) as exc:
        log.exception("dataGenerator failed for %s", ddb_id)
        _handle_failure(ddb_id, str(exc))
        return {"ok": False, "ddbId": ddb_id, "error": str(exc)}
