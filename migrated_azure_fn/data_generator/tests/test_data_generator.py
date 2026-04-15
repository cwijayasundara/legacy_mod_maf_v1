from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import azure.functions as func

from data_generator.function_app import handler


def _request_event(ddb_id: str | None, extra: dict | None = None) -> dict:
    detail: dict[str, object] = {}
    if ddb_id is not None:
        detail["ddbId"] = ddb_id
    event: dict[str, object] = {"detail": detail}
    if extra:
        event.update(extra)
    return event


@patch("data_generator.function_app._send_validator_event")
@patch("data_generator.function_app._write_success_state")
@patch("data_generator.function_app._load_request_record")
@patch("data_generator.function_app.TransformerFactory")
def test_handler_returns_success_and_persists_transformation(
    transformer_factory: MagicMock,
    load_request_record: MagicMock,
    write_success_state: MagicMock,
    send_validator_event: AsyncMock,
) -> None:
    # Arrange
    load_request_record.return_value = {
        "reqInputJSON": {"entity": {"name": "Acme"}},
        "serviceType": "EIN",
        "jurisdiction": "FLORIDA",
        "sourceSystem": "UPSTREAM",
    }
    transformer_factory.transform_to_filer_json.return_value = {"merged": True}

    # Act
    response = handler(_request_event("12345", {"extra": "value"}), None)

    # Assert
    assert response == {"ok": True, "ddbId": "12345"}
    load_request_record.assert_called_once_with("12345")
    transformer_factory.transform_to_filer_json.assert_called_once_with(
        raw_payload={"entity": {"name": "Acme"}},
        service_type="EIN",
        jurisdiction="FLORIDA",
        source_system="UPSTREAM",
    )
    write_success_state.assert_called_once_with("12345", {"merged": True})
    send_validator_event.assert_awaited_once_with("12345")


@patch("data_generator.function_app._send_validator_event")
@patch("data_generator.function_app._write_success_state")
@patch("data_generator.function_app._load_request_record")
def test_handler_returns_missing_ddb_id_when_detail_missing(
    load_request_record: MagicMock,
    write_success_state: MagicMock,
    send_validator_event: AsyncMock,
) -> None:
    # Arrange
    event = {"detail": {"other": "x"}}

    # Act
    response = handler(event, None)

    # Assert
    assert response == {"ok": False, "reason": "missing ddbId"}
    load_request_record.assert_not_called()
    write_success_state.assert_not_called()
    send_validator_event.assert_not_awaited()


@patch("data_generator.function_app._send_validator_event")
@patch("data_generator.function_app._write_success_state")
@patch("data_generator.function_app._load_request_record")
@patch("data_generator.function_app._handle_failure")
def test_handler_returns_failure_payload_when_runtime_error_occurs(
    handle_failure: MagicMock,
    load_request_record: MagicMock,
    write_success_state: MagicMock,
    send_validator_event: AsyncMock,
) -> None:
    # Arrange
    load_request_record.side_effect = RuntimeError("record 12345 not found")

    # Act
    response = handler(_request_event("12345"), None)

    # Assert
    assert response == {"ok": False, "ddbId": "12345", "error": "record 12345 not found"}
    handle_failure.assert_called_once()
    write_success_state.assert_not_called()
    send_validator_event.assert_not_awaited()


@patch("data_generator.function_app._send_validator_event")
@patch("data_generator.function_app._write_success_state")
@patch("data_generator.function_app._load_request_record")
@patch("data_generator.function_app._handle_failure")
def test_handler_treats_whitespace_ddb_id_as_missing(
    handle_failure: MagicMock,
    load_request_record: MagicMock,
    write_success_state: MagicMock,
    send_validator_event: AsyncMock,
) -> None:
    # Arrange
    event = _request_event("   ")

    # Act
    response = handler(event, None)

    # Assert
    assert response == {"ok": False, "reason": "missing ddbId"}
    handle_failure.assert_not_called()
    load_request_record.assert_not_called()
    write_success_state.assert_not_called()
    send_validator_event.assert_not_awaited()


@patch("data_generator.function_app._send_validator_event")
@patch("data_generator.function_app._write_success_state")
@patch("data_generator.function_app._load_request_record")
@patch("data_generator.function_app._handle_failure")
def test_handler_invokes_shared_error_handling_side_effects(
    handle_failure: MagicMock,
    load_request_record: MagicMock,
    write_success_state: MagicMock,
    send_validator_event: AsyncMock,
) -> None:
    # Arrange
    load_request_record.return_value = {
        "reqInputJSON": {},
        "serviceType": "EIN",
    }
    with patch(
        "data_generator.function_app.TransformerFactory.transform_to_filer_json",
        side_effect=ValueError("transform failed"),
    ):
        # Act
        response = handler(_request_event("abc"), None)

    # Assert
    assert response == {"ok": False, "ddbId": "abc", "error": "transform failed"}
    handle_failure.assert_called_once_with("abc", "transform failed")
    write_success_state.assert_not_called()
    send_validator_event.assert_not_awaited()
