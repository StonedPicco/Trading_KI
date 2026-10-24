"""Structured LLM output schemas + conversion to a strict JSON schema for structured outputs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class NewsAssessment(BaseModel):
    news_id: str = Field(description="ID exactly as given in the input")
    category: Literal[
        "earnings",
        "guidance",
        "regulatory",
        "macro",
        "central_bank",
        "corporate_action",
        "product",
        "legal",
        "analyst",
        "sector",
        "other",
    ]
    relevance: Literal["high", "medium", "low"]
    direction: Literal["bullish", "bearish", "neutral", "unclear"]
    is_new_information: bool = Field(description="false if it repeats already known information")
    verifiable_facts: list[str] = Field(
        description="Verbatim quotes from the news text only; empty if none"
    )
    reasoning: str


class AnalystNarrative(BaseModel):
    summary: str = Field(description="3-5 sentences, German, overall assessment")
    bull_case: list[str]
    bear_case: list[str]
    key_risks: list[str]
    market_context: str
    news_assessments: list[NewsAssessment]
    engine_agreement: Literal["agree", "partially", "disagree"]
    disagreement_reason: str = Field(description="empty string if engine_agreement is agree")
    uncertainty: list[str]


_ALLOWED_KEYS = {
    "type",
    "properties",
    "required",
    "items",
    "enum",
    "description",
    "additionalProperties",
    "anyOf",
}


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Inline $refs, require every property, forbid extra keys (structured-output friendly)."""
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            out = {k: walk(v) for k, v in node.items() if k in _ALLOWED_KEYS}
            if "const" in node:
                out["enum"] = [node["const"]]
            if out.get("type") == "object":
                out["additionalProperties"] = False
                out["required"] = list(out.get("properties", {}).keys())
            return out
        if isinstance(node, list):
            return [walk(n) for n in node]
        return node

    return walk(raw)
