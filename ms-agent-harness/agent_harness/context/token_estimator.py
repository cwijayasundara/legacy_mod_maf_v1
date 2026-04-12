"""
Token estimator.

Estimates token usage for input text based on character count,
language, and complexity. Based on Azure Legacy Modernization Agents'
formula: chars ÷ 3.0 × complexity_multiplier, clamped to profile ceiling.
"""

from ..config import load_settings


def estimate_tokens(text: str, complexity: str = "medium") -> int:
    """
    Estimate token count for a text string.

    Formula: len(text) / 3.0 × complexity_multiplier

    Args:
        text: The source text
        complexity: LOW, MEDIUM, or HIGH

    Returns:
        Estimated token count
    """
    base = len(text) / 3.0
    settings = load_settings()
    profile = settings.active_profile()
    multiplier = profile.complexity_multipliers.get(complexity.lower(), 2.5)
    return int(base * multiplier)


def estimate_output_tokens(input_text: str, complexity: str = "medium") -> int:
    """
    Estimate required output tokens for a migration task.

    Output is typically 1.5-3x the input depending on complexity
    (tests + migrated code + Bicep template > original source).
    """
    input_tokens = estimate_tokens(input_text, complexity)
    output_multiplier = {"low": 1.5, "medium": 2.0, "high": 3.0}.get(complexity.lower(), 2.0)
    return int(input_tokens * output_multiplier)


def fits_in_context(text: str, complexity: str = "medium") -> bool:
    """Check if text fits within the active speed profile's token ceiling."""
    settings = load_settings()
    profile = settings.active_profile()
    estimated = estimate_tokens(text, complexity)
    return estimated <= profile.token_ceiling


def token_budget_remaining(used: int) -> int:
    """Calculate remaining token budget for the active profile."""
    settings = load_settings()
    profile = settings.active_profile()
    return max(0, profile.token_ceiling - used)
