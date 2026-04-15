from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import azure.functions as func

from filing_queue_status.function_app import _process, handler


class DummyTimer:
    pass


@patch("filing_queue_status.function_app.DefaultAzureCredential", return_value=MagicMock())
@patch("filing_queue_status.function_app.ServiceBusClient")
@patch("filing_queue_status.function_app.CosmosClient")
def test_process_returns_bad_body_for_malformed_json(
    cosmos_mock: MagicMock, sbus_mock: MagicMock, cred_mock: MagicMock
) -> None:
    # Arrange
    record = {"body": "not-json"}

    # Act
    result = _process(record)

    # Assert
    assert result == {"ok": False, "reason": "bad_body"}
    cosmos_mock.assert_not_called()
    sbus_mock.assert_not_called()
    cred_mock.assert_not_called()


@patch("filing_queue_status.function_app.DefaultAzureCredential", return_value=MagicMock())
@patch("filing_queue_status.function_app.ServiceBusClient")
@patch("filing_queue_status.function_app.CosmosClient")
def test_process_rejects_missing_required_fields(
    cosmos_mock: MagicMock, sbus_mock: MagicMock, cred_mock: MagicMock
) -> None:
    # Arrange
    record = {"body": json.dumps({"serviceType": "COGS", "jurisdiction": "DELAWARE", "payload": {}})}

    # Act
    result = _process(record)

    # Assert
    assert result["ok"] is False
    assert result["reason"] == "bad_body"
    cosmos_mock.assert_not_called()
    sbus_mock.assert_not_called()
    cred_mock.assert_not_called()


@patch("filing_queue_status.function_app.DefaultAzureCredential", return_value=MagicMock())
@patch("filing_queue_status.function_app.ServiceBusClient")
@patch("filing_queue_status.function_app.CosmosClient")
def test_process_bypasses_delaware_cogs_and_publishes_event(
    cosmos_mock: MagicMock, sbus_mock: MagicMock, cred_mock: MagicMock
) -> None:
    # Arrange
    sender = MagicMock()
    sender.send_messages = AsyncMock()
    sbus_mock.return_value.get_topic_sender.return_value = sender
    cosmos_mock.return_value.get_database_client.return_value.get_container_client.return_value.read_item = MagicMock()
    record = {"body": json.dumps({"serviceType": "COGS", "jurisdiction": "DELAWARE", "payload": {"ddbId": "123"}})}

    # Act
    result = _process(record)

    # Assert
    assert result == {"ok": True, "bypass": "DELAWARE_COGS"}
    sender.send_messages.assert_awaited_once()


@patch("filing_queue_status.function_app.DefaultAzureCredential", return_value=MagicMock())
@patch("filing_queue_status.function_app.ServiceBusClient")
@patch("filing_queue_status.function_app.CosmosClient")
def test_process_returns_success_for_standard_message(
    cosmos_mock: MagicMock, sbus_mock: MagicMock, cred_mock: MagicMock
) -> None:
    # Arrange
    status_container = MagicMock()
    counter_container = MagicMock()
    cosmos_db = MagicMock()
    cosmos_db.get_container_client.side_effect = [status_container, counter_container]
    cosmos_mock.return_value.get_database_client.return_value = cosmos_db
    status_container.upsert_item = MagicMock()
    counter_container.upsert_item = MagicMock()
    status_container.read_item = MagicMock(return_value={"status": "IDLE"})
    sender = MagicMock()
    sender.send_messages = AsyncMock()
    sbus_mock.return_value.get_topic_sender.return_value = sender
    record = {"body": json.dumps({"serviceType": "EIN", "jurisdiction": "FLORIDA", "payload": {"ddbId": "abc"}})}

    # Act
    result = _process(record)

    # Assert
    assert result == {"ok": True, "ddbId": "abc"}
    status_container.upsert_item.assert_called()
    counter_container.upsert_item.assert_called()
    sender.send_messages.assert_awaited_once()


@patch("filing_queue_status.function_app.DefaultAzureCredential", return_value=MagicMock())
@patch("filing_queue_status.function_app.ServiceBusClient")
@patch("filing_queue_status.function_app.CosmosClient")
def test_process_raises_bot_busy_when_status_is_not_idle(
    cosmos_mock: MagicMock, sbus_mock: MagicMock, cred_mock: MagicMock
) -> None:
    # Arrange
    status_container = MagicMock()
    cosmos_db = MagicMock()
    cosmos_db.get_container_client.return_value = status_container
    cosmos_mock.return_value.get_database_client.return_value = cosmos_db
    status_container.read_item = MagicMock(return_value={"status": "IN_PROGRESS"})
    record = {"body": json.dumps({"serviceType": "EIN", "jurisdiction": "FLORIDA", "payload": {"ddbId": "abc"}})}

    # Act / Assert
    try:
        _process(record)
    except RuntimeError as exc:
        assert str(exc) == "bot_busy"
    else:
        raise AssertionError("Expected RuntimeError('bot_busy')")


@patch("filing_queue_status.function_app.DefaultAzureCredential", return_value=MagicMock())
@patch("filing_queue_status.function_app.ServiceBusClient")
@patch("filing_queue_status.function_app.CosmosClient")
def test_handler_returns_batch_failures_for_retryable_errors(
    cosmos_mock: MagicMock, sbus_mock: MagicMock, cred_mock: MagicMock
) -> None:
    # Arrange
    status_container = MagicMock()
    cosmos_db = MagicMock()
    cosmos_db.get_container_client.return_value = status_container
    cosmos_mock.return_value.get_database_client.return_value = cosmos_db
    status_container.read_item = MagicMock(return_value={"status": "IN_PROGRESS"})
    event = {"Records": [{"messageId": "m1", "body": json.dumps({"serviceType": "EIN", "jurisdiction": "FLORIDA", "payload": {"ddbId": "abc"}})}]}

    # Act
    response = handler(event, SimpleNamespace())

    # Assert
    assert response["batchItemFailures"] == [{"itemIdentifier": "m1"}]
    assert response["results"] == []


@patch("filing_queue_status.function_app.DefaultAzureCredential", return_value=MagicMock())
@patch("filing_queue_status.function_app.ServiceBusClient")
@patch("filing_queue_status.function_app.CosmosClient")
def test_handler_invokes_entrypoint_and_returns_results(
    cosmos_mock: MagicMock, sbus_mock: MagicMock, cred_mock: MagicMock
) -> None:
    # Arrange
    status_container = MagicMock()
    counter_container = MagicMock()
    cosmos_db = MagicMock()
    cosmos_db.get_container_client.side_effect = [status_container, counter_container]
    cosmos_mock.return_value.get_database_client.return_value = cosmos_db
    status_container.read_item = MagicMock(return_value={"status": "IDLE"})
    status_container.upsert_item = MagicMock()
    counter_container.upsert_item = MagicMock()
    sender = MagicMock()
    sender.send_messages = AsyncMock()
    sbus_mock.return_value.get_topic_sender.return_value = sender
    event = {"Records": [{"messageId": "m1", "body": json.dumps({"serviceType": "EIN", "jurisdiction": "FLORIDA", "payload": {"ddbId": "abc"}})}]}

    # Act
    response = handler(event, SimpleNamespace())

    # Assert
    assert response["results"] == [{"ok": True, "ddbId": "abc"}]
    assert response["batchItemFailures"] == []
