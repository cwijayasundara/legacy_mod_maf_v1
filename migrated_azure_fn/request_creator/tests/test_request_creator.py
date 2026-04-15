from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import azure.functions as func

from request_creator.function_app import _lookup_jurisdiction_settings, handler


class DummyRequest:
    def __init__(self, body: object) -> None:
        self._body = body
        self.method = "POST"
        self.url = "http://localhost/api/autograf/filing/request"
        self.headers: dict[str, str] = {}

    def get_json(self) -> object:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


@patch("request_creator.function_app._publish_downstream_event")
@patch("request_creator.function_app._upsert_request_record")
@patch("request_creator.function_app._lookup_jurisdiction_settings")
def test_handler_returns_400_when_service_type_missing(
    lookup_settings: MagicMock,
    upsert_request_record: MagicMock,
    publish_downstream_event: MagicMock,
) -> None:
    # Arrange
    req = DummyRequest({"jurisdiction": "FLORIDA"})

    # Act
    resp = handler(req)

    # Assert
    assert isinstance(resp, func.HttpResponse)
    assert resp.status_code == 400
    assert json.loads(resp.get_body()) == {
        "error": {
            "code": "BAD_REQUEST",
            "message": "serviceType required",
            "details": [],
        }
    }
    lookup_settings.assert_not_called()
    upsert_request_record.assert_not_called()
    publish_downstream_event.assert_not_called()


@patch("request_creator.function_app._publish_downstream_event")
@patch("request_creator.function_app._upsert_request_record")
@patch("request_creator.function_app._lookup_jurisdiction_settings")
def test_handler_returns_400_when_request_body_is_invalid_json(
    lookup_settings: MagicMock,
    upsert_request_record: MagicMock,
    publish_downstream_event: MagicMock,
) -> None:
    # Arrange
    req = DummyRequest(ValueError("invalid json"))

    # Act
    resp = handler(req)

    # Assert
    assert resp.status_code == 400
    payload = json.loads(resp.get_body())
    assert payload["error"]["code"] == "BAD_REQUEST"
    lookup_settings.assert_not_called()
    upsert_request_record.assert_not_called()
    publish_downstream_event.assert_not_called()


@patch("request_creator.function_app._publish_downstream_event")
@patch("request_creator.function_app._upsert_request_record")
@patch("request_creator.function_app._lookup_jurisdiction_settings")
def test_handler_returns_400_when_cid_pin_required_but_missing(
    lookup_settings: MagicMock,
    upsert_request_record: MagicMock,
    publish_downstream_event: MagicMock,
) -> None:
    # Arrange
    lookup_settings.return_value = {"enabled": True, "cidPinRequired": True}
    req = DummyRequest({
        "serviceType": "EIN",
        "jurisdiction": "FLORIDA",
        "eventType": "UPSTREAM",
        "source": "UPSTREAM",
    })

    # Act
    resp = handler(req)

    # Assert
    assert resp.status_code == 400
    assert json.loads(resp.get_body())["error"]["message"] == "CID/PIN required"
    lookup_settings.assert_called_once_with("FLORIDA", "EIN")
    upsert_request_record.assert_not_called()
    publish_downstream_event.assert_not_called()


@patch("request_creator.function_app._publish_downstream_event")
@patch("request_creator.function_app._upsert_request_record")
@patch("request_creator.function_app._lookup_jurisdiction_settings")
def test_handler_returns_409_when_jurisdiction_service_is_disabled(
    lookup_settings: MagicMock,
    upsert_request_record: MagicMock,
    publish_downstream_event: MagicMock,
) -> None:
    # Arrange
    lookup_settings.return_value = {"enabled": False, "cidPinRequired": False}
    req = DummyRequest({
        "serviceType": "EIN",
        "jurisdiction": "FLORIDA",
        "eventType": "UPSTREAM",
    })

    # Act
    resp = handler(req)

    # Assert
    assert resp.status_code == 409
    assert json.loads(resp.get_body())["error"]["code"] == "CONFLICT"
    lookup_settings.assert_called_once_with("FLORIDA", "EIN")
    upsert_request_record.assert_not_called()
    publish_downstream_event.assert_not_called()


@patch("request_creator.function_app._publish_downstream_event")
@patch("request_creator.function_app._upsert_request_record")
@patch("request_creator.function_app._lookup_jurisdiction_settings")
def test_handler_returns_200_and_persists_request_record(
    lookup_settings: MagicMock,
    upsert_request_record: MagicMock,
    publish_downstream_event: MagicMock,
) -> None:
    # Arrange
    lookup_settings.return_value = {"enabled": True, "cidPinRequired": False}
    req = DummyRequest({
        "serviceType": "EIN",
        "jurisdiction": "FLORIDA",
        "eventType": "UPSTREAM",
        "cidPin": "1234",
    })

    # Act
    resp = handler(req)

    # Assert
    assert resp.status_code == 200
    payload = json.loads(resp.get_body())
    assert payload["status"] == "CREATED"
    assert isinstance(payload["ddbId"], str)
    lookup_settings.assert_called_once_with("FLORIDA", "EIN")
    upsert_request_record.assert_called_once()
    publish_downstream_event.assert_called_once()


@patch("request_creator.function_app._publish_downstream_event")
@patch("request_creator.function_app._upsert_request_record")
@patch("request_creator.function_app._lookup_jurisdiction_settings")
def test_handler_defaults_source_to_upstream(
    lookup_settings: MagicMock,
    upsert_request_record: MagicMock,
    publish_downstream_event: MagicMock,
) -> None:
    # Arrange
    lookup_settings.return_value = {"enabled": True, "cidPinRequired": False}
    req = DummyRequest({"serviceType": "EIN", "eventType": "UPSTREAM"})

    # Act
    resp = handler(req)

    # Assert
    assert resp.status_code == 200
    call_kwargs = upsert_request_record.call_args.kwargs
    assert call_kwargs["request_body"]["source"] == "UPSTREAM"
    lookup_settings.assert_called_once_with(None, "EIN")
    publish_downstream_event.assert_called_once()


@patch("request_creator.function_app._publish_downstream_event")
@patch("request_creator.function_app._upsert_request_record")
@patch("request_creator.function_app._lookup_jurisdiction_settings")
def test_handler_adds_branch_to_downstream_event_detail_for_branching_events(
    lookup_settings: MagicMock,
    upsert_request_record: MagicMock,
    publish_downstream_event: MagicMock,
) -> None:
    # Arrange
    lookup_settings.return_value = {"enabled": True, "cidPinRequired": False}
    req = DummyRequest({
        "serviceType": "EIN",
        "jurisdiction": "FLORIDA",
        "eventType": "MERGE_EVIDENCE",
        "cidPin": "1234",
    })

    # Act
    resp = handler(req)

    # Assert
    assert resp.status_code == 200
    publish_downstream_event.assert_called_once()
    detail = publish_downstream_event.call_args.kwargs["detail"]
    assert detail["branch"] == "MERGE_EVIDENCE"


@patch("request_creator.function_app.DefaultAzureCredential")
@patch("request_creator.function_app.CosmosClient")
def test_lookup_jurisdiction_settings_reads_from_cosmos(cred: MagicMock, cosmos: MagicMock) -> None:
    # Arrange
    container = MagicMock()
    container.read_item.return_value = {"enabled": True, "cidPinRequired": False}
    cosmos.return_value.get_database_client.return_value.get_container_client.return_value = container

    # Act
    result = _lookup_jurisdiction_settings("FLORIDA", "EIN")

    # Assert
    assert result == {"enabled": True, "cidPinRequired": False}
    container.read_item.assert_called_once()
