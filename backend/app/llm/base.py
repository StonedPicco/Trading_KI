"""LLM abstraction. Implementations: AnthropicLLMClient, NullLLMClient (deterministic)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.llm.schemas import AnalystNarrative


@dataclass
class LLMResult:
    narrative: AnalystNarrative
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    generated_by: str = "llm"  # llm | deterministic
    notes: list[str] = field(default_factory=list)


class LLMClient(Protocol):
    name: str
    model: str

    async def analyze(self, system: str, prompt: str) -> LLMResult: ...


# USD per million tokens (input, output). Source: Anthropic pricing as cached in the SDK
# reference on 2026-10-06 – verify on the official pricing page before relying on it.
PRICING: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = PRICING.get(model, (10.0, 50.0))  # unknown model: assume the most expensive tier
    return round(input_tokens / 1e6 * inp + output_tokens / 1e6 * out, 6)
