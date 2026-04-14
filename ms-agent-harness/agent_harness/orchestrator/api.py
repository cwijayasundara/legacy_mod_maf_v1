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
from agent_harness.discovery import workflow as discovery_workflow
from agent_harness.discovery import paths as discovery_paths
from agent_harness.persistence.repository import MigrationRepository

logger = logging.getLogger("orchestrator")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_MIGRATIONS", "3"))

_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
_pipeline: MigrationPipeline = None
_ado: AdoClient = None
_discovery_repo: MigrationRepository = MigrationRepository()


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
    _discovery_repo.initialize()
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
    source_paths: list[str] = Field(default_factory=list,
        description="Optional explicit source paths. When provided, bypasses src/lambda/<module>/ lookup.")
    context_paths: list[str] = Field(default_factory=list,
        description="Optional read-only context paths shown to the migrator.")

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
    if req.source_paths:
        for p in req.source_paths:
            if not os.path.exists(p):
                raise HTTPException(404, f"source path not found: {p}")
        for p in req.context_paths:
            if not os.path.exists(p):
                raise HTTPException(404, f"context path not found: {p}")
        return
    # Legacy behaviour.
    source = os.path.join(PROJECT_ROOT, "src", "lambda", req.module)
    if not os.path.isdir(source):
        raise HTTPException(404, f"Lambda source not found at src/lambda/{req.module}/")


async def _run_pipeline(req: MigrationRequest) -> MigrationResponse:
    if _pipeline is None:
        logger.warning("Pipeline not initialized; skipping background run for %s", req.module)
        return MigrationResponse(
            status="skipped", module=req.module, work_item_id=req.work_item_id,
            message="pipeline not initialized",
        )
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


# ─── Discovery models ─────────────────────────────────────────────────────

class DiscoverRequest(BaseModel):
    repo_id: str
    repo_path: str


class DiscoverResponse(BaseModel):
    status: str
    repo_id: str
    artifacts: dict = Field(default_factory=dict)
    stages: list[str] = Field(default_factory=list)
    message: str = ""


class PlanRequest(BaseModel):
    repo_id: str


class PlanResponse(BaseModel):
    repo_id: str
    backlog: list[dict]
    approved: bool


class ApproveRequest(BaseModel):
    approver: str
    comment: str = ""


class DiscoveryStatusResponse(BaseModel):
    repo_id: str
    created_at: str | None = None
    updated_at: str | None = None
    approved: bool = False
    approver: str | None = None
    artifacts: dict = Field(default_factory=dict)


# ─── Discovery endpoints ──────────────────────────────────────────────────

@app.post("/discover", response_model=DiscoverResponse)
async def discover(req: DiscoverRequest):
    if not os.path.isdir(req.repo_path):
        raise HTTPException(404, f"repo_path not found: {req.repo_path}")
    try:
        result = await discovery_workflow.run_discovery(
            repo_id=req.repo_id, repo_path=req.repo_path, repo=_discovery_repo,
        )
    except RuntimeError as e:
        return DiscoverResponse(status="blocked", repo_id=req.repo_id, message=str(e))
    return DiscoverResponse(
        status=result["status"], repo_id=req.repo_id,
        artifacts=result.get("artifacts", {}), stages=result.get("stages", []),
    )


@app.post("/plan", response_model=PlanResponse)
async def plan(req: PlanRequest):
    try:
        backlog = await discovery_workflow.run_planning(req.repo_id, _discovery_repo)
    except FileNotFoundError as e:
        raise HTTPException(409, str(e))
    return PlanResponse(
        repo_id=req.repo_id,
        backlog=[item.model_dump() for item in backlog.items],
        approved=_discovery_repo.is_backlog_approved(req.repo_id),
    )


