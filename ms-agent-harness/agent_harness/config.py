"""
Agent configuration loader.

Reads settings.yaml and provides typed access to model routing,
speed profiles, rate limits, and quality thresholds.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).parent.parent / "config"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"


@dataclass
class SpeedProfile:
    """Controls token budgets and reasoning per file complexity."""
    name: str
    description: str
    token_ceiling: int
    reasoning_effort: str
    max_parallel_chunks: int
    complexity_multipliers: dict[str, float]

    def token_budget(self, complexity: str) -> int:
        multiplier = self.complexity_multipliers.get(complexity, 2.5)
        return int(self.token_ceiling * multiplier / 3.5)  # normalize


@dataclass
class RateLimits:
    tokens_per_minute: int = 210000
    requests_per_minute: int = 60
    sliding_window_seconds: int = 60


@dataclass
class ChunkingConfig:
    max_lines: int = 3000
    max_chars: int = 150000
    overlap_lines: int = 50


@dataclass
class QualityConfig:
    coverage_floor: int = 80
    reviewer_confidence_threshold: int = 70
    max_self_healing_attempts: int = 3
    max_iterations_per_module: int = 10


@dataclass
class TimeoutConfig:
    per_call_seconds: int = 120
    per_stage_seconds: dict[str, int] = field(default_factory=lambda: {
        "analyzer": 600, "coder": 900, "tester": 600,
        "reviewer": 300, "security": 300,
        "scanner": 300, "grapher": 600, "brd": 900,
        "architect": 900, "stories": 600,
    })


@dataclass
class CostConfig:
    per_run_token_cap: int | None = None


@dataclass
class Settings:
    """Root configuration."""
    foundry_endpoint: str = ""
    default_model: str = "gpt-4o"
    models: dict[str, str] = field(default_factory=dict)
    speed_profiles: dict[str, SpeedProfile] = field(default_factory=dict)
    default_profile: str = "balanced"
    rate_limits: RateLimits = field(default_factory=RateLimits)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    cost: CostConfig = field(default_factory=CostConfig)

    def model_for_role(self, role: str) -> str:
        return self.models.get(role, self.default_model)

    def active_profile(self) -> SpeedProfile:
        return self.speed_profiles.get(self.default_profile, list(self.speed_profiles.values())[0])

    def timeout_for(self, role: str) -> int:
        return self.timeouts.per_stage_seconds.get(role, 600)


def load_settings() -> Settings:
    """Load settings from YAML + environment variable overrides."""
    if not SETTINGS_PATH.exists():
        return Settings()

    raw = yaml.safe_load(SETTINGS_PATH.read_text())

    # Resolve endpoint from environment
    endpoint_env = raw.get("azure_openai", {}).get("endpoint_env", "FOUNDRY_PROJECT_ENDPOINT")
    model_env = raw.get("azure_openai", {}).get("model_env", "FOUNDRY_MODEL")

    # Parse speed profiles
    profiles = {}
    for name, data in raw.get("speed_profiles", {}).items():
        profiles[name] = SpeedProfile(
            name=name,
            description=data.get("description", ""),
            token_ceiling=data.get("token_ceiling", 100000),
            reasoning_effort=data.get("reasoning_effort", "medium"),
            max_parallel_chunks=data.get("max_parallel_chunks", 3),
            complexity_multipliers=data.get("complexity_multipliers", {"low": 1.5, "medium": 2.5, "high": 3.5}),
        )

    rl = raw.get("rate_limits", {})
    ch = raw.get("chunking", {})
    qa = raw.get("quality", {})

    timeouts_raw = raw.get("timeouts", {}) or {}
    if "per_stage_seconds" in timeouts_raw and timeouts_raw.get("per_stage_seconds"):
        per_stage = dict(timeouts_raw["per_stage_seconds"])
    else:
        per_stage = TimeoutConfig().per_stage_seconds
    timeouts_cfg = TimeoutConfig(
        per_call_seconds=int(timeouts_raw.get("per_call_seconds", 120)),
        per_stage_seconds=per_stage,
    )
    cost_raw = raw.get("cost", {}) or {}
    cap_raw = cost_raw.get("per_run_token_cap")
    cost_cfg = CostConfig(per_run_token_cap=int(cap_raw) if cap_raw is not None else None)

    return Settings(
        foundry_endpoint=os.environ.get(endpoint_env, ""),
        default_model=os.environ.get(model_env, "gpt-4o"),
        models=raw.get("models", {}),
        speed_profiles=profiles,
        default_profile=raw.get("default_profile", "balanced"),
        rate_limits=RateLimits(
            tokens_per_minute=rl.get("tokens_per_minute", 210000),
            requests_per_minute=rl.get("requests_per_minute", 60),
            sliding_window_seconds=rl.get("sliding_window_seconds", 60),
        ),
        chunking=ChunkingConfig(
            max_lines=ch.get("max_lines", 3000),
            max_chars=ch.get("max_chars", 150000),
            overlap_lines=ch.get("overlap_lines", 50),
        ),
        quality=QualityConfig(
            coverage_floor=qa.get("coverage_floor", 80),
            reviewer_confidence_threshold=qa.get("reviewer_confidence_threshold", 70),
            max_self_healing_attempts=qa.get("max_self_healing_attempts", 3),
            max_iterations_per_module=qa.get("max_iterations_per_module", 10),
        ),
        timeouts=timeouts_cfg,
        cost=cost_cfg,
    )
