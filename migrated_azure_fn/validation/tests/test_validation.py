from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import azure.functions as func
import pytest

from validation.function_app import ValidationService, handle_error, handler, push_item_to_common_queue


class DummyEvent:
    def __init__(self, body: dict[str, object]) -> None:
        self.body = json.dumps(body).encode("utf-8")
        self.method = "POST"
        self.url = "http://localhost/api/validation"
        self.headers = {}


def _mock_container(record: dict[str, object] | None) -> MagicMock:
    container = MagicMock()
    container.read_item = MagicMock(return_value=record)
    container.upsert_item = MagicMock()
    return container


@patch("validation.function_app.ServiceBusClient")
@patch("validation.function_app.CosmosClient")
@patch("validation.function_app.DefaultAzureCredential")
def test_handler_returns_soft_failure_when_ddb_id_missing(cred: MagicMock, cosmos: MagicMock, sbus: MagicMock) -> None:
    # Arrange
    req = DummyEvent({"detail": {}})

    # Act
    resp = handler(req)

    # Assert
    assert isinstance(resp, func.HttpResponse)
    assert resp.status_code == 200
    assert json.loads(resp.get_body()) == {"ok": False, "reason": "missing ddbId"}
    cosmos.assert_not_called()
    sbus.assert_not_called()
    cred.assert_not_called()


@patch("validation.function_app.ServiceBusClient")
@patch("validation.function_app.CosmosClient")
@patch("validation.function_app.DefaultAzureCredential")
def test_handler_validates_and_enqueues_successfully(cred: MagicMock, cosmos: MagicMock, sbus: MagicMock) -> None:
    # Arrange
    record = {
        "ID": "ddb-1",
        "mergedJSON": {"entity": {"name": "Acme"}, "_meta": {"jurisdiction": "FLORIDA", "serviceType": "EIN"}},
        "serviceType": "EIN",
        "jurisdiction": "FLORIDA",
    }
    container = _mock_container(record)
    cosmos.return_value.get_database_client.return_value.get_container_client.return_value = container
    sender = MagicMock()
    sbus.return_value.get_queue_sender.return_value = sender
    req = DummyEvent({"detail": {"ddbId": "ddb-1"}})

    # Act
    resp = handler(req)

    # Assert
    assert resp.status_code == 200
    assert json.loads(resp.get_body()) == {"ok": True, "ddbId": "ddb-1"}
    container.read_item.assert_called_once_with(item="ddb-1", partition_key="ddb-1")
    container.upsert_item.assert_called()
    sender.send_messages.assert_called_once()


@patch("validation.function_app.ServiceBusClient")
@patch("validation.function_app.CosmosClient")
@patch("validation.function_app.DefaultAzureCredential")
def test_handler_returns_validation_errors_when_validator_fails(cred: MagicMock, cosmos: MagicMock, sbus: MagicMock) -> None:
    # Arrange
    record = {
        "ID": "ddb-2",
        "mergedJSON": {"entity": {}, "_meta": {"jurisdiction": "FLORIDA", "serviceType": "EIN"}},
        "serviceType": "EIN",
        "jurisdiction": "FLORIDA",
    }
    container = _mock_container(record)
    cosmos.return_value.get_database_client.return_value.get_container_client.return_value = container
    req = DummyEvent({"detail": {"ddbId": "ddb-2"}})

    # Act
    resp = handler(req)

    # Assert
    assert resp.status_code == 200
    payload = json.loads(resp.get_body())
    assert payload["ok"] is False
    assert payload["ddbId"] == "ddb-2"
    assert payload["errors"]
    assert sbus.return_value.get_queue_sender.return_value.send_messages.call_count == 0


@patch("validation.function_app.ServiceBusClient")
@patch("validation.function_app.CosmosClient")
@patch("validation.function_app.DefaultAzureCredential")
def test_handler_raises_runtime_error_when_record_missing(cred: MagicMock, cosmos: MagicMock, sbus: MagicMock) -> None:
    # Arrange
    container = _mock_container(None)
    cosmos.return_value.get_database_client.return_value.get_container_client.return_value = container
    req = DummyEvent({"detail": {"ddbId": "ddb-3"}})

    # Act / Assert
    with pytest.raises(RuntimeError, match="record"):
        handler(req)


@patch("validation.function_app.ServiceBusClient")
@patch("validation.function_app.CosmosClient")
@patch("validation.function_app.DefaultAzureCredential")
def test_handler_converts_unexpected_exceptions_into_failure_response(cred: MagicMock, cosmos: MagicMock, sbus: MagicMock) -> None:
    # Arrange
    container = _mock_container({"ID": "ddb-4"})
    container.read_item.side_effect = ValueError("boom")
    cosmos.return_value.get_database_client.return_value.get_container_client.return_value = container
    req = DummyEvent({"detail": {"ddbId": "ddb-4"}})

    # Act
    resp = handler(req)

    # Assert
    assert resp.status_code == 500
    payload = json.loads(resp.get_body())
    assert payload == {"ok": False, "ddbId": "ddb-4", "error": "boom"}


@patch("validation.function_app.ServiceBusClient")
@patch("validation.function_app.CosmosClient")
@patch("validation.function_app.DefaultAzureCredential")
def test_handle_error_updates_failure_status_and_context(cred: MagicMock, cosmos: MagicMock, sbus: MagicMock) -> None:
    # Arrange
    container = _mock_container({"ID": "ddb-5"})
    cosmos.return_value.get_database_client.return_value.get_container_client.return_value = container

    # Act
    handle_error("ddb-5", RuntimeError("failed validation"))

    # Assert
    container.upsert_item.assert_called()


@patch("validation.function_app.ServiceBusClient")
@patch("validation.function_app.CosmosClient")
@patch("validation.function_app.DefaultAzureCredential")
def test_push_item_to_common_queue_preserves_group_and_dedup_fields(cred: MagicMock, cosmos: MagicMock, sbus: MagicMock) -> None:
    # Arrange
    sender = MagicMock()
    sbus.return_value.get_queue_sender.return_value = sender

    # Act
    push_item_to_common_queue(service_type="EIN", jurisdiction="FLORIDA", payload={"ddbId": "ddb-6"}, group_id="FLORIDA#EIN", deduplication_id="dedup-1")

    # Assert
    sender.send_messages.assert_called_once()


def test_validation_service_accepts_custom_clients() -> None:
    # Arrange
    container = _mock_container({"ID": "ddb-7"})
    service = ValidationService(container=container, sender=MagicMock())

    # Act
    result = service.load_record("ddb-7")

    # Assert
    assert result == {"ID": "ddb-7"}
