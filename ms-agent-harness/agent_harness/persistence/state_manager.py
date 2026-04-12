"""
State manager — learned rules, progress, coverage baseline.

Same persistent state as codex-harness, with optional Azure Blob sync.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger("state-manager")

STATE_DIR = Path(__file__).parent.parent.parent / "config" / "state"
STATE_FILES = ["learned-rules.md", "migration-progress.txt", "coverage-baseline.txt", "failures.md"]


class StateManager:
    """Manages persistent migration state."""

    def __init__(self, blob_connection_string: str = "", container_name: str = "migration-state"):
        self.state_dir = STATE_DIR
        self.blob_cs = blob_connection_string or os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
        self.container_name = container_name
        self._blob_client = None

    async def initialize(self):
        """Initialize Blob Storage if configured."""
        if self.blob_cs:
            try:
                from azure.storage.blob.aio import BlobServiceClient
                self._blob_client = BlobServiceClient.from_connection_string(self.blob_cs)
                container = self._blob_client.get_container_client(self.container_name)
                try:
                    await container.create_container()
                except Exception:
                    pass
                logger.info("State manager connected to Blob Storage")
            except Exception as e:
                logger.warning("Blob Storage unavailable: %s — using local state only", e)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def is_connected(self) -> bool:
        return self._blob_client is not None

    # ─── Learned Rules ─────────────────────────────────────────────────

    def get_learned_rules(self) -> str:
        return self._read("learned-rules.md")

    def append_learned_rule(self, rule: str):
        path = self.state_dir / "learned-rules.md"
        with open(path, "a") as f:
            f.write(f"\n{rule}\n")

    # ─── Coverage Baseline ─────────────────────────────────────────────

    def get_coverage_baseline(self) -> int:
        content = self._read("coverage-baseline.txt")
        for line in content.split("\n"):
            line = line.strip()
            if line.isdigit():
                return int(line)
        return 80

    def update_coverage_baseline(self, new_coverage: int):
        current = self.get_coverage_baseline()
        if new_coverage > current:
            path = self.state_dir / "coverage-baseline.txt"
            path.write_text(f"# Coverage Ratchet Baseline\n{new_coverage}\n")
            logger.info("Coverage baseline ratcheted: %d%% → %d%%", current, new_coverage)

    # ─── Progress Log ──────────────────────────────────────────────────

    def append_progress(self, session_block: str):
        path = self.state_dir / "migration-progress.txt"
        with open(path, "a") as f:
            f.write(f"\n{session_block}\n")

    # ─── Failures Log ──────────────────────────────────────────────────

    def append_failure(self, failure_entry: str):
        path = self.state_dir / "failures.md"
        with open(path, "a") as f:
            f.write(f"\n{failure_entry}\n")

    # ─── Blob Sync ─────────────────────────────────────────────────────

    async def pull_state(self):
        if not self._blob_client:
            return
        container = self._blob_client.get_container_client(self.container_name)
        for filename in STATE_FILES:
            try:
                blob = container.get_blob_client(filename)
                download = await blob.download_blob()
                content = await download.readall()
                (self.state_dir / filename).write_bytes(content)
            except Exception:
                pass

    async def push_state(self):
        if not self._blob_client:
            return
        container = self._blob_client.get_container_client(self.container_name)
        for filename in STATE_FILES:
            path = self.state_dir / filename
            if path.exists():
                blob = container.get_blob_client(filename)
                with open(path, "rb") as f:
                    await blob.upload_blob(f, overwrite=True)

    # ─── Internal ──────────────────────────────────────────────────────

    def _read(self, filename: str) -> str:
        path = self.state_dir / filename
        return path.read_text() if path.exists() else ""
