"""Tests for agents/config.py — YAML config loading, no LLM calls."""

from agent_harness.config import load_settings, Settings, SpeedProfile


class TestLoadSettings:
    def test_load_settings_returns_settings(self):
        settings = load_settings()
        assert isinstance(settings, Settings)

    def test_has_models(self):
        settings = load_settings()
        assert isinstance(settings.models, dict)
        assert len(settings.models) > 0

    def test_has_chunking_config(self):
        settings = load_settings()
        assert settings.chunking.max_lines == 3000
        assert settings.chunking.max_chars == 150000
        assert settings.chunking.overlap_lines == 50

    def test_has_quality_config(self):
        settings = load_settings()
        assert settings.quality.coverage_floor == 80
        assert settings.quality.max_self_healing_attempts == 3


class TestSpeedProfiles:
    def test_four_profiles_exist(self):
        settings = load_settings()
        assert len(settings.speed_profiles) == 4
        expected = {"turbo", "fast", "balanced", "thorough"}
        assert set(settings.speed_profiles.keys()) == expected

    def test_profiles_have_expected_fields(self):
        settings = load_settings()
        for name, profile in settings.speed_profiles.items():
            assert isinstance(profile, SpeedProfile)
            assert profile.name == name
            assert profile.token_ceiling > 0
            assert profile.reasoning_effort in ("low", "mixed", "medium", "high")
            assert profile.max_parallel_chunks > 0
            assert "low" in profile.complexity_multipliers
            assert "medium" in profile.complexity_multipliers
            assert "high" in profile.complexity_multipliers

    def test_default_profile_is_balanced(self):
        settings = load_settings()
        assert settings.default_profile == "balanced"
        active = settings.active_profile()
        assert active.name == "balanced"

    def test_thorough_has_highest_multipliers(self):
        settings = load_settings()
        thorough = settings.speed_profiles["thorough"]
        turbo = settings.speed_profiles["turbo"]
        for key in ("low", "medium", "high"):
            assert thorough.complexity_multipliers[key] >= turbo.complexity_multipliers[key]


class TestModelRouting:
    def test_analyzer_model(self):
        settings = load_settings()
        assert settings.model_for_role("analyzer") == "gpt-4o"

    def test_coder_model(self):
        settings = load_settings()
        assert settings.model_for_role("coder") == "gpt-4o-mini"

    def test_tester_model(self):
        settings = load_settings()
        assert settings.model_for_role("tester") == "gpt-4o-mini"

    def test_reviewer_model(self):
        settings = load_settings()
        assert settings.model_for_role("reviewer") == "gpt-4o"

    def test_unknown_role_falls_back_to_default(self):
        settings = load_settings()
        assert settings.model_for_role("nonexistent") == settings.default_model
