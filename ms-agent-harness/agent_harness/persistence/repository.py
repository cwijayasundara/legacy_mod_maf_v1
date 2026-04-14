"""
SQLite migration repository.

Caches analysis results, tracks chunk processing status, and enables
checkpoint/resume for interrupted migrations. Based on Azure Legacy
Modernization Agents' SqliteMigrationRepository.

Tables:
- migration_runs: run metadata (id, module, status, timestamps)
- analysis_cache: cached analyzer output per module (reuse across retries)
- chunk_status: processing status per chunk (for large file migration)
- dependencies: inter-module dependency graph
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("persistence")

DB_PATH = Path(__file__).parent.parent.parent / "migration.db"


class MigrationRepository:
    """SQLite-backed migration state repository."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path or DB_PATH)
        self._initialized = False

    def initialize(self):
        """Create tables if they don't exist."""
        if self._initialized:
            return
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS migration_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    module TEXT NOT NULL,
                    language TEXT NOT NULL,
                    work_item_id TEXT DEFAULT 'LOCAL',
                    status TEXT DEFAULT 'pending',
                    started_at TEXT,
                    completed_at TEXT,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS analysis_cache (
                    module TEXT PRIMARY KEY,
                    analysis_json TEXT NOT NULL,
                    complexity_score INTEGER,
                    complexity_level TEXT,
                    cached_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chunk_status (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    module TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    start_line INTEGER,
                    end_line INTEGER,
                    status TEXT DEFAULT 'pending',
                    tokens_used INTEGER DEFAULT 0,
                    result_text TEXT,
                    error_text TEXT,
                    completed_at TEXT,
                    UNIQUE(module, chunk_index)
                );

                CREATE TABLE IF NOT EXISTS dependencies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_module TEXT NOT NULL,
                    target_module TEXT NOT NULL,
                    dependency_type TEXT,
                    details TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_runs_module ON migration_runs(module);
                CREATE INDEX IF NOT EXISTS idx_chunks_module ON chunk_status(module);

                CREATE TABLE IF NOT EXISTS discovery_runs (
                    repo_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    approved INTEGER DEFAULT 0,
                    approver TEXT,
                    approval_comment TEXT,
                    approved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS discovery_stage_cache (
                    repo_id TEXT NOT NULL,
                    stage_name TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (repo_id, stage_name)
                );

                CREATE TABLE IF NOT EXISTS migrate_repo_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL DEFAULT 'running'
                );

                CREATE TABLE IF NOT EXISTS migrate_repo_module_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_run_id INTEGER NOT NULL,
                    module TEXT NOT NULL,
                    wave INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reason TEXT DEFAULT '',
                    review_score INTEGER,
                    completed_at TEXT,
                    UNIQUE(repo_run_id, module)
                );

                CREATE INDEX IF NOT EXISTS idx_mrr_repo ON migrate_repo_runs(repo_id);
                CREATE INDEX IF NOT EXISTS idx_mrmr_run ON migrate_repo_module_runs(repo_run_id);
            """)
        self._initialized = True

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ─── Migration Runs ────────────────────────────────────────────────

    def start_run(self, module: str, language: str, work_item_id: str = "LOCAL") -> int:
        """Start a new migration run. Returns the run ID."""
        self.initialize()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO migration_runs (module, language, work_item_id, status, started_at) VALUES (?, ?, ?, 'running', ?)",
                (module, language, work_item_id, _now()),
            )
            return cursor.lastrowid

    def complete_run(self, run_id: int, status: str, error: str = ""):
        """Mark a run as completed/blocked/failed."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE migration_runs SET status = ?, completed_at = ?, error_message = ? WHERE id = ?",
                (status, _now(), error, run_id),
            )

    def get_last_run(self, module: str) -> dict | None:
        """Get the most recent run for a module."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM migration_runs WHERE module = ? ORDER BY id DESC LIMIT 1",
                (module,),
            ).fetchone()
            return dict(row) if row else None

    # ─── Analysis Cache ────────────────────────────────────────────────

    def cache_analysis(self, module: str, analysis: dict, score: int, level: str):
        """Cache analyzer results for reuse across retries."""
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO analysis_cache
                   (module, analysis_json, complexity_score, complexity_level, cached_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (module, json.dumps(analysis), score, level, _now()),
            )

    def get_cached_analysis(self, module: str) -> dict | None:
        """Get cached analysis if available (skip re-analysis on retry)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT analysis_json FROM analysis_cache WHERE module = ?",
                (module,),
            ).fetchone()
            return json.loads(row["analysis_json"]) if row else None

    # ─── Chunk Status (for large files) ────────────────────────────────

    def init_chunks(self, module: str, chunk_count: int):
        """Initialize chunk tracking for a large file migration."""
        self.initialize()
        with self._connect() as conn:
            for i in range(chunk_count):
                conn.execute(
                    "INSERT OR IGNORE INTO chunk_status (module, chunk_index, status) VALUES (?, ?, 'pending')",
                    (module, i),
                )

    def update_chunk(self, module: str, chunk_index: int, status: str,
                     tokens_used: int = 0, result: str = "", error: str = ""):
        """Update the status of a specific chunk."""
        with self._connect() as conn:
            conn.execute(
                """UPDATE chunk_status SET status = ?, tokens_used = ?, result_text = ?,
                   error_text = ?, completed_at = ? WHERE module = ? AND chunk_index = ?""",
                (status, tokens_used, result, error, _now(), module, chunk_index),
            )

    def get_last_completed_chunk(self, module: str) -> int:
        """Get the index of the last completed chunk (-1 if none). For resume."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(chunk_index) as last_idx FROM chunk_status WHERE module = ? AND status = 'completed'",
                (module,),
            ).fetchone()
            return row["last_idx"] if row and row["last_idx"] is not None else -1

    def get_chunk_results(self, module: str) -> list[dict]:
        """Get all chunk results for assembly."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chunk_status WHERE module = ? ORDER BY chunk_index",
                (module,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ─── Dependencies ──────────────────────────────────────────────────

    def add_dependency(self, source: str, target: str, dep_type: str = "calls", details: str = ""):
        """Record an inter-module dependency."""
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO dependencies (source_module, target_module, dependency_type, details) VALUES (?, ?, ?, ?)",
                (source, target, dep_type, details),
            )

    def get_dependencies(self, module: str) -> list[dict]:
        """Get all dependencies for a module (both directions)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM dependencies WHERE source_module = ? OR target_module = ?",
                (module, module),
            ).fetchall()
            return [dict(r) for r in rows]

    # ─── Discovery Runs ────────────────────────────────────────────────

    def create_discovery_run(self, repo_id: str):
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO discovery_runs
                   (repo_id, created_at, updated_at, approved)
                   VALUES (?, ?, ?, 0)""",
                (repo_id, _now(), _now()),
            )

    def get_discovery_run(self, repo_id: str) -> dict | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM discovery_runs WHERE repo_id = ?", (repo_id,)
            ).fetchone()
            return dict(row) if row else None

    def approve_backlog(self, repo_id: str, approver: str, comment: str = ""):
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """UPDATE discovery_runs
                   SET approved = 1, approver = ?, approval_comment = ?,
                       approved_at = ?, updated_at = ?
                   WHERE repo_id = ?""",
                (approver, comment, _now(), _now(), repo_id),
            )

    def is_backlog_approved(self, repo_id: str) -> bool:
        run = self.get_discovery_run(repo_id)
        return bool(run and run["approved"])

    # ─── Discovery Stage Cache ─────────────────────────────────────────

    def stage_cache_hit(self, repo_id: str, stage_name: str, input_hash: str) -> bool:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """SELECT input_hash FROM discovery_stage_cache
                   WHERE repo_id = ? AND stage_name = ?""",
                (repo_id, stage_name),
            ).fetchone()
            return bool(row) and row["input_hash"] == input_hash

    def cache_stage(self, repo_id: str, stage_name: str, input_hash: str, artifact_path: str):
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO discovery_stage_cache
                   (repo_id, stage_name, input_hash, artifact_path, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (repo_id, stage_name, input_hash, artifact_path, _now()),
            )

    def get_cached_stage_path(self, repo_id: str, stage_name: str) -> str | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """SELECT artifact_path FROM discovery_stage_cache
                   WHERE repo_id = ? AND stage_name = ?""",
                (repo_id, stage_name),
            ).fetchone()
            return row["artifact_path"] if row else None


    # ─── Migrate Repo Runs ─────────────────────────────────────────────

    def create_migrate_repo_run(self, repo_id: str) -> int:
        self.initialize()
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO migrate_repo_runs (repo_id, started_at, status)
                   VALUES (?, ?, 'running')""",
                (repo_id, _now()),
            )
            return cursor.lastrowid

    def record_migrate_module(self, run_id: int, module: str, wave: int,
                              status: str, reason: str = "",
                              review_score: int | None = None) -> None:
        self.initialize()
        with self._connect() as conn:
            completed = _now() if status in {"completed", "failed", "skipped"} else None
            conn.execute(
                """INSERT INTO migrate_repo_module_runs
                       (repo_run_id, module, wave, status, reason, review_score, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(repo_run_id, module) DO UPDATE SET
                       wave = excluded.wave,
                       status = excluded.status,
                       reason = excluded.reason,
                       review_score = excluded.review_score,
                       completed_at = excluded.completed_at""",
                (run_id, module, wave, status, reason, review_score, completed),
            )

    def complete_migrate_repo_run(self, run_id: int, status: str) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                "UPDATE migrate_repo_runs SET status = ?, completed_at = ? WHERE id = ?",
                (status, _now(), run_id),
            )

    def get_migrate_repo_run(self, repo_id: str) -> dict | None:
        self.initialize()
        with self._connect() as conn:
            run = conn.execute(
                """SELECT * FROM migrate_repo_runs WHERE repo_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (repo_id,),
            ).fetchone()
            if not run:
                return None
            rows = conn.execute(
                """SELECT module, wave, status, reason, review_score, completed_at
                   FROM migrate_repo_module_runs WHERE repo_run_id = ?
                   ORDER BY wave, module""",
                (run["id"],),
            ).fetchall()
            data = dict(run)
            data["modules"] = [dict(r) for r in rows]
            return data


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
