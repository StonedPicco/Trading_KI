"""Deterministic narrative built only from engine output – used without an LLM key and as
fallback when LLM output fails validation."""

from __future__ import annotations

from typing import Any

from app.llm.schemas import AnalystNarrative


def deterministic_narrative(facts: dict[str, Any], scenario: dict[str, Any]) -> AnalystNarrative:
    label = scenario.get("label", "")
    reasons = "; ".join(scenario.get("reasons", []))
    price = scenario.get("reference_price")
    summary = f"{facts.get('symbol')} @ {price:.2f}: {label}. {reasons}." if price else label
    if scenario.get("entry_zone"):
        lo, hi = scenario["entry_zone"]
        targets = ", ".join(f"{t:.2f}" for t in scenario.get("targets", []))
        summary += (
            f" Entry-Zone {lo:.2f}–{hi:.2f}, Stop {scenario['stop']:.2f}, Ziele {targets}, "
            f"CRV {scenario.get('reward_risk')}."
        )
    rs = facts.get("relative_strength", {})
    ctx_parts = []
    for key, name in (("market", "Markt"), ("sector", "Sektor")):
        r = rs.get(key)
        if r and r.get("rs_intraday") is not None:
            ctx_parts.append(f"{name} ({r['benchmark']}): {r['rs_intraday']:+.2f} %-Punkte heute")
    vol = facts.get("volatility") or {}
    if vol.get("regime"):
        ctx_parts.append(f"Volatilitätsregime: {vol['regime']}")
    uncertainty = list((facts.get("similarity") or {}).get("limitations", []))
    uncertainty += list((facts.get("data_quality") or {}).get("info", []))
    if (facts.get("provenance") or {}).get("data_kind") == "demo":
        uncertainty.insert(0, "DEMO-DATEN: simulierte Kurse, keine reale Marktsituation.")
    uncertainty.append("Automatisch generierte Begründung ohne Sprachmodell (deterministisch).")
    return AnalystNarrative(
        summary=summary,
        bull_case=[
            f"{f['observation']} → {f['interpretation']}" for f in scenario.get("factors_for", [])
        ],
        bear_case=[
            f"{f['observation']} → {f['interpretation']}"
            for f in scenario.get("factors_against", [])
        ],
        key_risks=list(scenario.get("risks", [])),
        market_context="; ".join(ctx_parts) or "Kein Markt-/Sektorvergleich verfügbar.",
        news_assessments=[],
        engine_agreement="agree",
        disagreement_reason="",
        uncertainty=uncertainty,
    )
