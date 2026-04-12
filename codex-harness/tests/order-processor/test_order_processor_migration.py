import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "src/lambda/order-processor/handler.py"
TARGET_PATH = ROOT / "src/azure-functions/order-processor/function_app.py"


def load_module(module_name: str, path: Path):
    if path == SOURCE_PATH and "boto3" not in sys.modules:
        boto3_stub = types.SimpleNamespace(
            resource=lambda *_args, **_kwargs: None,
            client=lambda *_args, **_kwargs: None,
        )
        sys.modules["boto3"] = boto3_stub
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def source_module():
    return load_module("order_processor_source", SOURCE_PATH)


@pytest.fixture
def target_module():
    return load_module("order_processor_target", TARGET_PATH)


class FixedDatetime:
    @classmethod
    def now(cls, tz=None):
        class FixedInstant:
            def isoformat(self):
                return "2026-04-12T09:30:00+00:00"

        return FixedInstant()


def build_source_event(method: str, body=None, order_id=None):
    event = {"httpMethod": method, "pathParameters": {}}
    if body is not None:
        event["body"] = body
    if order_id is not None:
        event["pathParameters"] = {"id": order_id}
    return event


def parse_source_response(result):
    return result["statusCode"], result["headers"], json.loads(result["body"])


def parse_target_response(result):
    return result["status_code"], result["headers"], result["body"]


def patch_deterministic_ids(monkeypatch, source_module, target_module):
    monkeypatch.setattr(source_module.uuid, "uuid4", lambda: "order-12345678")
    monkeypatch.setattr(target_module.uuid, "uuid4", lambda: "order-12345678")
    monkeypatch.setattr(source_module, "datetime", FixedDatetime)
    monkeypatch.setattr(target_module, "datetime", FixedDatetime)


class RecordingReceiptStore:
    def __init__(self):
        self.saved = []

    def save_receipt(self, receipt_path, receipt, content_type):
        self.saved.append(
            {
                "path": receipt_path,
                "receipt": receipt,
                "content_type": content_type,
            }
        )


class RecordingNotificationQueue:
    def __init__(self):
        self.messages = []

    def send_order_created(self, message):
        self.messages.append(message)


def build_service(target_module, *, include_queue=True):
    repository = target_module.InMemoryOrderRepository()
    receipt_store = RecordingReceiptStore()
    notification_queue = RecordingNotificationQueue() if include_queue else None
    service = target_module.OrderProcessorService(
        repository=repository,
        receipt_store=receipt_store,
        notification_queue=notification_queue,
    )
    return service, repository, receipt_store, notification_queue


def test_unit_invalid_json_returns_400(target_module):
    service, _, _, _ = build_service(target_module)

    response = service.dispatch("POST", body_text="{bad json")

    status_code, headers, body = parse_target_response(response)
    assert status_code == 400
    assert headers["Content-Type"] == "application/json"
    assert headers["Access-Control-Allow-Origin"] == "*"
    assert body == {"error": "Invalid JSON"}


