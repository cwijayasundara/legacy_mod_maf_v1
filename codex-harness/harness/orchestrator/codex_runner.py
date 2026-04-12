"""
Codex CLI Runner

Wraps the Codex CLI for execution within the orchestrator.
Handles environment setup, timeout, output capture, and error handling.

For Azure deployment, the Codex CLI runs inside the Container App
against the Azure OpenAI endpoint (not openai.com).
"""

import asyncio
import logging
import os
import shutil

logger = logging.getLogger("codex-runner")

# Default timeout per module migration (seconds)
DEFAULT_TIMEOUT = 3600  # 1 hour
# Timeout by language (some languages take longer)
LANGUAGE_TIMEOUTS = {
    "java": 5400,    # 1.5 hours - Maven builds are slow
    "csharp": 5400,  # 1.5 hours - NuGet restore + build
    "python": 3600,  # 1 hour
    "node": 3600,    # 1 hour
}


class CodexRunner:
    """Wraps Codex CLI execution."""

    def __init__(self, model: str, api_base: str, api_key: str, project_root: str):
        self.model = model
        self.api_base = api_base
        self.api_key = api_key
        self.project_root = project_root

    def is_available(self) -> bool:
        """Check if Codex CLI is installed and accessible."""
        return shutil.which("codex") is not None

    def _build_env(self) -> dict:
        """Build environment variables for Codex subprocess."""
        env = os.environ.copy()

        # Set API key
        if self.api_key:
            env["OPENAI_API_KEY"] = self.api_key

        # If using Azure OpenAI endpoint, configure for Azure
        if self.api_base:
            env["CODEX_API_BASE"] = self.api_base
            env["OPENAI_BASE_URL"] = self.api_base

        return env

    async def run(
        self,
        prompt: str,
        module: str,
        language: str = "python",
    ) -> tuple[bool, str]:
        """
        Run Codex CLI with the given prompt.

        Uses asyncio.create_subprocess_exec for non-blocking execution.
        The Codex CLI runs in --approval-mode full-auto (no user interaction).

        Args:
            prompt: The migration task prompt
            module: Module name (for logging and timeout selection)
            language: Source language (affects timeout)

        Returns:
            Tuple of (success: bool, output: str)
        """
        if not self.is_available():
            msg = "Codex CLI not found. Install: npm install -g @openai/codex"
            logger.error(msg)
            return False, f"ERROR: {msg}"

        timeout = LANGUAGE_TIMEOUTS.get(language, DEFAULT_TIMEOUT)

        # Build command as list (no shell injection risk)
        # Codex CLI uses: codex exec --full-auto -m MODEL "PROMPT"
        cmd = [
            "codex", "exec",
            "--full-auto",
            "-m", self.model,
            prompt,
        ]

        logger.info(
            "Running Codex: module=%s model=%s timeout=%ds",
            module, self.model, timeout,
        )

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.project_root,
                env=self._build_env(),
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.error(
                    "Codex timed out for module %s after %ds", module, timeout
                )
                return False, f"TIMEOUT after {timeout}s"

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            output = stdout
            if stderr:
                output += "\n--- STDERR ---\n" + stderr

            success = process.returncode == 0
            if success:
                logger.info("Codex completed for module %s", module)
            else:
                logger.warning(
                    "Codex exited %d for module %s", process.returncode, module
                )

            return success, output

        except FileNotFoundError:
            logger.error("codex binary not found in PATH")
            return False, "ERROR: codex command not found in PATH"
        except Exception as exc:
            logger.exception("Codex error for module %s", module)
            return False, f"ERROR: {exc}"
