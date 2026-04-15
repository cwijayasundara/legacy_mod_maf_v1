"""Kick off AWS Lambda -> Azure Functions migration end-to-end.

All knobs come from .env (loaded from the repo root):

    # --- required auth (pick one) ---
    OPENAI_API_KEY=sk-...
    # or
    FOUNDRY_PROJECT_ENDPOINT=https://your-project.services.ai.azure.com

    # --- optional ---
    OPENAI_MODEL=gpt-4o           # default model for all agent roles
    SOURCE_DIR=aws_legacy/generated_code
    MIGRATED_DIR=azure_fn         # where generated Azure Functions are written
    REPO_ID=legacy-aws            # logical id for the discovery/migration run
    ORCHESTRATOR_PORT=8000

Relative paths in SOURCE_DIR / MIGRATED_DIR are resolved against the repo root.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent
HARNESS_DIR = REPO_ROOT / "ms-agent-harness"
STARTUP_TIMEOUT_S = 60


def _resolve(path_str: str) -> Path:
    p = Path(path_str).expanduser()
    return p if p.is_absolute() else (REPO_ROOT / p).resolve()


def preflight() -> None:
    """Fail fast on import-time errors and signature mismatches in the pipeline hot path.

    Catches the class of bugs that otherwise surface only mid-migration: async/sync
    mismatches, wrong argument arity between pipeline stages, return-key drift between
    agents, and chunker/complexity-scorer type errors. Cheap (<1s) — always runs.
    """
    import inspect

    if str(HARNESS_DIR) not in sys.path:
        sys.path.insert(0, str(HARNESS_DIR))

    print("[preflight] importing pipeline modules")
    from agent_harness import analyzer, coder, pipeline, reviewer, security_reviewer, tester  # noqa: F401
    from agent_harness.context import chunker
    from agent_harness.context.complexity_scorer import ComplexityResult, score_complexity
    from agent_harness.discovery import workflow  # noqa: F401

    print("[preflight] checking signatures")

    # 1. pipeline.run -> propose_contract(module, language, analysis, acceptance_criteria)
    pc_params = list(inspect.signature(coder.propose_contract).parameters)
    required = {"module", "language", "analysis_path", "acceptance_criteria"}
    missing = required - set(pc_params)
    if missing:
        raise RuntimeError(f"coder.propose_contract missing params: {missing}")

    # 2. score_complexity must be sync (analyzer calls it without await)
    if inspect.iscoroutinefunction(score_complexity):
        raise RuntimeError("score_complexity is async but analyzer calls it sync")

    # 3. ComplexityResult must be a dataclass with .score/.level (not dict-indexed)
    import dataclasses
    cr_fields = {f.name for f in dataclasses.fields(ComplexityResult)}
    if not {"score", "level"}.issubset(cr_fields):
        raise RuntimeError(f"ComplexityResult fields {cr_fields} missing score/level")

    # 4. Chunker must tolerate Path input + Chunk must be str() friendly
    sample = HARNESS_DIR / "requirements.txt"
    if sample.is_file():
        chunker.needs_chunking(sample)  # must not raise on Path
        chunks = chunker.chunk_file(sample)
        if chunks and not isinstance(str(chunks[0]), str):
            raise RuntimeError("Chunk.__str__ broken")

    # 5. reviewer return contract (pipeline.py reads 'confidence' + 'recommendation')
    rev_src = (HARNESS_DIR / "agent_harness" / "reviewer.py").read_text()
    if '"confidence"' not in rev_src or '"recommendation"' not in rev_src:
        raise RuntimeError("reviewer return dict missing confidence/recommendation keys")

    # 6. Stale cache drift: if migration.db exists AND an old-layout discovery/ dir
    # exists at the repo root, the DB caches paths outside MIGRATED_DIR and will
    # re-serve them on cache hit while downstream stages look under MIGRATED_DIR.
    legacy_dirs = [REPO_ROOT / n for n in ("discovery", "migration-analysis", "src")]
    db_path = HARNESS_DIR / "migration.db"
    stale = [str(d) for d in legacy_dirs if d.is_dir()]
    if stale and db_path.exists():
        raise RuntimeError(
            "stale artifact layout detected. Cached paths in ms-agent-harness/migration.db "
            "point at old locations outside MIGRATED_DIR. Remove:\n  "
            + "\n  ".join(stale + [str(db_path)])
            + "\nthen rerun."
        )

    print("[preflight] ok")


def start_orchestrator(source_dir: Path, output_dir: Path, port: int, model: str | None) -> subprocess.Popen:
    env = os.environ.copy()
    env["PROJECT_ROOT"] = str(REPO_ROOT)
    env["MIGRATED_DIR"] = str(output_dir)
    env.setdefault("MAX_CONCURRENT_MIGRATIONS", "5")
    env.setdefault("OPENAI_CALL_CONCURRENCY", "8")
    env.setdefault("OPENAI_REQUESTS_PER_MINUTE", "300")
    env.setdefault("OPENAI_SLIDING_WINDOW_SECONDS", "60")
    env.setdefault("AGENT_MAX_RETRIES", "4")
    env.setdefault("DISCOVERY_FAST_STORIES", "1")
    env.setdefault("DISCOVERY_BRD_CONCURRENCY", "6")
    env.setdefault("DISCOVERY_ARCHITECT_CONCURRENCY", "6")
    env.setdefault("POLL_INTERVAL_S", "5")
    if model:
        env["FOUNDRY_MODEL"] = model
    cmd = [
        sys.executable, "-m", "uvicorn",
        "agent_harness.orchestrator.api:app",
        "--host", "127.0.0.1", "--port", str(port),
    ]
    print(f"[orchestrator] starting on :{port} (model={env.get('FOUNDRY_MODEL', 'default')})")
    print(f"[orchestrator] source={source_dir}")
    print(f"[orchestrator] target={output_dir}")
    proc = subprocess.Popen(cmd, cwd=HARNESS_DIR, env=env)

    deadline = time.time() + STARTUP_TIMEOUT_S
    with httpx.Client(timeout=2.0) as client:
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"orchestrator exited early (code {proc.returncode})")
            try:
                r = client.get(f"http://127.0.0.1:{port}/openapi.json")
                if r.status_code == 200:
                    print("[orchestrator] ready")
                    return proc
            except httpx.HTTPError:
                pass
            time.sleep(1.0)
    proc.terminate()
    raise RuntimeError("orchestrator did not become ready in time")


def run_migration(source_dir: Path, repo_id: str, port: int) -> None:
    base_url = f"http://127.0.0.1:{port}"
    with httpx.Client(base_url=base_url, timeout=None) as client:
        overall_started = time.perf_counter()
        print(f"[discover] scanning {source_dir}")
        discover_started = time.perf_counter()
        r = client.post("/discover", json={"repo_id": repo_id, "repo_path": str(source_dir)})
        r.raise_for_status()
        body = r.json()
        print(f"[discover] completed in {time.perf_counter() - discover_started:.2f}s")
        print(f"[discover] {body}")
        if body.get("status") != "ok":
            raise RuntimeError(
                f"discovery failed: {body.get('status')} — {body.get('message', '(no message)')}. "
                f"Inspect {source_dir} relative to inventory/graph/brd under "
                f"{os.getenv('MIGRATED_DIR', 'azure_fn')}/discovery/{repo_id}/."
            )

        # Guard: scanner sometimes returns 0 modules if the repo layout is unusual.
        # Fail fast here rather than burning BRD/architect tokens on nothing.
        import json as _json
        inv_path = _resolve(os.getenv("MIGRATED_DIR", "azure_fn")) / "discovery" / repo_id / "inventory.json"
        if inv_path.is_file():
            modules = _json.loads(inv_path.read_text()).get("modules", [])
            if not modules:
                raise RuntimeError(
                    f"scanner produced 0 modules for {source_dir}. "
                    f"Check {inv_path}. Clear cache (delete discovery dir + migration.db) and rerun."
                )
            print(f"[discover] inventory has {len(modules)} module(s): {[m['id'] for m in modules]}")

        print(f"[plan] building backlog for {repo_id}")
        plan_started = time.perf_counter()
        r = client.post("/plan", json={"repo_id": repo_id})
        r.raise_for_status()
        plan_resp = r.json()
        print(f"[plan] completed in {time.perf_counter() - plan_started:.2f}s")
        print(f"[plan] {len(plan_resp.get('backlog', []))} backlog items")

        print(f"[approve] backlog for {repo_id}")
        approve_started = time.perf_counter()
        r = client.post(
            f"/approve/backlog/{repo_id}",
            json={"approver": "run_migration.py", "comment": "auto-approved by driver script"},
        )
        r.raise_for_status()
        print(f"[approve] completed in {time.perf_counter() - approve_started:.2f}s")
        print(f"[approve] {r.json()}")

        print("[migrate] starting fanout (async; polling every 15s)")
        r = client.post("/migrate-repo", json={"repo_id": repo_id})
        r.raise_for_status()
        print(f"[migrate] accepted: {r.json()}")

        start = time.time()
        poll_interval = int(os.getenv("POLL_INTERVAL_S", "15"))
        last_summary: str | None = None
        while True:
            time.sleep(poll_interval)
            s = client.get(f"/migrate-repo/{repo_id}")
            if s.status_code == 404:
                # Run row may not be visible immediately after POST.
                continue
            s.raise_for_status()
            body = s.json()
            modules = body.get("modules", [])
            status = body.get("status", "running")
            elapsed = int(time.time() - start)
            hms = f"{elapsed // 3600:02d}:{(elapsed % 3600) // 60:02d}:{elapsed % 60:02d}"

            counts: dict[str, int] = {}
            for m in modules:
                counts[m["status"]] = counts.get(m["status"], 0) + 1
            summary = " ".join(
                f"{k}={v}" for k, v in sorted(counts.items())
            ) or "no modules yet"
            line = f"[progress] {hms}  overall={status}  {summary}"
            if line != last_summary:
                print(line)
                running = [m for m in modules if m["status"] == "running"]
                for m in running:
                    print(f"           ▶ wave {m.get('wave')}: {m['module']}")
                done = [m for m in modules if m["status"] == "completed"]
                for m in done[-3:]:  # show up to 3 most recent completions
                    score = m.get("review_score")
                    score_s = f" score={score}/100" if score is not None else ""
                    print(f"           ✓ {m['module']}{score_s}")
                last_summary = line

            if status not in ("running", "accepted", ""):
                print(f"[migrate] final: {body}")
                print(f"[timing] total run {time.perf_counter() - overall_started:.2f}s")
                break


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")

    if not os.getenv("OPENAI_API_KEY") and not os.getenv("FOUNDRY_PROJECT_ENDPOINT"):
        print("ERROR: set OPENAI_API_KEY or FOUNDRY_PROJECT_ENDPOINT in .env", file=sys.stderr)
        return 2

    source_dir = _resolve(os.getenv("SOURCE_DIR", "aws_legacy/generated_code"))
    output_dir = _resolve(os.getenv("MIGRATED_DIR", "azure_fn"))
    repo_id = os.getenv("REPO_ID", "legacy-aws")
    port = int(os.getenv("ORCHESTRATOR_PORT", "8000"))
    model = os.getenv("OPENAI_MODEL") or os.getenv("FOUNDRY_MODEL")

    if not source_dir.is_dir():
        print(f"ERROR: source not found: {source_dir}", file=sys.stderr)
        return 2

    os.environ["PROJECT_ROOT"] = str(REPO_ROOT)
    os.environ["MIGRATED_DIR"] = str(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Fresh DB every run avoids stale cache entries (analyzer path, stage cache,
    # migrate-repo runs) pointing at files the previous run wrote and a cleanup
    # later deleted. Set KEEP_DB=1 in .env to opt out (e.g. for incremental reruns).
    db_path = HARNESS_DIR / "migration.db"
    if os.getenv("KEEP_DB") != "1" and db_path.exists():
        db_path.unlink()
        print(f"[startup] removed {db_path} for a clean run (set KEEP_DB=1 to keep)")

    if os.getenv("SKIP_PREFLIGHT") != "1":
        try:
            preflight()
        except Exception as exc:
            print(f"ERROR: preflight failed: {exc}", file=sys.stderr)
            print("Set SKIP_PREFLIGHT=1 to bypass (not recommended).", file=sys.stderr)
            return 3

    proc = start_orchestrator(source_dir, output_dir, port, model)
    try:
        run_migration(source_dir, repo_id, port)
    finally:
        print("[orchestrator] stopping")
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()

    print(f"\nDone. All artifacts under {output_dir}/:")
    print(f"  - Migrated code:     {output_dir}/<module>/")
    print(f"  - Analysis/reviews:  {output_dir}/analysis/<module>/")
    print(f"  - Discovery:         {output_dir}/discovery/{repo_id}/")
    print(f"  - Infrastructure:    {output_dir}/infrastructure/<module>/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
