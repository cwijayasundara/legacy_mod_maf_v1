"""
Agent base — factory for creating Microsoft Agent Framework agents.

Uses FoundryChatClient for Azure OpenAI and the Agent class
from agent-framework with @tool-decorated functions.
"""

import asyncio
import logging
import os
from pathlib import Path

# Load .env before any SDK imports (they may read OPENAI_API_KEY at import time)
for _env in [Path(__file__).parent.parent / ".env", Path(__file__).parent.parent.parent / ".env"]:
    if _env.exists():
        for _line in _env.read_text().splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

from agent_framework import Agent, tool
from agent_framework_foundry import FoundryChatClient

from .config import Settings, load_settings

logger = logging.getLogger("agents.base")

PROMPTS_DIR = Path(__file__).parent / "prompts"
DISCOVERY_PROMPTS_DIR = Path(__file__).parent / "discovery" / "prompts"

_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def create_chat_client(model: str | None = None):
    """Create a chat client — FoundryChatClient for Azure, OpenAIChatClient for local dev."""
    settings = get_settings()
    model = model or settings.default_model
    endpoint = settings.foundry_endpoint

    if endpoint:
        from azure.identity import DefaultAzureCredential
        return FoundryChatClient(
            project_endpoint=endpoint,
            model=model,
            credential=DefaultAzureCredential(),
        )
    else:
        from agent_framework_openai import OpenAIChatClient
        return OpenAIChatClient(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            model=model,
        )


def load_prompt(role: str,
                repo_root: str | Path | None = None,
                module_path: str | Path | None = None) -> str:
    """Load system prompt from prompts/ directory, falling back to discovery/prompts/."""
    for candidate in (PROMPTS_DIR / f"{role}.md", DISCOVERY_PROMPTS_DIR / f"{role}.md"):
        if candidate.exists():
            prompt = candidate.read_text()
            break
    else:
        logger.warning("Prompt file not found for role %s", role)
        prompt = f"You are a migration {role} agent."

    # Inject quality principles into every agent's prompt
    quality_path = PROMPTS_DIR / "quality-principles.md"
    if quality_path.exists():
        prompt += "\n\n" + quality_path.read_text()

    # Inject repo-level AGENTS.md
    if repo_root:
        agents_md = Path(repo_root) / "AGENTS.md"
        if agents_md.is_file():
            try:
                prompt += (
                    f"\n\n## Repo context (AGENTS.md)\n{agents_md.read_text(encoding='utf-8')}"
                )
            except OSError as exc:
                logger.warning("Could not read %s: %s", agents_md, exc)

    # Inject module-level AGENTS.md (overrides repo-level by appearing after).
    if module_path:
        mod_md = Path(module_path) / "AGENTS.md"
        if mod_md.is_file():
            try:
                prompt += (
                    f"\n\n## Module context (AGENTS.md)\n{mod_md.read_text(encoding='utf-8')}"
                )
            except OSError as exc:
                logger.warning("Could not read %s: %s", mod_md, exc)

    return prompt


def create_agent(role: str, tools: list | None = None,
                 repo_root: str | Path | None = None,
                 module_path: str | Path | None = None) -> Agent:
    """
    Create an agent for a specific role.

    Args:
        role: One of 'analyzer', 'coder', 'tester', 'reviewer', discovery roles, etc.
        tools: List of @tool-decorated functions
        repo_root: Optional repo root; when set, <repo_root>/AGENTS.md is injected.
        module_path: Optional module dir; when set, <module_path>/AGENTS.md is injected.
    """
    settings = get_settings()
    model = settings.model_for_role(role)
    prompt = load_prompt(role, repo_root=repo_root, module_path=module_path)

    # Inject learned rules
    learned_rules = _load_learned_rules()
    if learned_rules:
        prompt += f"\n\n## Learned Rules (inject into all work)\n{learned_rules}"

    # Inject program.md steering
    program = _load_program()
    if program:
        prompt += f"\n\n## Human Steering (from program.md)\n{program}"

    client = create_chat_client(model)

    agent = Agent(
        client=client,
        name=f"migration-{role}",
        instructions=prompt,
        tools=tools or [],
    )

    logger.info("Created agent: migration-%s (model: %s, tools: %d)", role, model, len(tools or []))
    return agent


def _load_learned_rules() -> str:
    rules_path = Path(__file__).parent.parent / "config" / "state" / "learned-rules.md"
    if rules_path.exists():
        content = rules_path.read_text()
        if "## Rule" in content:
            return content
    return ""


def _load_program() -> str:
    program_path = Path(__file__).parent.parent / "config" / "program.md"
    if program_path.exists():
        return program_path.read_text()
    return ""


async def run_with_retry(agent: Agent, message: str, max_retries: int = 3) -> str:
    """Run an agent with exponential backoff on rate limit errors."""
    for attempt in range(max_retries):
        try:
            result = await agent.run(message)
            return result.text
        except Exception as e:
            error_str = str(e).lower()

            if "rate_limit" in error_str or "429" in error_str:
                wait = (2 ** attempt) + (asyncio.get_event_loop().time() % 1)
                logger.warning("Rate limited (attempt %d/%d), waiting %.1fs", attempt + 1, max_retries, wait)
                await asyncio.sleep(wait)
                continue

            if "context_length" in error_str or "token" in error_str:
                logger.warning("Token limit hit — retrying with truncated context")
                message = message[:int(len(message) * 0.7)]
                continue

            logger.error("Agent error (attempt %d/%d): %s", attempt + 1, max_retries, e)
            if attempt == max_retries - 1:
                raise

    raise RuntimeError(f"Agent failed after {max_retries} retries")
