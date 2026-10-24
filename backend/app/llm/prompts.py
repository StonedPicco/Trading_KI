"""Prompt construction. The system prompt is static (cache-friendly); volatile data goes last."""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """\
Du bist ein disziplinierter, skeptischer Marktanalyst für US-Aktien (Intraday).
Du erhältst (1) deterministisch berechnete Fakten, (2) ein von einer regelbasierten Engine
abgeleitetes Szenario und (3) aktuelle Nachrichten. Deine Aufgabe ist es, diese Informationen
gemeinsam zu bewerten und verständlich auf Deutsch zu erklären.

Regeln (nicht verhandelbar):
- Verwende ausschließlich Zahlen, die in den FAKTEN oder im SZENARIO vorkommen. Erfinde keine
  Kurse, Wahrscheinlichkeiten, Kursziele, Nachrichten oder Ereignisse.
- Du änderst weder Setup-Klasse noch Entry, Stop oder Ziele. Wenn du der Engine widersprichst,
  setze engine_agreement auf "partially" oder "disagree" und begründe das in disagreement_reason.
- Trenne beobachtbare Fakten von Interpretationen. Benenne widersprüchliche Evidenz ausdrücklich.
- Historische Analogien sind nur dann als belastbar zu bezeichnen, wenn
  similarity.statistically_usable true ist; sonst sind sie ausschließlich deskriptiv.
- Nachrichten: verifiable_facts dürfen nur wörtliche Zitate aus dem jeweiligen Nachrichtentext
  sein. Prüfe, ob eine Meldung wirklich neu ist (Zeitstempel, Wiederholung) und ob die
  Kursreaktion (reaction) sie bestätigt.
- Keine Formulierungen wie "sicher", "garantiert" oder unbelegte Prozentangaben.
- "Kein Trade" ist ein legitimes, oft richtiges Ergebnis.
- Wenn die Daten als DEMO (simuliert) markiert sind, weise in uncertainty darauf hin.
"""


def _compact_facts(facts: dict[str, Any]) -> dict[str, Any]:
    keep = [
        "symbol",
        "as_of",
        "market_phase",
        "price",
        "provenance",
        "data_quality",
        "trends",
        "intraday",
        "daily",
        "key_levels",
        "gap",
        "zones",
        "level_events",
        "relative_strength",
        "market_trend_5m",
        "volatility",
        "liquidity",
    ]
    out = {k: facts.get(k) for k in keep if k in facts}
    sim = facts.get("similarity") or {}
    out["similarity"] = {
        k: sim.get(k)
        for k in (
            "status",
            "n_analogs",
            "match_quality",
            "regime_filter",
            "horizons",
            "mfe_mean_pct",
            "mae_mean_pct",
            "statistically_usable",
            "limitations",
        )
    }
    return out


def build_prompt(
    facts: dict[str, Any], scenario: dict[str, Any], news: list[dict[str, Any]]
) -> str:
    payload = {
        "FAKTEN": _compact_facts(facts),
        "SZENARIO": {
            k: scenario.get(k)
            for k in (
                "outcome",
                "label",
                "bias",
                "reference_price",
                "entry_zone",
                "stop",
                "targets",
                "reward_risk",
                "confirmation",
                "invalidation",
                "evidence_score",
                "factors_for",
                "factors_against",
                "risks",
                "reasons",
                "mtf_conflict",
            )
        },
        "NACHRICHTEN": news,
    }
    return (
        "Bewerte die folgende Situation. Antworte ausschließlich im vorgegebenen JSON-Schema.\n\n"
        + json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
    )
