"""Tests for agents/context/token_estimator.py — token math, no LLM calls.

We mock load_settings to supply controlled speed profiles.
"""

from unittest.mock import patch

from agent_harness.config import Settings, SpeedProfile
from agent_harness.context.token_estimator import (
    estimate_tokens,
    fits_in_context,
)


def _mock_settings():
    return Settings(
        speed_profiles={
            "balanced": SpeedProfile(
                name="balanced",
                description="test",
                token_ceiling=100000,
                reasoning_effort="medium",
                max_parallel_chunks=3,
                complexity_multipliers={"low": 1.5, "medium": 2.5, "high": 3.5},
            ),
        },
        default_profile="balanced",
    )


class TestEstimateBasic:
    @patch("agents.context.token_estimator.load_settings", return_value=_mock_settings())
    def test_estimate_basic(self, mock_settings):
        """300 chars / 3.0 = 100 base tokens, then multiplied by complexity."""
        text = "x" * 300
        result = estimate_tokens(text, "low")
        # 300 / 3.0 * 1.5 = 150
        assert result == 150

    @patch("agents.context.token_estimator.load_settings", return_value=_mock_settings())
    def test_estimate_medium(self, mock_settings):
        text = "x" * 300
        result = estimate_tokens(text, "medium")
        # 300 / 3.0 * 2.5 = 250
        assert result == 250


class TestComplexityMultiplier:
    @patch("agents.context.token_estimator.load_settings", return_value=_mock_settings())
    def test_high_gt_medium_gt_low(self, mock_settings):
        text = "x" * 600
        low = estimate_tokens(text, "low")
        med = estimate_tokens(text, "medium")
        high = estimate_tokens(text, "high")
        assert high > med > low

    @patch("agents.context.token_estimator.load_settings", return_value=_mock_settings())
    def test_exact_multiplier_values(self, mock_settings):
        text = "x" * 900  # 300 base tokens
        low = estimate_tokens(text, "low")
        med = estimate_tokens(text, "medium")
        high = estimate_tokens(text, "high")
        assert low == 450    # 300 * 1.5
        assert med == 750    # 300 * 2.5
        assert high == 1050  # 300 * 3.5


class TestFitsInContext:
    @patch("agents.context.token_estimator.load_settings", return_value=_mock_settings())
    def test_short_text_fits(self, mock_settings):
        assert fits_in_context("short text", "low") is True

    @patch("agents.context.token_estimator.load_settings", return_value=_mock_settings())
    def test_very_long_text_does_not_fit(self, mock_settings):
        # 100000 token ceiling; need chars * multiplier / 3 > 100000
        # With high multiplier 3.5: chars > 100000 * 3 / 3.5 = ~85714
        huge = "x" * 200000
        assert fits_in_context(huge, "high") is False

    @patch("agents.context.token_estimator.load_settings", return_value=_mock_settings())
    def test_boundary(self, mock_settings):
        # Exactly at ceiling: 100000 tokens with medium multiplier
        # 100000 = chars / 3.0 * 2.5  =>  chars = 100000 * 3.0 / 2.5 = 120000
        text = "x" * 120000
        assert fits_in_context(text, "medium") is True
        # One more char should still fit (int rounding)
        text_over = "x" * 120001
        assert fits_in_context(text_over, "medium") is True  # rounds to 100000
