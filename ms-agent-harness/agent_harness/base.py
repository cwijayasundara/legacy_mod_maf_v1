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


def load_prompt(role: str) -> str:
    """Load system prompt from prompts/ directory."""
    prompt_file = PROMPTS_DIR / f"{role}.md"
    if prompt_file.exists():
        prompt = prompt_file.read_text()
    else:
        logger.warning("Prompt file not found: %s", prompt_file)
        prompt = f"You are a migration {role} agent."

    # Inject quality principles into every agent's prompt
    quality_path = PROMPTS_DIR / "quality-principles.md"
    if quality_path.exists():
        prompt += "\n\n" + quality_path.read_text()

    return prompt


def create_agent(role: str, tools: list | None = None) -> Agent:
    """
    Create an agent for a specific role.

    Args:
        role: One of 'analyzer', 'coder', 'tester', 'reviewer'
        tools: List of @tool-decorated functions
    """
    settings = get_settings()
    model = settings.model_for_role(role)
    prompt = load_prompt(role)

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