def test_unit_missing_fields_preserves_field_order(target_module):
    service, _, _, _ = build_service(target_module)

    response = service.dispatch("POST", body_text=json.dumps({"customer_id": "cust-1"}))

    assert parse_target_response(response) == (
        400,
        {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        {"error": "Missing fields: items, total"},
    )


def test_unit_rejects_invalid_items_and_total(target_module):
    service, _, _, _ = build_service(target_module)

    items_response = service.dispatch(
        "POST",
        body_text=json.dumps({"customer_id": "cust-1", "items": [], "total": 10}),
    )
    total_response = service.dispatch(
        "POST",
        body_text=json.dumps({"customer_id": "cust-1", "items": ["sku"], "total": 0}),
    )

    assert parse_target_response(items_response)[2] == {
        "error": "Items must be a non-empty list"
    }
    assert parse_target_response(total_response)[2] == {
        "error": "Total must be a positive number"
    }


def test_unit_generate_receipt_shape_matches_source(target_module):
    order = {
        "id": "order-12345678",
        "customer_id": "cust-1",
        "items": [{"sku": "A-1", "qty": 2}],
        "total": "19.5",
        "created_at": "2026-04-12T09:30:00+00:00",
    }

    receipt = target_module.generate_receipt(order)

    assert receipt == {
        "receipt_id": "RCP-order-12",
        "order_id": "order-12345678",
        "customer_id": "cust-1",
        "items": [{"sku": "A-1", "qty": 2}],
        "total": "19.5",
        "date": "2026-04-12T09:30:00+00:00",
        "message": "Thank you for your order!",
    }


def test_integration_create_order_persists_receipt_and_notification(monkeypatch, target_module):
    monkeypatch.setattr(target_module.uuid, "uuid4", lambda: "order-12345678")
    monkeypatch.setattr(target_module, "datetime", FixedDatetime)
    service, repository, receipt_store, notification_queue = build_service(target_module)

    response = service.dispatch(
        "POST",
        body_text=json.dumps(
            {
                "customer_id": "cust-9",
                "items": [{"sku": "ABC", "qty": 1}],
                "total": 42.75,
            }
        ),
    )

    status_code, _, body = parse_target_response(response)
    assert status_code == 201
    assert body == {"order_id": "order-12345678", "status": "confirmed"}
    assert repository.items["order-12345678"] == {
        "id": "order-12345678",
        "customer_id": "cust-9",
        "items": [{"sku": "ABC", "qty": 1}],
        "total": "42.75",
        "status": "confirmed",
        "created_at": "2026-04-12T09:30:00+00:00",
    }
    assert receipt_store.saved == [
        {
            "path": "receipts/order-12345678.json",
            "receipt": {
                "receipt_id": "RCP-order-12",
                "order_id": "order-12345678",
                "customer_id": "cust-9",
                "items": [{"sku": "ABC", "qty": 1}],
                "total": "42.75",
                "date": "2026-04-12T09:30:00+00:00",
                "message": "Thank you for your order!",
            },
            "content_type": "application/json",
        }
    ]
    assert notification_queue.messages == [
        {
            "event": "order.created",
            "order_id": "order-12345678",
            "customer_id": "cust-9",
            "total": 42.75,
        }
    ]


def test_integration_create_order_skips_notification_when_queue_is_absent(monkeypatch, target_module):
    monkeypatch.setattr(target_module.uuid, "uuid4", lambda: "order-12345678")
    monkeypatch.setattr(target_module, "datetime", FixedDatetime)
    service, repository, receipt_store, notification_queue = build_service(
        target_module,
        include_queue=False,
    )

    response = service.dispatch(
        "POST",
        body_text=json.dumps(
            {
                "customer_id": "cust-9",
                "items": [{"sku": "ABC", "qty": 1}],
                "total": 42.75,
            }
        ),
    )

    assert parse_target_response(response)[0] == 201
    assert repository.items["order-12345678"]["status"] == "confirmed"
    assert receipt_store.saved[0]["path"] == "receipts/order-12345678.json"
    assert notification_queue is None


def test_contract_post_success_matches_lambda(monkeypatch, source_module, target_module):
    patch_deterministic_ids(monkeypatch, source_module, target_module)

    class SourceTable:
        def __init__(self):
            self.items = {}

        def put_item(self, Item):
            self.items[Item["id"]] = Item

        def get_item(self, Key):
            item = self.items.get(Key["id"])
            return {"Item": item} if item else {}

    class SourceDynamo:
        def __init__(self, table):
            self._table = table

        def Table(self, _name):
            return self._table

    class SourceS3:
        def __init__(self):
            self.objects = []

        def put_object(self, **kwargs):
            self.objects.append(kwargs)

    class SourceSqs:
        def __init__(self):
            self.messages = []

        def send_message(self, **kwargs):
            self.messages.append(kwargs)

    source_table = SourceTable()
    source_s3 = SourceS3()
    source_sqs = SourceSqs()
    monkeypatch.setattr(source_module, "dynamodb", SourceDynamo(source_table))
    monkeypatch.setattr(source_module, "s3", source_s3)
    monkeypatch.setattr(source_module, "sqs", source_sqs)
    monkeypatch.setattr(source_module, "NOTIFICATIONS_QUEUE", "queue-name")

    source_result = source_module.lambda_handler(
        build_source_event(
            "POST",
            json.dumps(
                {
                    "customer_id": "cust-9",
                    "items": [{"sku": "ABC", "qty": 1}],
                    "total": 42.75,
                }
            ),
        ),
        None,
    )

    service, _, _, _ = build_service(target_module)
    target_result = service.dispatch(
        "POST",
        body_text=json.dumps(
            {
                "customer_id": "cust-9",
                "items": [{"sku": "ABC", "qty": 1}],
                "total": 42.75,
            }
        ),
    )

    assert parse_target_response(target_result) == parse_source_response(source_result)


def test_contract_get_missing_matches_lambda(source_module, target_module):
    class SourceTable:
        def get_item(self, Key):
            return {}

    class SourceDynamo:
        def Table(self, _name):
            return SourceTable()

    source_module.dynamodb = SourceDynamo()
    source_result = source_module.lambda_handler(build_source_event("GET", order_id="missing"), None)

    service, _, _, _ = build_service(target_module)
    target_result = service.dispatch("GET", order_id="missing")

    assert parse_target_response(target_result) == parse_source_response(source_result)


def test_contract_get_success_matches_lambda(monkeypatch, source_module, target_module):
    stored_order = {
        "id": "order-12345678",
        "customer_id": "cust-9",
        "items": [{"sku": "ABC", "qty": 1}],
        "total": "42.75",
        "status": "confirmed",
        "created_at": "2026-04-12T09:30:00+00:00",
    }

    class SourceTable:
        def get_item(self, Key):
            if Key["id"] == stored_order["id"]:
                return {"Item": stored_order}
            return {}

    class SourceDynamo:
        def Table(self, _name):
            return SourceTable()

    monkeypatch.setattr(source_module, "dynamodb", SourceDynamo())

    source_result = source_module.lambda_handler(
        build_source_event("GET", order_id=stored_order["id"]),
        None,
    )

    service, repository, _, _ = build_service(target_module)
    repository.save_order(stored_order)
    target_result = service.dispatch("GET", order_id=stored_order["id"])

    assert parse_target_response(target_result) == parse_source_response(source_result)


def test_contract_unknown_route_matches_lambda(source_module, target_module):
    source_result = source_module.lambda_handler(build_source_event("DELETE"), None)

    service, _, _, _ = build_service(target_module)
    target_result = service.dispatch("DELETE")

    assert parse_target_response(target_result) == parse_source_response(source_result)
