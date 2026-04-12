"""
Migration Orchestrator API — Codex Harness version.

FastAPI application that wraps the Codex CLI migration pipeline.
Deployed as Azure Container App.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path as _P

# Load .env from project root or parent
for _env in [_P(__file__).parent.parent.parent / ".env", _P(__file__).parent.parent.parent.parent / ".env"]:
    if _env.exists():
        for _line in _env.read_text().splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .codex_runner import CodexRunner
from .state_manager import StateManager
from .ado_client import AdoClient

logger = logging.getLogger("orchestrator")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

CODEX_MODEL = os.environ.get("CODEX_MODEL", "o4-mini")
CODEX_API_BASE = os.environ.get("CODEX_API_BASE", "")
CODEX_API_KEY = os.environ.get("CODEX_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
PROJECT_ROOT = os.environ.get("PROJECT_ROOT", str(_P(__file__).parent.parent.parent))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_MIGRATIONS", "3"))

_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
state_manager: StateManager = None
ado_client: AdoClient = None
codex_runner: CodexRunner = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global state_manager, ado_client, codex_runner
    state_manager = StateManager(
        connection_string=os.environ.get("AZURE_STORAGE_CONNECTION_STRING", ""),
        container_name=os.environ.get("STATE_CONTAINER", "migration-state"),
        local_state_dir=os.path.join(PROJECT_ROOT, "config", "state"),
    )
    await state_manager.initialize()
    ado_client = AdoClient(
        org_url=os.environ.get("ADO_ORG_URL", ""),
        project=os.environ.get("ADO_PROJECT", ""),
        repo=os.environ.get("ADO_REPO", ""),
        pat=os.environ.get("ADO_PAT", ""),
    )
    codex_runner = CodexRunner(
        model=CODEX_MODEL, api_base=CODEX_API_BASE,
        api_key=CODEX_API_KEY, project_root=PROJECT_ROOT,
    )
    logger.info("Orchestrator started (Codex harness, max concurrent: %d)", MAX_CONCURRENT)
    yield


app = FastAPI(
    title="Migration Orchestrator (Codex)",
    description="AWS Lambda → Azure Functions migration using Codex CLI",
    version="1.0.0",
    lifespan=lifespan,
)


class MigrationRequest(BaseModel):
    module: str = Field(..., description="Lambda module name (directory under src/lambda/)")
    language: str = Field(..., description="Source language: python, node, java, csharp")
    work_item_id: str = Field(default="LOCAL")
    title: str = Field(default="")
    description: str = Field(default="")
    acceptance_criteria: str = Field(default="")


class MigrationResponse(BaseModel):
    status: str
    module: str
    work_item_id: str
    message: str = ""
    pr_url: str | None = None
    review_score: int | None = None


class HealthResponse(BaseModel):
    status: str = "healthy"
    framework: str = "codex-cli"
    codex_available: bool = False
    state_connected: bool = False
    ado_configured: bool = False


@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        codex_available=codex_runner.is_available() if codex_runner else False,
        state_connected=state_manager.is_connected() if state_manager else False,
        ado_configured=ado_client.is_configured() if ado_client else False,
    )


@app.post("/migrate", response_model=MigrationResponse)
async def migrate_async(req: MigrationRequest, bg: BackgroundTasks):
    _validate(req)
    bg.add_task(_run_pipeline, req)
    return MigrationResponse(
        status="accepted", module=req.module, work_item_id=req.work_item_id,
        message=f"Migration queued for {req.module} ({req.language})",
    )


@app.post("/migrate/sync", response_model=MigrationResponse)
async def migrate_sync(req: MigrationRequest):
    _validate(req)
    return await _run_pipeline(req)


@app.get("/status/{module}")
async def get_status(module: str):
    progress = await state_manager.get_module_progress(module)
    if not progress:
        raise HTTPException(404, f"No data for module '{module}'")
    return progress


@app.get("/status")
async def list_status():
    return await state_manager.get_all_progress()


def _validate(req: MigrationRequest):
    if req.language not in {"python", "node", "java", "csharp"}:
        raise HTTPException(400, f"Invalid language: {req.language}")
    source = os.path.join(PROJECT_ROOT, "src", "lambda", req.module)
    if not os.path.isdir(source):
        raise HTTPException(404, f"Lambda source not found at src/lambda/{req.module}/")


async def _run_pipeline(req: MigrationRequest) -> MigrationResponse:
    async with _semaphore:
        await state_manager.pull_state()

        prompt = f"""Migrate AWS Lambda module '{req.module}' ({req.language}) to Azure Functions.
Work Item: WI-{req.work_item_id} — {req.title}
Description: {req.description}
Acceptance Criteria: {req.acceptance_criteria}

Follow the .codex/AGENTS.md workflow:
0. Sprint Contract: Coder proposes, Tester finalizes
1. Run migration-analyzer on src/lambda/{req.module}/
2. Run migration-coder (TDD-first, ratcheting, generate Bicep)
3. Run migration-tester (three-layer evaluation, structured failure reports)
4. Run migration-reviewer (8-point gate + sprint contract validation)
5. If APPROVED: branch migrate/WI-{req.work_item_id}-{req.module}
6. If BLOCKED: write blocked.md, append to config/state/failures.md
"""
        success, output = await codex_runner.run(prompt=prompt, module=req.module, language=req.language)

        log_dir = os.path.join(PROJECT_ROOT, "migrated_code", "migration-analysis", req.module)
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "codex-output.log"), "w") as f:
            f.write(output)

        await state_manager.push_state()

        blocked = os.path.exists(os.path.join(log_dir, "blocked.md"))
        review_path = os.path.join(log_dir, "review.md")
        approved = False
        if os.path.exists(review_path):
            approved = "APPROVE" in open(review_path).read()

        if blocked:
            return MigrationResponse(status="blocked", module=req.module, work_item_id=req.work_item_id, message="Blocked after 3 attempts.")

        if success and approved:
            pr_url = None
            if ado_client and ado_client.is_configured():
                pr_url = await ado_client.create_pull_request(
                    source_branch=f"migrate/WI-{req.work_item_id}-{req.module}",
                    title=f"[WI-{req.work_item_id}] Migrate {req.module} to Azure Functions",
                    description=f"Auto-generated.\nReview: migrated_code/migration-analysis/{req.module}/review.md",
                    work_item_id=req.work_item_id,
                )
            return MigrationResponse(status="completed", module=req.module, work_item_id=req.work_item_id, message="Migration complete.", pr_url=pr_url)

        return MigrationResponse(status="failed" if not success else "changes_requested", module=req.module, work_item_id=req.work_item_id, message="See review.md for details.")
