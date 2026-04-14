import pytest
import yaml


def test_timeout_config_defaults():
    from agent_harness.config import TimeoutConfig
    t = TimeoutConfig()
    assert t.per_call_seconds == 120
    assert t.per_stage_seconds["analyzer"] == 600
    assert t.per_stage_seconds["coder"] == 900
    assert t.per_stage_seconds["scanner"] == 300


def test_cost_config_defaults():
    from agent_harness.config import CostConfig
    c = CostConfig()
    assert c.per_run_token_cap is None


def test_settings_timeout_for_known_role():
    from agent_harness.config import Settings, TimeoutConfig
    s = Settings(timeouts=TimeoutConfig(
        per_call_seconds=30,
        per_stage_seconds={"analyzer": 42, "coder": 55},
    ))
    assert s.timeout_for("analyzer") == 42
    assert s.timeout_for("coder") == 55


def test_settings_timeout_for_unknown_role_falls_back_to_600():
    from agent_harness.config import Settings
    assert Settings().timeout_for("novel-role") == 600


def test_load_settings_reads_yaml_blocks(tmp_path, monkeypatch):
    yaml_text = yaml.safe_dump({
        "timeouts": {
            "per_call_seconds": 45,
            "per_stage_seconds": {"analyzer": 111, "stories": 222},
        },
        "cost": {"per_run_token_cap": 500_000},
    })
    p = tmp_path / "settings.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr("agent_harness.config.SETTINGS_PATH", p)
    from agent_harness.config import load_settings
    s = load_settings()
    assert s.timeouts.per_call_seconds == 45
    assert s.timeouts.per_stage_seconds["analyzer"] == 111
    assert s.timeouts.per_stage_seconds["stories"] == 222
    assert s.timeout_for("stories") == 222
    assert s.timeout_for("reviewer") == 600
    assert s.cost.per_run_token_cap == 500_000


def test_load_settings_missing_blocks_uses_defaults(tmp_path, monkeypatch):
    p = tmp_path / "settings.yaml"
    p.write_text(yaml.safe_dump({"default_model": "gpt-5.4-mini"}), encoding="utf-8")
    monkeypatch.setattr("agent_harness.config.SETTINGS_PATH", p)
    from agent_harness.config import load_settings
    s = load_settings()
    assert s.timeouts.per_call_seconds == 120
    assert s.cost.per_run_token_cap is None
