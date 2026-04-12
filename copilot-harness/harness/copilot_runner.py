"""
Copilot CLI Runner

Wraps GitHub Copilot CLI in autopilot mode for headless execution.
Supports BYOK (Azure OpenAI, OpenAI, Anthropic, Ollama) via environment variables.
"""

import asyncio
import logging
import os
import shutil

import yaml

logger = logging.getLogger("copilot-runner")

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")


class CopilotRunner:
    """Wraps Copilot CLI with BYOK support."""

    def __init__(
        self,
        project_root: str = "",
        provider_type: str = "",
        provider_url: str = "",
        api_key: str = "",
        model: str = "",
        offline: bool = False,
    ):
        self.project_root = project_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.provider_type = provider_type or os.environ.get("COPILOT_PROVIDER_TYPE", "")
        self.provider_url = provider_url or os.environ.get("COPILOT_PROVIDER_BASE_URL", "")
        self.api_key = api_key or os.environ.get("COPILOT_PROVIDER_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
        self.model = model or os.environ.get("COPILOT_MODEL", "")
        self.offline = offline or os.environ.get("COPILOT_OFFLINE", "").lower() == "true"
        self._timeouts = {"python": 3600, "node": 3600, "java": 5400, "csharp": 5400}
        self._max_continues = 20
        self._load_settings()

    def _load_settings(self):
        try:
            if os.path.exists(SETTINGS_PATH):
                with open(SETTINGS_PATH) as f:
                    settings = yaml.safe_load(f) or {}
                copilot = settings.get("copilot", {})
                self._max_continues = copilot.get("max_autopilot_continues", 20)
                self._timeouts.update(copilot.get("language_timeouts", {}))
        except Exception:
            pass

    def is_available(self) -> bool:
        """Check if Copilot CLI is installed."""
        return shutil.which("copilot") is not None

    def _build_env(self) -> dict:
        """Build environment variables for BYOK."""
        env = os.environ.copy()
        if self.provider_type:
            env["COPILOT_PROVIDER_TYPE"] = self.provider_type
        if self.provider_url:
            env["COPILOT_PROVIDER_BASE_URL"] = self.provider_url
        if self.api_key:
            env["COPILOT_PROVIDER_API_KEY"] = self.api_key
            env["OPENAI_API_KEY"] = self.api_key
        if self.model:
            env["COPILOT_MODEL"] = self.model
        if self.offline:
            env["COPILOT_OFFLINE"] = "true"
        return env

    async def run(self, prompt: str, module: str, language: str = "python") -> tuple[bool, str]:
        """
        Run Copilot CLI in autopilot mode.
        Returns (success, output).
        """
        if not self.is_available():
            return False, "ERROR: Copilot CLI not found"

        timeout = self._timeouts.get(language, 3600)
        cmd = [
            "copilot", "--autopilot", "--yolo",
            "--max-autopilot-continues", str(self._max_continues),
            "-p", prompt,
        ]

        logger.info("Running Copilot: module=%s timeout=%ds", module, timeout)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.project_root,
                env=self._build_env(),
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return False, f"TIMEOUT after {timeout}s"

            output = stdout_bytes.decode("utf-8", errors="replace")
            if stderr_bytes:
                output += "\n--- STDERR ---\n" + stderr_bytes.decode("utf-8", errors="replace")

            return process.returncode == 0, output

        except FileNotFoundError:
            return False, "ERROR: copilot not found in PATH"
        except Exception as exc:
            logger.exception("Copilot error for %s", module)
            return False, f"ERROR: {exc}"