@app.post("/approve/backlog/{repo_id}")
async def approve_backlog(repo_id: str, req: ApproveRequest):
    run = _discovery_repo.get_discovery_run(repo_id)
    if run is None:
        raise HTTPException(404, f"no discovery run for repo_id={repo_id}")
    _discovery_repo.approve_backlog(repo_id, approver=req.approver, comment=req.comment)
    return {"repo_id": repo_id, "approved": True}


@app.get("/discover/{repo_id}", response_model=DiscoveryStatusResponse)
async def get_discover(repo_id: str):
    run = _discovery_repo.get_discovery_run(repo_id)
    if run is None:
        raise HTTPException(404, f"no discovery run for repo_id={repo_id}")
    artifacts = {}
    for name, p in [
        ("inventory", discovery_paths.inventory_path(repo_id)),
        ("graph", discovery_paths.graph_path(repo_id)),
        ("stories", discovery_paths.stories_path(repo_id)),
        ("backlog", discovery_paths.backlog_path(repo_id)),
    ]:
        if p.exists():
            artifacts[name] = str(p)
    return DiscoveryStatusResponse(
        repo_id=repo_id,
        created_at=run.get("created_at"),
        updated_at=run.get("updated_at"),
        approved=bool(run.get("approved")),
        approver=run.get("approver"),
        artifacts=artifacts,
    )


# ─── Migrate-repo (fan-out) ───────────────────────────────────────────────

from agent_harness import fanout as _fanout


class MigrateRepoRequest(BaseModel):
    repo_id: str


class MigrateRepoModuleStatus(BaseModel):
    module: str
    wave: int
    status: str
    reason: str = ""
    review_score: int | None = None


class MigrateRepoResultBody(BaseModel):
    repo_id: str
    run_id: int
    status: str
    modules: list[MigrateRepoModuleStatus] = Field(default_factory=list)


class MigrateRepoAcceptedBody(BaseModel):
    repo_id: str
    run_id: int | None = None
    status: str = "accepted"


class MigrateRepoRunBody(BaseModel):
    repo_id: str
    id: int | None = None
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    modules: list[MigrateRepoModuleStatus] = Field(default_factory=list)


def _assert_approved_or_409(repo_id: str) -> None:
    if not _discovery_repo.is_backlog_approved(repo_id):
        raise HTTPException(409,
            f"backlog for {repo_id} is not approved; call /approve/backlog/{repo_id}")


@app.post("/migrate-repo", response_model=MigrateRepoAcceptedBody)
async def migrate_repo_async(req: MigrateRepoRequest, bg: BackgroundTasks):
    _assert_approved_or_409(req.repo_id)

    async def _run():
        try:
            await _fanout.migrate_repo(repo_id=req.repo_id,
                                        repo=_discovery_repo,
                                        pipeline=_pipeline)
        except Exception:
            logger.exception("migrate_repo background task failed")

    bg.add_task(_run)
    return MigrateRepoAcceptedBody(repo_id=req.repo_id)


@app.post("/migrate-repo/sync", response_model=MigrateRepoResultBody)
async def migrate_repo_sync(req: MigrateRepoRequest):
    _assert_approved_or_409(req.repo_id)
    try:
        result = await _fanout.migrate_repo(
            repo_id=req.repo_id, repo=_discovery_repo, pipeline=_pipeline,
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return MigrateRepoResultBody(
        repo_id=result.repo_id, run_id=result.run_id, status=result.status,
        modules=[MigrateRepoModuleStatus(**vars(m)) for m in result.modules],
    )


@app.get("/migrate-repo/{repo_id}", response_model=MigrateRepoRunBody)
async def get_migrate_repo(repo_id: str):
    run = _discovery_repo.get_migrate_repo_run(repo_id)
    if run is None:
        raise HTTPException(404, f"no migrate-repo run for {repo_id}")
    return MigrateRepoRunBody(
        repo_id=repo_id, id=run.get("id"),
        status=run.get("status"),
        started_at=run.get("started_at"),
        completed_at=run.get("completed_at"),
        modules=[MigrateRepoModuleStatus(**m) for m in run.get("modules", [])],
    )
