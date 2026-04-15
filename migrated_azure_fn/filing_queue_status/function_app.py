from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import azure.functions as func
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusMessage
from azure.servicebus.aio import ServiceBusClient

app = func.FunctionApp()
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


@dataclass(frozen=True)
class FilingMessage:
    service_type: str
    jurisdiction: str
    ddb_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ProcessingResult:
    ok: bool
    data: dict[str, Any]
    retryable: bool = False


def _error_payload(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": []}}


def _parse_record(record: dict[str, Any]) -> FilingMessage | ProcessingResult:
    body = record.get("body", "{}")
    try:
        msg = json.loads(body)
    except json.JSONDecodeError:
        log.error("module=filing_queue_status operation=parse_body status=bad_json body=%r", body)
        return ProcessingResult(ok=False, data={"ok": False, "reason": "bad_body"}, retryable=False)

    service_type = msg.get("serviceType")
    jurisdiction = msg.get("jurisdiction")
    payload = msg.get("payload") or {}
    ddb_id = payload.get("ddbId", "")
    if not service_type or not jurisdiction or not isinstance(payload, dict) or "ddbId" not in payload:
        return ProcessingResult(ok=False, data={"ok": False, "reason": "bad_body"}, retryable=False)
    return FilingMessage(service_type=service_type, jurisdiction=jurisdiction, ddb_id=str(ddb_id), payload=payload)


@lru_cache(maxsize=1)
def _cosmos_client() -> CosmosClient:
    endpoint = os.environ["COSMOS_ENDPOINT"]
    return CosmosClient(endpoint, credential=DefaultAzureCredential())


@lru_cache(maxsize=1)
def _service_bus_client() -> ServiceBusClient:
    namespace = os.environ["SERVICEBUS_FQDN"]
    return ServiceBusClient(namespace, credential=DefaultAzureCredential())


@lru_cache(maxsize=1)
def _status_container():
    database_name = os.environ["COSMOS_DATABASE_NAME"]
    container_name = os.environ["BOT_STATUS_CONTAINER_NAME"]
    return _cosmos_client().get_database_client(database_name).get_container_client(container_name)


@lru_cache(maxsize=1)
def _counter_container():
    database_name = os.environ["COSMOS_DATABASE_NAME"]
    container_name = os.environ["FILING_COUNTER_CONTAINER_NAME"]
    return _cosmos_client().get_database_client(database_name).get_container_client(container_name)


@lru_cache(maxsize=1)
def _filer_topic_name() -> str:
    return os.environ["FILER_TOPIC_NAME"]


async def _publish_event(message: FilingMessage, *, bypass: bool) -> None:
    sender = _service_bus_client().get_topic_sender(topic_name=_filer_topic_name())
    detail = {"ddbId": message.ddb_id, "payload": message.payload}
    if not bypass:
        detail["serviceType"] = message.service_type
        detail["jurisdiction"] = message.jurisdiction
    payload = json.dumps({"source": "filingQueueStatusHandler", "destination": "filer", **detail})
    async with sender:
        await sender.send_messages(ServiceBusMessage(payload))


def _load_status(jurisdiction: str, service_type: str) -> dict[str, Any]:
    item_id = f"BOT_STATUS#{jurisdiction}#{service_type}"
    try:
        return _status_container().read_item(item=item_id, partition_key=item_id)
    except CosmosResourceNotFoundError:
        return {"status": "IDLE"}


def _mark_in_progress(message: FilingMessage) -> None:
    item_id = f"BOT_STATUS#{message.jurisdiction}#{message.service_type}"
    _status_container().upsert_item(
        {"id": item_id, "status": "IN_PROGRESS", "data": {"ddbId": message.ddb_id}}
    )


def _decrement_counter(message: FilingMessage) -> None:
    item_id = f"FILING_COUNT#{message.jurisdiction}#{message.service_type}"
    container = _counter_container()
    try:
        current = container.read_item(item=item_id, partition_key=item_id)
        count = int(current.get("count", 0)) - 1
    except CosmosResourceNotFoundError:
        count = -1
    container.upsert_item({"id": item_id, "count": count})


def _process(record: dict[str, Any]) -> dict[str, Any]:
    parsed = _parse_record(record)
    if isinstance(parsed, ProcessingResult):
        return parsed.data

    message = parsed
    if message.jurisdiction == "DELAWARE" and message.service_type == "COGS":
        _publish_event_sync(message, bypass=True)
        return {"ok": True, "bypass": "DELAWARE_COGS"}

    status = _load_status(message.jurisdiction, message.service_type)
    if status.get("status") != "IDLE":
        log.info("module=filing_queue_status operation=concurrency_gate status=busy ddbId=%s", message.ddb_id)
        raise RuntimeError("bot_busy")

    try:
        _mark_in_progress(message)
        _decrement_counter(message)
        _publish_event_sync(message, bypass=False)
        return {"ok": True, "ddbId": message.ddb_id}
    except CosmosResourceExistsError as exc:
        log.exception("module=filing_queue_status operation=cosmos_write status=error ddbId=%s", message.ddb_id)
        raise RuntimeError(str(exc)) from exc


def _publish_event_sync(message: FilingMessage, *, bypass: bool) -> None:
    import asyncio

    asyncio.run(_publish_event(message, bypass=bypass))


@app.service_bus_queue_trigger(arg_name="msg", queue_name="filing-queue-status", connection="SERVICEBUS_CONNECTION")
def filing_queue_status(msg: func.ServiceBusMessage) -> dict[str, Any]:
    return _process({"body": msg.get_body().decode("utf-8"), "messageId": msg.message_id})


@app.function_name(name="filing_queue_status")
@app.service_bus_queue_trigger(arg_name="msg", queue_name="filing-queue-status", connection="SERVICEBUS_CONNECTION")
def handler(msg: func.ServiceBusMessage) -> dict[str, Any]:
    result = _process({"body": msg.get_body().decode("utf-8"), "messageId": msg.message_id})
    return {"batchItemFailures": [] if result.get("ok") else [{"itemIdentifier": msg.message_id or ""}], "results": [result]}
