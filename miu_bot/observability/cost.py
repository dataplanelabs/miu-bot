"""Token-to-cost estimation for LLM usage tracking."""

from __future__ import annotations

# Approximate pricing per 1M tokens (input, output) as of 2025/2026
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus": (15.0, 75.0),
    "claude-sonnet": (3.0, 15.0),
    "claude-haiku": (0.25, 1.25),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "deepseek": (0.14, 0.28),
    "gemini": (0.15, 0.60),
    "qwen": (0.14, 0.28),
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost for a single LLM call."""
    model_lower = model.lower()
    for key, (input_price, output_price) in MODEL_PRICING.items():
        if key in model_lower:
            return (
                (prompt_tokens / 1_000_000) * input_price
                + (completion_tokens / 1_000_000) * output_price
            )
    return 0.0
