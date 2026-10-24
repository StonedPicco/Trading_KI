from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.llm.anthropic_client import AnthropicLLMClient, LLMOutputError
from app.llm.base import estimate_cost
from app.llm.null_client import deterministic_narrative
from app.llm.schemas import AnalystNarrative, NewsAssessment, strict_json_schema
from app.llm.validator import validate_narrative

FACTS = {
    "symbol": "TEST",
    "price": 187.42,
    "key_levels": {"prev_day_high": 189.5},
    "provenance": {"data_kind": "live"},
}
SCENARIO = {
    "label": "Bullisches Setup",
    "reference_price": 187.42,
    "entry_zone": [186.9, 187.5],
    "stop": 185.8,
    "targets": [189.5, 191.2],
    "reward_risk": 2.1,
    "reasons": ["x"],
    "factors_for": [],
    "factors_against": [],
    "risks": [],
}
NEWS = [
    {
        "id": "alpaca:1",
        "headline": "Acme raises full-year guidance",
        "summary": "Acme now expects revenue of $12 billion.",
        "content": None,
    }
]


def narrative(**kw: Any) -> AnalystNarrative:
    base: dict[str, Any] = dict(
        summary="Kurs 187.42 nahe Widerstand 189.5; Stop 185.8.",
        bull_case=["Trend intakt"],
        bear_case=["Widerstand"],
        key_risks=["Volatilität"],
        market_context="neutral",
        news_assessments=[],
        engine_agreement="agree",
        disagreement_reason="",
        uncertainty=[],
    )
    base.update(kw)
    return AnalystNarrative(**base)


def test_strict_schema_forbids_additional_properties_everywhere() -> None:
    schema = strict_json_schema(AnalystNarrative)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            assert "$ref" not in node
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)


def test_validator_accepts_grounded_numbers() -> None:
    _, report = validate_narrative(narrative(), FACTS, SCENARIO, NEWS)
    assert report.ok, report.errors


def test_validator_rejects_hallucinated_price() -> None:
    _, report = validate_narrative(
        narrative(summary="Kursziel 250.00 sehr wahrscheinlich."), FACTS, SCENARIO, NEWS
    )
    assert not report.ok
    assert any("250" in e for e in report.errors)


def test_validator_rejects_certainty_language() -> None:
    _, report = validate_narrative(
        narrative(summary="Ein garantierter Gewinn."), FACTS, SCENARIO, NEWS
    )
    assert not report.ok


def test_validator_strips_non_verbatim_news_facts_and_unknown_ids() -> None:
    good = NewsAssessment(
        news_id="alpaca:1",
        category="guidance",
        relevance="high",
        direction="bullish",
        is_new_information=True,
        verifiable_facts=["expects revenue of $12 billion", "CEO resigned"],
        reasoning="Prognose angehoben",
    )
    bad = good.model_copy(update={"news_id": "alpaca:999"})
    cleaned, report = validate_narrative(
        narrative(news_assessments=[good, bad]), FACTS, SCENARIO, NEWS
    )
    assert cleaned.news_assessments[0].verifiable_facts == ["expects revenue of $12 billion"]
    assert any("alpaca:999" in e for e in report.errors)


def test_deterministic_narrative_flags_demo_data() -> None:
    n = deterministic_narrative({**FACTS, "provenance": {"data_kind": "demo"}}, SCENARIO)
    assert n.uncertainty[0].startswith("DEMO-DATEN")
    _, report = validate_narrative(n, FACTS, SCENARIO, [])
    assert report.ok, report.errors


class _FakeMessages:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


def _fake_client(text: str, stop_reason: str = "end_turn") -> tuple[Any, _FakeMessages]:
    resp = SimpleNamespace(
        stop_reason=stop_reason,
        model="claude-opus-5-5",
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=6000, output_tokens=1500),
    )
    msgs = _FakeMessages(resp)
    client = SimpleNamespace(messages=msgs, beta=SimpleNamespace(messages=msgs))
    return client, msgs


async def test_anthropic_client_parses_structured_output_and_costs() -> None:
    client, msgs = _fake_client(json.dumps(narrative().model_dump()))
    llm = AnthropicLLMClient("k", "claude-opus-5-5", client=client)  # type: ignore[arg-type]
    result = await llm.analyze("system", "prompt")
    assert result.narrative.summary.startswith("Kurs")
    assert result.cost_usd == pytest.approx(6000 * 4 / 1e6 + 1500 * 20 / 1e6)
    call = msgs.calls[0]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default"
    assert "temperature" not in call


async def test_anthropic_client_refusal_raises() -> None:
    client, _ = _fake_client("", stop_reason="refusal")
    llm = AnthropicLLMClient("k", "claude-opus-5-5", client=client)  # type: ignore[arg-type]
    with pytest.raises(LLMOutputError):
        await llm.analyze("s", "p")


async def test_anthropic_client_invalid_json_raises() -> None:
    client, _ = _fake_client('{"summary": 1}')
    llm = AnthropicLLMClient("k", "claude-opus-5-5", client=client)  # type: ignore[arg-type]
    with pytest.raises(LLMOutputError):
        await llm.analyze("s", "p")


def test_unknown_model_cost_is_conservative() -> None:
    assert estimate_cost("unknown-model", 1_000_000, 0) == 10.0
