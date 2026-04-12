"""
State Manager

Persists migration state (learned-rules, progress, coverage-baseline, failures)
to Azure Blob Storage so it survives across Container App restarts.

In local dev mode (no connection string), operates on local filesystem only.

Flow:
  pull_state()  — download state/ files from Blob → local disk (at start of migration)
  push_state()  — upload local state/ files → Blob Storage (after migration completes)
"""

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger("state-manager")

# Files that constitute persistent migration state
STATE_FILES = [
    "learned-rules.md",
    "migration-progress.txt",
    "coverage-baseline.txt",
    "failures.md",
]


@dataclass
class ModuleProgress:
    """Parsed migration progress for a single module."""
    module: str = ""
    status: str = "unknown"
    gates_passed: list[int] = field(default_factory=list)
    gates_failed: list[int] = field(default_factory=list)
    coverage: float | None = None
    reviewer_score: int | None = None
    blocked: bool = False
    block_reason: str = ""


class StateManager:
    """Manages persistent state in Azure Blob Storage + local filesystem."""

    def __init__(self, connection_string: str, container_name: str, local_state_dir: str):
        self.connection_string = connection_string
        self.container_name = container_name
        self.local_state_dir = local_state_dir
        self._blob_client = None
        self._is_cloud = bool(connection_string)

    async def initialize(self):
        """Initialize Blob Storage client if connection string is provided."""
        if self._is_cloud:
            try:
                from azure.storage.blob.aio import BlobServiceClient
                self._blob_client = BlobServiceClient.from_connection_string(
                    self.connection_string
                )
                # Ensure container exists
                container = self._blob_client.get_container_client(self.container_name)
                try:
                    await container.create_container()
                    logger.info("Created state container: %s", self.container_name)
                except Exception:
                    pass  # Container already exists
                logger.info("State manager connected to Azure Blob Storage")
            except ImportError:
                logger.warning("azure-storage-blob not installed — falling back to local state")
                self._is_cloud = False
            except Exception as e:
                logger.warning("Blob Storage connection failed: %s — falling back to local state", e)
                self._is_cloud = False
        else:
            logger.info("State manager running in local-only mode (no Blob Storage)")

        # Ensure local state directory exists
        os.makedirs(self.local_state_dir, exist_ok=True)

    def is_connected(self) -> bool:
        """Check if Blob Storage is connected."""
        return self._is_cloud and self._blob_client is not None

    async def pull_state(self):
        """Download state files from Blob Storage to local disk."""
        if not self._is_cloud:
            logger.debug("Local-only mode — skip pull")
            return

        container = self._blob_client.get_container_client(self.container_name)
        for filename in STATE_FILES:
            blob = container.get_blob_client(filename)
            local_path = os.path.join(self.local_state_dir, filename)
            try:
                download = await blob.download_blob()
                content = await download.readall()
                with open(local_path, "wb") as f:
                    f.write(content)
                logger.debug("Pulled state/%s from Blob Storage", filename)
            except Exception:
                # File doesn't exist in Blob yet — use local version or create empty
                if not os.path.exists(local_path):
                    logger.debug("state/%s not in Blob Storage, using local", filename)

    async def push_state(self):
        """Upload local state files to Blob Storage."""
        if not self._is_cloud:
            logger.debug("Local-only mode — skip push")
            return

        container = self._blob_client.get_container_client(self.container_name)
        for filename in STATE_FILES:
            local_path = os.path.join(self.local_state_dir, filename)
            if os.path.exists(local_path):
                blob = container.get_blob_client(filename)
                with open(local_path, "rb") as f:
                    await blob.upload_blob(f, overwrite=True)
                logger.debug("Pushed state/%s to Blob Storage", filename)

    async def get_module_progress(self, module: str) -> ModuleProgress | None:
        """Parse migration-progress.txt for a specific module's latest session."""
        progress_path = os.path.join(self.local_state_dir, "migration-progress.txt")
        if not os.path.exists(progress_path):
            return None

        content = open(progress_path).read()
        # Find the last session block for this module
        sessions = content.split("=== Session")
        latest = None
        for session in reversed(sessions):
            if f"module: {module}" in session:
                latest = session
                break

        if not latest:
            return None

        # Parse key-value pairs from the session block
        progress = ModuleProgress(module=module)
        for line in latest.split("\n"):
            line = line.strip()
            if line.startswith("recommendation:"):
                val = line.split(":", 1)[1].strip()
                progress.status = val.lower()
            elif line.startswith("coverage:"):
                try:
                    progress.coverage = float(line.split(":", 1)[1].strip().rstrip("%"))
                except ValueError:
                    pass
            elif line.startswith("reviewer_score:"):
                try:
                    progress.reviewer_score = int(line.split(":", 1)[1].strip().split("/")[0])
                except ValueError:
                    pass
            elif line.startswith("blocked:"):
                progress.blocked = "true" in line.lower()
            elif line.startswith("block_reason:"):
                progress.block_reason = line.split(":", 1)[1].strip()
            elif line.startswith("gates_passed:"):
                try:
                    val = line.split(":", 1)[1].strip().strip("[]")
                    progress.gates_passed = [int(x.strip()) for x in val.split(",") if x.strip()]
                except ValueError:
                    pass
            elif line.startswith("gates_failed:"):
                try:
                    val = line.split(":", 1)[1].strip().strip("[]")
                    progress.gates_failed = [int(x.strip()) for x in val.split(",") if x.strip()]
                except ValueError:
                    pass

        return progress

    async def get_all_progress(self) -> list[ModuleProgress]:
        """Get progress for all modules that have been migrated."""
        progress_path = os.path.join(self.local_state_dir, "migration-progress.txt")
        if not os.path.exists(progress_path):
            return []

        content = open(progress_path).read()
        # Extract unique module names
        modules = set()
        for line in content.split("\n"):
            if line.strip().startswith("module:"):
                modules.add(line.split(":", 1)[1].strip())

        results = []
        for module in sorted(modules):
            progress = await self.get_module_progress(module)
            if progress:
                results.append(progress)
        return results
