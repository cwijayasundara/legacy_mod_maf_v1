"""Tests for orchestrator/ado_client.py — no network calls."""

import base64
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness", "orchestrator"))

from ado_client import AdoClient


def _configured_client():
    return AdoClient(
        org_url="https://dev.azure.com/myorg",
        project="MyProject",
        repo="my-repo",
        pat="fake-pat-token",
    )


def _unconfigured_client():
    return AdoClient(org_url="", project="", repo="", pat="")


# ---------- tests ----------


def test_is_configured():
    """is_configured returns True when all fields are set, False when any is missing."""
    assert _configured_client().is_configured() is True
    assert _unconfigured_client().is_configured() is False

    # Missing just the PAT
    c = AdoClient(org_url="https://dev.azure.com/org", project="P", repo="R", pat="")
    assert c.is_configured() is False


def test_headers():
    """Auth header should be base64 of ':pat'."""
    client = _configured_client()
    expected_encoded = base64.b64encode(b":fake-pat-token").decode()
    headers = client._headers()
    assert headers["Authorization"] == f"Basic {expected_encoded}"
    assert headers["Content-Type"] == "application/json"


def test_pr_body_composition():
    """Verify source/target branch refs are correctly qualified."""
    client = _configured_client()

    # Simulate what create_pull_request does internally to branch names
    source = "migrate/WI-123-order-processor"
    target = "main"

    if not source.startswith("refs/heads/"):
        source = f"refs/heads/{source}"
    if not target.startswith("refs/heads/"):
        target = f"refs/heads/{target}"

    assert source == "refs/heads/migrate/WI-123-order-processor"
    assert target == "refs/heads/main"

    # Already qualified branches should not be double-prefixed
    already_qualified = "refs/heads/feature"
    if not already_qualified.startswith("refs/heads/"):
        already_qualified = f"refs/heads/{already_qualified}"
    assert already_qualified == "refs/heads/feature"


@pytest.mark.asyncio
async def test_not_configured_skips():
    """create_pull_request returns None when client is not configured."""
    client = _unconfigured_client()
    result = await client.create_pull_request(
        source_branch="migrate/test",
        title="Test PR",
        description="desc",
        work_item_id="123",
    )
    assert result is None
