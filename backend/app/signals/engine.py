"""Deterministic signal engine: facts -> evidence factors -> setup classification -> levels.

The engine is the *only* component that decides the outcome class and price levels. The LLM
may explain or disagree, but cannot change them.

Evidence balance is a transparent weighted sum of factor directions. It is explicitly NOT a
probability and is labelled "uncalibrated" until enough live, out-of-sample outcomes exist
(see services/evaluation.py).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Literal

ENGINE_VERSION = "0.1.0"


class Outcome(StrEnum):
    BULLISH_SETUP = "bullish_setup"
    BEARISH_SETUP = "bearish_setup"
    LONG_ENTRY = "long_entry"
    SHORT_ENTRY = "short_entry"
    INVALIDATED = "invalidated"
    WATCH = "watch"
    NO_TRADE = "no_trade"
    INSUFFICIENT_DATA = "insufficient_data"


OUTCOME_LABEL_DE = {
    Outcome.BULLISH_SETUP: "Bullisches Setup",
    Outcome.BEARISH_SETUP: "Bärisches Setup",
    Outcome.LONG_ENTRY: "Möglicher Long-Einstieg",
    Outcome.SHORT_ENTRY: "Möglicher Short-Einstieg",
    Outcome.INVALIDATED: "Bestehendes Setup invalidiert",
    Outcome.WATCH: "Beobachten / auf Bestätigung warten",
    Outcome.NO_TRADE: "Kein Trade empfohlen",
    Outcome.INSUFFICIENT_DATA: "Datenlage unzureichend",
}


@dataclass
class Factor:
    key: str
    direction: int  # +1 bullish, -1 bearish, 0 neutral/risk
    weight: float
    observation: str  # observable fact
    interpretation: str  # what it means (interpretation, clearly separated)

    @property
    def contribution(self) -> float:
        return self.direction * self.weight


@dataclass
class Scenario:
    outcome: Outcome
    label: str
    bias: Literal["long", "short", "neutral"]
    reference_price: float
    entry_zone: tuple[float, float] | None = None
    stop: float | None = None
    targets: list[float] = field(default_factory=list)
    reward_risk: float | None = None
    confirmation: list[str] = field(default_factory=list)
    invalidation: str | None = None
    invalidation_price: float | None = None
    evidence_score: float = 0.0
    evidence_note: str = "Evidenzbilanz – nicht kalibriert, keine Wahrscheinlichkeit"
    factors_for: list[dict[str, Any]] = field(default_factory=list)
    factors_against: list[dict[str, Any]] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    mtf_conflict: bool = False
    engine_version: str = ENGINE_VERSION

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["outcome"] = self.outcome.value
        return d


def _f(key: str, direction: int, weight: float, obs: str, interp: str) -> Factor:
    return Factor(key, direction, weight, obs, interp)


def _fmt(x: float | None, nd: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def collect_factors(facts: dict[str, Any]) -> list[Factor]:
    factors: list[Factor] = []
    trends: dict[str, dict[str, Any]] = facts.get("trends", {})
    weights = {"1Week": 1.0, "1Day": 2.0, "1Hour": 1.5, "15Min": 1.0, "5Min": 1.0}
    for tf, w in weights.items():
        t = trends.get(tf)
        if not t or (t.get("structure") == "insufficient" and t.get("bars", 0) < 30):
            continue
        d = {"up": 1, "down": -1}.get(t["direction"], 0)
        if d:
            factors.append(
                _f(
                    f"trend_{tf}",
                    d,
                    w,
                    f"{tf}: Trend {t['direction']}, Struktur {t['structure']}, "
                    f"Kurs {_fmt(t['close'])} vs. EMA20 {_fmt(t['ema20'])}"
                    f"/EMA50 {_fmt(t['ema50'])}",
                    f"Trend im {tf}-Chart {'stützt Long' if d > 0 else 'stützt Short'}",
                )
            )

    ind = facts.get("intraday", {})
    price = facts["price"]
    vwap = ind.get("vwap")
    atr5 = ind.get("atr_5m")
    if vwap and atr5:
        dist = (price - vwap) / atr5
        if abs(dist) > 0.2:
            factors.append(
                _f(
                    "vwap",
                    1 if dist > 0 else -1,
                    1.0,
                    f"Kurs {_fmt(price)} {'über' if dist > 0 else 'unter'} VWAP {_fmt(vwap)} "
                    f"({_fmt(dist, 1)} ATR5m)",
                    "Intraday-Käufer im Vorteil" if dist > 0 else "Intraday-Verkäufer im Vorteil",
                )
            )
        if abs(dist) > 2.5:
            factors.append(
                _f(
                    "extension",
                    -1 if dist > 0 else 1,
                    1.5,
                    f"Abstand zum VWAP {_fmt(dist, 1)} ATR5m",
                    "Anstieg kurzfristig überdehnt – erhöhtes Rücksetzer-Risiko"
                    if dist > 0
                    else "Abverkauf kurzfristig überdehnt – Gegenbewegung möglich",
                )
            )
    r5 = ind.get("rsi_5m")
    if r5 is not None and (r5 > 75 or r5 < 25):
        factors.append(
            _f(
                "rsi_extreme",
                -1 if r5 > 75 else 1,
                1.0,
                f"RSI(14) 5m = {_fmt(r5, 1)}",
                "Überkauft – Momentum erschöpft sich häufig" if r5 > 75 else "Überverkauft",
            )
        )
    div = ind.get("divergence_15m")
    if div:
        factors.append(
            _f(
                "divergence",
                -1 if div == "bearish" else 1,
                1.0,
                f"RSI-Divergenz 15m: {div}",
                "Momentumverlust beim letzten Hoch"
                if div == "bearish"
                else "Abwärtsmomentum lässt nach",
            )
        )

    for ev in facts.get("level_events", []):
        bullish = ev["kind"] in ("breakout", "false_breakout_down")
        is_false = ev["kind"].startswith("false")
        conf = ev["volume_confirmed"]
        weight = 1.5 if is_false else (2.0 if conf else 0.5)
        factors.append(
            _f(
                f"level_{ev['kind']}",
                1 if bullish else -1,
                weight,
                f"{ev['kind']} an {_fmt(ev['level'])} (RVOL {_fmt(ev['rvol'], 1)})",
                (
                    "Ausbruch volumenbestätigt"
                    if conf
                    else "Ausbruch ohne Volumenbestätigung – fragil"
                )
                if not is_false
                else "Fehlausbruch – Gegenbewegung wahrscheinlicher als Fortsetzung",
            )
        )

    rs = facts.get("relative_strength", {})
    for key, label in (("market", "SPY"), ("sector", "Sektor")):
        r = rs.get(key) or {}
        val = r.get("rs_intraday")
        if val is not None and abs(val) >= 0.5:
            factors.append(
                _f(
                    f"rs_{key}",
                    1 if val > 0 else -1,
                    1.0,
                    f"Relative Stärke vs. {r.get('benchmark', label)} heute: {_fmt(val)} %-Punkte",
                    "Aktie stärker als Vergleich" if val > 0 else "Aktie schwächer als Vergleich",
                )
            )
    mkt = facts.get("market_trend_5m")
    if mkt in ("up", "down"):
        factors.append(
            _f(
                "market_trend",
                1 if mkt == "up" else -1,
                0.75,
                f"SPY 5m-Trend: {mkt}",
                "Gesamtmarkt-Rückenwind" if mkt == "up" else "Gesamtmarkt-Gegenwind",
            )
        )

    sim = facts.get("similarity") or {}
    if sim.get("status") == "ok":
        h30 = next((h for h in sim.get("horizons", []) if h["horizon_min"] == 30), None)
        if h30 and h30.get("distinguishable") and sim.get("statistically_usable"):
            up = (h30["hit_rate"] or 0) > (h30["base_hit_rate"] or 0)
            factors.append(
                _f(
                    "history",
                    1 if up else -1,
                    1.0,
                    f"{h30['n']} Analogien: Trefferquote 30 Min. "
                    f"{_fmt((h30['hit_rate'] or 0) * 100, 0)} % "
                    f"vs. Basis {_fmt((h30['base_hit_rate'] or 0) * 100, 0)} %",
                    "Historisch ähnliche Situationen liefen überdurchschnittlich "
                    + ("positiv" if up else "negativ"),
                )
            )

    for n in facts.get("news_signals", []):
        if n.get("confirmed_by_price") and n.get("direction") in ("bullish", "bearish"):
            factors.append(
                _f(
                    f"news_{n['id']}",
                    1 if n["direction"] == "bullish" else -1,
                    1.0,
                    f"Nachricht: {n['headline'][:90]}",
                    "Nachricht durch Kursreaktion und Volumen bestätigt",
                )
            )
    return factors


def _nearest(levels: list[float], price: float, above: bool) -> float | None:
    cands = [lv for lv in levels if (lv > price if above else lv < price)]
    if not cands:
        return None
    return min(cands) if above else max(cands)


def build_scenario(
    facts: dict[str, Any],
    min_rr: float = 1.5,
    previous: dict[str, Any] | None = None,
) -> Scenario:
    price = float(facts["price"])
    dq = facts.get("data_quality", {})
    if not dq.get("ok", False):
        return Scenario(
            Outcome.INSUFFICIENT_DATA,
            OUTCOME_LABEL_DE[Outcome.INSUFFICIENT_DATA],
            "neutral",
            price,
            reasons=list(dq.get("issues", [])) or ["Datenqualität unzureichend"],
        )

    # Invalidation of the previous scenario takes precedence.
    if (
        previous
        and previous.get("invalidation_price")
        and previous.get("bias") in ("long", "short")
    ):
        inv = float(previous["invalidation_price"])
        hit = price < inv if previous["bias"] == "long" else price > inv
        if hit:
            return Scenario(
                Outcome.INVALIDATED,
                OUTCOME_LABEL_DE[Outcome.INVALIDATED],
                "neutral",
                price,
                reasons=[
                    f"Vorheriges {previous['bias']}-Szenario: Invalidierung bei {inv:.2f} "
                    f"erreicht (Kurs {price:.2f})"
                ],
                invalidation_price=inv,
            )

    factors = collect_factors(facts)
    score = round(sum(f.contribution for f in factors), 2)
    pro = [asdict(f) for f in factors if f.direction > 0]
    con = [asdict(f) for f in factors if f.direction < 0]

    trends = facts.get("trends", {})
    htf = {"up": 1, "down": -1}.get(trends.get("1Day", {}).get("direction", ""), 0)
    ltf = sum(
        {"up": 1, "down": -1}.get(trends.get(tf, {}).get("direction", ""), 0)
        for tf in ("5Min", "15Min")
    )
    mtf_conflict = htf != 0 and ltf != 0 and (htf > 0) != (ltf > 0)

    risks: list[str] = []
    regime = (facts.get("volatility") or {}).get("regime")
    if regime == "high":
        risks.append("Hohes Volatilitätsregime: größere Stops nötig, Positionsgröße reduzieren")
    liq = (facts.get("liquidity") or {}).get("level")
    if liq == "low":
        risks.append("Geringe Liquidität: Bewegungen können irreführend sein, Slippage-Risiko")
    phase = facts.get("market_phase")
    if phase in ("pre_market", "after_hours"):
        risks.append("Außerbörsliche Handelszeit: dünneres Orderbuch, breitere Spreads")
    if phase == "closed":
        risks.append("Markt geschlossen: Szenario gilt frühestens für die nächste Session")
    if mtf_conflict:
        risks.append("Konflikt zwischen Tages-Trend und Intraday-Trend")
    for ev in facts.get("upcoming_events", []):
        risks.append(ev)
    for note in (facts.get("provenance") or {}).get("notes", []):
        risks.append(f"Datenhinweis: {note}")

    bias: Literal["long", "short", "neutral"] = (
        "long" if score >= 3 else "short" if score <= -3 else "neutral"
    )
    zones = facts.get("zones", [])
    kl = facts.get("key_levels", {})
    level_prices = sorted(
        {z["low"] for z in zones}
        | {z["high"] for z in zones}
        | {v for k, v in kl.items() if v is not None and k != "session_open"}
    )
    atr5 = (facts.get("intraday") or {}).get("atr_5m") or price * 0.003
    vwap = (facts.get("intraday") or {}).get("vwap")

    base: dict[str, Any] = dict(
        reference_price=price,
        evidence_score=score,
        factors_for=pro,
        factors_against=con,
        risks=risks,
        mtf_conflict=mtf_conflict,
    )
    if bias == "neutral":
        reasons = [
            f"Keine ausreichende Evidenz in eine Richtung (Evidenzbilanz {score:+.1f}, Schwelle ±3)"
        ]
        near = [lv for lv in level_prices if abs(lv - price) <= 0.5 * atr5]
        if near:
            return Scenario(
                Outcome.WATCH,
                OUTCOME_LABEL_DE[Outcome.WATCH],
                "neutral",
                reasons=[*reasons, f"Kurs nahe Schlüsselniveau {near[0]:.2f} – Reaktion abwarten"],
                confirmation=[f"Schlusskurs (5m) jenseits {near[0]:.2f} mit RVOL ≥ 1,5"],
                **base,
            )
        return Scenario(
            Outcome.NO_TRADE, OUTCOME_LABEL_DE[Outcome.NO_TRADE], "neutral", reasons=reasons, **base
        )

    sign = 1 if bias == "long" else -1
    breakout = next(
        (
            e
            for e in reversed(facts.get("level_events", []))
            if e["kind"] == ("breakout" if sign > 0 else "breakdown")
        ),
        None,
    )
    if breakout:
        lvl = breakout["level"]
        entry = (lvl, lvl + sign * 0.3 * atr5)
    else:
        anchor = (
            vwap if vwap is not None and (price - vwap) * sign > 0 else price - sign * 0.5 * atr5
        )
        entry = (anchor, price) if sign > 0 else (price, anchor)
    entry_lo, entry_hi = sorted(entry)
    entry_mid = (entry_lo + entry_hi) / 2

    structural = _nearest(level_prices, entry_lo if sign > 0 else entry_hi, above=sign < 0)
    fallback_stop = entry_mid - sign * 1.5 * atr5
    stop = fallback_stop
    if structural is not None and abs(entry_mid - structural) <= 3 * atr5:
        stop = structural - sign * 0.2 * atr5
    if abs(entry_mid - stop) < 0.75 * atr5:
        stop = entry_mid - sign * 0.75 * atr5
    risk = abs(entry_mid - stop)

    tgt_levels = (
        [lv for lv in level_prices if (lv - entry_hi) * sign > 0.25 * atr5]
        if sign > 0
        else [lv for lv in level_prices if (entry_lo - lv) > 0.25 * atr5]
    )
    tgt_levels = sorted(tgt_levels, key=lambda lv: abs(lv - entry_mid))[:2]
    targets = tgt_levels or [entry_mid + sign * 2 * risk, entry_mid + sign * 3 * risk]
    if len(targets) == 1:
        targets.append(entry_mid + sign * max(3 * risk, abs(targets[0] - entry_mid) * 1.5))
    rr = round(abs(targets[0] - entry_mid) / risk, 2) if risk > 0 else None

    invalidation_text = (
        f"{'Unterschreiten' if sign > 0 else 'Überschreiten'} von {stop:.2f} "
        f"(Struktur/ATR-Stop) oder {'Verlust' if sign > 0 else 'Rückeroberung'} des VWAP "
        "mit Volumen"
    )
    confirmation = []
    if breakout and not breakout["volume_confirmed"]:
        confirmation.append("Volumenbestätigung fehlt: RVOL ≥ 1,5 auf dem nächsten 5m-Bar abwarten")
    if not breakout:
        confirmation.append(
            f"Halten {'über' if sign > 0 else 'unter'} {entry_lo if sign > 0 else entry_hi:.2f} "
            "bei Rücksetzer; Umkehrkerze mit steigendem Volumen"
        )
    reasons = [f"Evidenzbilanz {score:+.1f} ({len(pro)} Pro / {len(con)} Contra Faktoren)"]

    downgrade: list[str] = []
    if rr is None or rr < min_rr:
        downgrade.append(f"Chance-Risiko {rr} < Mindestwert {min_rr}")
    if mtf_conflict:
        downgrade.append("Multi-Timeframe-Konflikt")
    if phase in ("pre_market", "after_hours", "closed"):
        downgrade.append(f"Marktphase {phase}")
    if liq == "low":
        downgrade.append("geringe Liquidität")
    in_zone = entry_lo - 0.25 * atr5 <= price <= entry_hi + 0.25 * atr5
    if not in_zone:
        downgrade.append("Kurs außerhalb der Entry-Zone")
    if breakout and not breakout["volume_confirmed"]:
        downgrade.append("Ausbruch ohne Volumenbestätigung")

    common: dict[str, Any] = dict(
        entry_zone=(round(entry_lo, 2), round(entry_hi, 2)),
        stop=round(stop, 2),
        targets=[round(t, 2) for t in targets],
        reward_risk=rr,
        confirmation=confirmation,
        invalidation=invalidation_text,
        invalidation_price=round(stop, 2),
        **base,
    )
    if rr is not None and rr < min_rr:
        return Scenario(
            Outcome.WATCH,
            OUTCOME_LABEL_DE[Outcome.WATCH],
            bias,
            reasons=[*reasons, *downgrade],
            **common,
        )
    if downgrade:
        outcome = Outcome.BULLISH_SETUP if sign > 0 else Outcome.BEARISH_SETUP
        return Scenario(
            outcome,
            OUTCOME_LABEL_DE[outcome],
            bias,
            reasons=[*reasons, *("Kein sofortiger Einstieg: " + d for d in downgrade)],
            **common,
        )
    outcome = Outcome.LONG_ENTRY if sign > 0 else Outcome.SHORT_ENTRY
    return Scenario(outcome, OUTCOME_LABEL_DE[outcome], bias, reasons=reasons, **common)
