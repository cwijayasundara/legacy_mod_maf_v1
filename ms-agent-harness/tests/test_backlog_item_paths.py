import json
from agent_harness.discovery.artifacts import BacklogItem


def test_backlog_item_defaults_empty_lists():
    item = BacklogItem(module="orders", language="python", wave=1)
    assert item.source_paths == []
    assert item.context_paths == []


def test_backlog_item_round_trips_with_paths():
    item = BacklogItem(
        module="orders", language="python", wave=1,
        source_paths=["/abs/a.py"],
        context_paths=["/abs/services/b.py", "/abs/services/c.py"],
    )
    again = BacklogItem.model_validate_json(item.model_dump_json())
    assert again == item


def test_legacy_backlog_item_still_loads():
    """BacklogItem written before Task 1 (no new fields) must still validate."""
    legacy = {"module": "orders", "language": "python", "wave": 1,
              "work_item_id": "S1", "title": "", "description": "",
              "acceptance_criteria": ""}
    item = BacklogItem.model_validate(legacy)
    assert item.source_paths == []
    assert item.context_paths == []


def test_migrate_request_still_superset():
    """BacklogItem minus wave/source_paths/context_paths must still validate as MigrationRequest."""
    from agent_harness.orchestrator.api import MigrationRequest
    item = BacklogItem(module="orders", language="python", wave=1,
                       source_paths=["/a"], context_paths=["/b"])
    payload = json.loads(item.model_dump_json())
    for k in ("wave", "source_paths", "context_paths"):
        payload.pop(k)
    MigrationRequest.model_validate(payload)  # must not raise
