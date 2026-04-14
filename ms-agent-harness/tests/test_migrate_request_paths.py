import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from agent_harness.orchestrator import api as api_mod
    api_mod._pipeline = None
    api_mod._ado = None
    return TestClient(api_mod.app)


def test_legacy_request_still_404s_when_src_lambda_missing(client, tmp_path):
    """The legacy PROJECT_ROOT/src/lambda/<module>/ path still governs when
    source_paths is empty."""
    resp = client.post("/migrate", json={
        "module": "no-such", "language": "python",
    })
    assert resp.status_code == 404


def test_request_with_source_paths_skips_legacy_check(client, tmp_path):
    handler = tmp_path / "orders_handler.py"
    handler.write_text("def handler(e,c): pass\n")
    resp = client.post("/migrate", json={
        "module": "orders", "language": "python",
        "source_paths": [str(handler)],
    })
    # Accepted (background task queued) — not 404.
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


def test_request_with_missing_source_path_404s(client, tmp_path):
    resp = client.post("/migrate", json={
        "module": "orders", "language": "python",
        "source_paths": [str(tmp_path / "ghost.py")],
    })
    assert resp.status_code == 404


def test_request_with_missing_context_path_404s(client, tmp_path):
    handler = tmp_path / "h.py"
    handler.write_text("pass\n")
    resp = client.post("/migrate", json={
        "module": "orders", "language": "python",
        "source_paths": [str(handler)],
        "context_paths": [str(tmp_path / "ghost.py")],
    })
    assert resp.status_code == 404
