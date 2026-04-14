import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.repo_scanner import scan_repo, sanity_check
from agent_harness.discovery.artifacts import Inventory, ModuleRecord
from agent_harness.discovery import paths

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_repo"


@pytest.mark.asyncio
async def test_scan_repo_writes_inventory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    canned = Inventory(
        repo_meta={"root_path": str(FIXTURE), "total_files": 8,
                   "total_loc": 60,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="orders", language="python",
                         handler_entrypoint="orders/handler.py",
                         loc=14, config_files=["orders/requirements.txt"]),
            ModuleRecord(id="payments", path="payments", language="python",
                         handler_entrypoint="payments/handler.py",
                         loc=18, config_files=["payments/requirements.txt"]),
            ModuleRecord(id="notifications", path="notifications", language="python",
                         handler_entrypoint="notifications/handler.py",
                         loc=12, config_files=["notifications/requirements.txt"]),
        ],
    ).model_dump_json()

    with patch("agent_harness.discovery.repo_scanner._run_agent",
               new=AsyncMock(return_value=canned)):
        out = await scan_repo(repo_id="synth", repo_path=str(FIXTURE))

    inv_path = paths.inventory_path("synth")
    assert inv_path.exists()
    inv = Inventory.model_validate_json(inv_path.read_text())
    assert {m.id for m in inv.modules} == {"orders", "payments", "notifications"}
    assert out == inv


def test_sanity_check_passes_on_valid_inventory():
    inv = Inventory(
        repo_meta={"root_path": str(FIXTURE), "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="orders", language="python",
                         handler_entrypoint="orders/handler.py",
                         loc=10, config_files=[]),
        ],
    )
    report = sanity_check(inv, repo_root=FIXTURE)
    assert report.verdict == "PASS"


def test_sanity_check_fails_on_missing_handler():
    inv = Inventory(
        repo_meta={"root_path": str(FIXTURE), "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="ghost", path="ghost", language="python",
                         handler_entrypoint="ghost/missing.py",
                         loc=10, config_files=[]),
        ],
    )
    report = sanity_check(inv, repo_root=FIXTURE)
    assert report.verdict == "FAIL"
    assert "ghost/missing.py" in report.reasons[0]


def test_sanity_check_fails_on_extension_mismatch():
    inv = Inventory(
        repo_meta={"root_path": str(FIXTURE), "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="orders", language="java",
                         handler_entrypoint="orders/handler.py",
                         loc=10, config_files=[]),
        ],
    )
    report = sanity_check(inv, repo_root=FIXTURE)
    assert report.verdict == "FAIL"
    assert any("language" in r for r in report.reasons)
