"""
Migration Orchestrator API — MS Agent Framework version.

Same REST interface as codex-harness, but runs agents in-process
using Microsoft Agent Framework instead of spawning Codex CLI.
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path as _P

# Load .env from project root or parent
for _env in [_P(__file__).parent.parent / ".env", _P(__file__).parent.parent.parent / ".env"]:
    if _env.exists():
        for _line in _env.read_text().splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

# Add parent to path for agent imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_harness.pipeline import MigrationPipeline, PipelineResult
from agent_harness.orchestrator.ado_client import AdoClient

logger = logging.getLogger("orchestrator")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_MIGRATIONS", "3"))

_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
_pipeline: MigrationPipeline = None
_ado: AdoClient = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pipeline, _ado
    _pipeline = MigrationPipeline(project_root=PROJECT_ROOT)
    await _pipeline.initialize()
    _ado = AdoClient(
        org_url=os.environ.get("ADO_ORG_URL", ""),
        project=os.environ.get("ADO_PROJECT", ""),
        repo=os.environ.get("ADO_REPO", ""),
        pat=os.environ.get("ADO_PAT", ""),
    )
    logger.info("Orchestrator started (MS Agent Framework, max concurrent: %d)", MAX_CONCURRENT)
    yield


app = FastAPI(
    title="Migration Orchestrator (MS Agent Framework)",
    description="AWS Lambda → Azure Functions migration using Microsoft Agent Framework agents",
    version="1.0.0",
    lifespan=lifespan,
)


# ─── Models ────────────────────────────────────────────────────────────────

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

class StatusResponse(BaseModel):
    module: str
    status: str
    gates_passed: list[int] = []
    gates_failed: list[int] = []
    coverage: float | None = None
    reviewer_score: int | None = None

class HealthResponse(BaseModel):
    status: str = "healthy"
    framework: str = "microsoft-agent-framework"
    foundry_configured: bool = False
    ado_configured: bool = False


# ─── Endpoints ─────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        foundry_configured=bool(os.environ.get("FOUNDRY_PROJECT_ENDPOINT")),
        ado_configured=_ado.is_configured() if _ado else False,
    )


@app.post("/migrate", response_model=MigrationResponse)
async def migrate_async(req: MigrationRequest, bg: BackgroundTasks):
    """Start migration in background. Returns immediately."""
    _validate(req)
    bg.add_task(_run_pipeline, req)
    return MigrationResponse(
        status="accepted", module=req.module, work_item_id=req.work_item_id,
        message=f"Migration queued for {req.module} ({req.language})",
    )


@app.post("/migrate/sync", response_model=MigrationResponse)
async def migrate_sync(req: MigrationRequest):
    """Run migration synchronously (blocks until complete). For demos."""
    _validate(req)
    return await _run_pipeline(req)


@app.get("/status/{module}", response_model=StatusResponse)
async def status(module: str):
    progress = await _pipeline.state.get_module_progress(module) if _pipeline else None
    if not progress:
        raise HTTPException(404, f"No data for module '{module}'")
    return StatusResponse(module=module, **progress.__dict__)


@app.get("/status", response_model=list[StatusResponse])
async def status_all():
    items = await _pipeline.state.get_all_progress() if _pipeline else []
    return [StatusResponse(module=p.module, **p.__dict__) for p in items]


# ─── Internal ──────────────────────────────────────────────────────────────

def _validate(req: MigrationRequest):
    if req.language not in {"python", "node", "java", "csharp"}:
        raise HTTPException(400, f"Invalid language: {req.language}")
    source = os.path.join(PROJECT_ROOT, "src", "lambda", req.module)
    if not os.path.isdir(source):
        raise HTTPException(404, f"Lambda source not found at src/lambda/{req.module}/")


async def _run_pipeline(req: MigrationRequest) -> MigrationResponse:
    async with _semaphore:
        result: PipelineResult = await _pipeline.run(
            module=req.module,
            language=req.language,
            work_item_id=req.work_item_id,
            title=req.title,
            description=req.description,
            acceptance_criteria=req.acceptance_criteria,
        )

        pr_url = None
        if result.status == "completed" and _ado and _ado.is_configured():
            pr_url = await _ado.create_pull_request(
                source_branch=f"migrate/WI-{req.work_item_id}-{req.module}",
                title=f"[WI-{req.work_item_id}] Migrate {req.module} ({req.language}) to Azure Functions",
                description=f"Auto-generated by MS Agent Framework migration pipeline.\n\n"
                            f"Review: migration-analysis/{req.module}/review.md",
                work_item_id=req.work_item_id,
            )

        return MigrationResponse(
            status=result.status,
            module=result.module,
            work_item_id=req.work_item_id,
            message=result.message,
            pr_url=pr_url,
            review_score=result.review_score,
        )
