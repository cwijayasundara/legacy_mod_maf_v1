"""Run the discovery pipeline against the synthetic fixture with real LLM calls."""
import asyncio
from pathlib import Path

from agent_harness.discovery.workflow import run_discovery, run_planning
from agent_harness.persistence.repository import MigrationRepository

FIXTURE = Path(__file__).parent / "tests" / "fixtures" / "synthetic_repo"


async def main():
    repo = MigrationRepository()
    repo.initialize()
    print(f"Running discovery against {FIXTURE}")
    result = await run_discovery(repo_id="synth", repo_path=str(FIXTURE), repo=repo)
    print("discover:", result["status"], result["stages"])
    backlog = await run_planning(repo_id="synth", repo=repo)
    print(f"backlog: {len(backlog.items)} items across waves "
          f"{sorted({i.wave for i in backlog.items})}")
    for item in backlog.items:
        print(f"  wave={item.wave}  module={item.module}  title={item.title}")


if __name__ == "__main__":
    asyncio.run(main())
