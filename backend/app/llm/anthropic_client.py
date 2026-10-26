"""Anthropic Claude implementation of LLMClient using structured outputs (JSON schema)."""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from app.core.errors import AppError
from app.llm.base import LLMResult, estimate_cost
from app.llm.schemas import AnalystNarrative, strict_json_schema

log = logging.getLogger(__name__)


class LLMOutputError(AppError):
    pass


class AnthropicLLMClient:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        effort: str = "medium",
        server_side_fallback: bool = True,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self.server_side_fallback = server_side_fallback
        self.client = client or anthropic.AsyncAnthropic(api_key=api_key, max_retries=3)
        self.schema = strict_json_schema(AnalystNarrative)

    async def analyze(self, system: str, prompt: str) -> LLMResult:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16000,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": self.schema},
            },
        }
        try:
            if self.server_side_fallback:
                # On a policy decline the API re-runs the request on a fallback model.
                resp = await self.client.beta.messages.create(
                    **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
                )
            else:
                resp = await self.client.messages.create(**kwargs)
        except anthropic.RateLimitError as exc:
            raise LLMOutputError(f"LLM rate limited: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMOutputError(f"LLM API error {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMOutputError("LLM connection error") from exc

        if resp.stop_reason == "refusal":
            raise LLMOutputError("LLM declined the request (refusal)")
        if resp.stop_reason == "max_tokens":
            raise LLMOutputError("LLM output truncated (max_tokens)")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            raise LLMOutputError("LLM returned no text block")
        try:
            narrative = AnalystNarrative.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMOutputError(f"LLM output failed schema validation: {exc}") from exc
        served_by = getattr(resp, "model", self.model) or self.model
        usage = resp.usage
        return LLMResult(
            narrative=narrative,
            model=served_by,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=estimate_cost(served_by, usage.input_tokens, usage.output_tokens),
        )
