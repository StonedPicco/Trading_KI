"""Post-validation of LLM output against the facts it was given.

Structured outputs guarantee shape; this module checks *content*:
* every price-like number in the text must appear in the input (facts/scenario/news)
* news_ids must reference given news; quoted facts must be verbatim substrings of the news text
* forbidden certainty phrases are rejected
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.llm.schemas import AnalystNarrative

_NUM = re.compile(r"(?<![\w.])[-+]?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?")
_FORBIDDEN = [
    re.compile(p, re.I)
    for p in (r"garantiert", r"sicherer? (trade|gewinn)", r"risikolos", r"100\s?% sicher")
]
_SMALL_INT_OK = {1, 2, 3, 4, 5, 9, 10, 12, 14, 15, 20, 26, 30, 50, 60, 200, 252}


@dataclass
class ValidationReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _collect_numbers(obj: Any, out: set[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, int | float):
        v = float(obj)
        out.update({v, round(v, 2), round(v, 1), round(v), round(v * 100, 1), round(v * 100)})
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_numbers(v, out)
    elif isinstance(obj, list | tuple):
        for v in obj:
            _collect_numbers(v, out)
    elif isinstance(obj, str):
        for m in _NUM.findall(obj):
            parsed = _parse_number(m)
            if parsed is not None:
                out.add(parsed)


def _parse_number(token: str) -> float | None:
    t = token.strip()
    if "," in t and "." in t:
        t = (
            t.replace(",", "")
            if t.rfind(".") > t.rfind(",")
            else t.replace(".", "").replace(",", ".")
        )
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _supported(value: float, allowed: set[float]) -> bool:
    a = abs(value)
    if a in _SMALL_INT_OK or (a < 10 and a == int(a)):
        return True
    for x in allowed:
        if abs(x - a) <= max(0.006 * max(abs(x), 1e-9), 0.051 if a < 10 else 0.011):
            return True
        if abs(abs(x) - a) <= max(0.006 * abs(x), 0.011):
            return True
    return False


def _texts(n: AnalystNarrative) -> list[str]:
    parts = [
        n.summary,
        n.market_context,
        n.disagreement_reason,
        *n.bull_case,
        *n.bear_case,
        *n.key_risks,
        *n.uncertainty,
    ]
    parts += [a.reasoning for a in n.news_assessments]
    return [p for p in parts if p]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def validate_narrative(
    narrative: AnalystNarrative,
    facts: dict[str, Any],
    scenario: dict[str, Any],
    news: list[dict[str, Any]],
) -> tuple[AnalystNarrative, ValidationReport]:
    allowed: set[float] = set()
    _collect_numbers(facts, allowed)
    _collect_numbers(scenario, allowed)
    _collect_numbers(news, allowed)
    report = ValidationReport(ok=True)

    for text in _texts(narrative):
        for pattern in _FORBIDDEN:
            if pattern.search(text):
                report.errors.append(f"verbotene Formulierung: '{pattern.pattern}'")
        for token in _NUM.findall(text):
            value = _parse_number(token)
            if value is None or _supported(value, allowed):
                continue
            msg = f"Zahl {token} nicht in den Eingabedaten belegt"
            if abs(value) >= 10:
                report.errors.append(msg)
            else:
                report.warnings.append(msg)

    by_id = {str(n["id"]): n for n in news}
    cleaned = []
    for a in narrative.news_assessments:
        src = by_id.get(a.news_id)
        if src is None:
            report.errors.append(f"unbekannte news_id {a.news_id}")
            continue
        corpus = _norm(" ".join(str(src.get(k) or "") for k in ("headline", "summary", "content")))
        kept = [f for f in a.verifiable_facts if _norm(f) and _norm(f) in corpus]
        dropped = len(a.verifiable_facts) - len(kept)
        if dropped:
            report.warnings.append(
                f"{dropped} nicht wörtlich belegte Fakten zu {a.news_id} entfernt"
            )
        cleaned.append(a.model_copy(update={"verifiable_facts": kept}))
    narrative = narrative.model_copy(update={"news_assessments": cleaned})
    report.ok = not report.errors
    return narrative, report
