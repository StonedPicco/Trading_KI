from __future__ import annotations

from typing import Any

from app.signals.engine import Outcome, build_scenario


def _trend(direction: str, close: float = 100.0) -> dict[str, Any]:
    return {"direction": direction, "structure": "HH_HL" if direction == "up" else "LH_LL",
            "close": close, "ema20": close, "ema50": close, "bars": 500}


def bullish_facts(**overrides: Any) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "symbol": "TEST", "price": 100.0, "market_phase": "regular",
        "data_quality": {"ok": True, "issues": [], "info": []},
        "trends": {tf: _trend("up") for tf in ("1Week", "1Day", "1Hour", "15Min", "5Min")},
        "intraday": {"vwap": 99.6, "atr_5m": 0.4, "rsi_5m": 60.0},
        "key_levels": {"prev_day_high": 101.6, "prev_day_low": 97.0, "session_open": 99.0},
        "zones": [
            {"low": 98.9, "high": 99.1, "strength": 3},
            {"low": 102.4, "high": 102.8, "strength": 3},
        ],
        "level_events": [],
        "relative_strength": {"market": {"benchmark": "SPY", "rs_intraday": 1.0}},
        "market_trend_5m": "up",
        "volatility": {"regime": "normal"},
        "liquidity": {"level": "high"},
        "provenance": {"notes": []},
    }
    facts.update(overrides)
    return facts


def test_insufficient_data() -> None:
    sc = build_scenario(bullish_facts(data_quality={"ok": False, "issues": ["stale"]}))
    assert sc.outcome == Outcome.INSUFFICIENT_DATA
    assert sc.entry_zone is None


def test_bullish_alignment_produces_long_with_consistent_levels() -> None:
    sc = build_scenario(bullish_facts())
    assert sc.outcome == Outcome.LONG_ENTRY
    assert sc.entry_zone is not None and sc.stop is not None
    lo, hi = sc.entry_zone
    assert sc.stop < lo <= hi < sc.targets[0]
    assert sc.reward_risk is not None and sc.reward_risk >= 1.5
    assert sc.invalidation_price == sc.stop
    assert sc.evidence_score >= 3
    assert "nicht kalibriert" in sc.evidence_note


def test_no_evidence_means_no_trade() -> None:
    flat = {tf: _trend("sideways") for tf in ("1Week", "1Day", "1Hour", "15Min", "5Min")}
    sc = build_scenario(bullish_facts(
        trends=flat, intraday={"vwap": 100.0, "atr_5m": 0.4, "rsi_5m": 50},
        relative_strength={}, market_trend_5m="sideways",
        zones=[], key_levels={},
    ))
    assert sc.outcome == Outcome.NO_TRADE
    assert sc.bias == "neutral"


def test_mtf_conflict_downgrades_entry_to_setup() -> None:
    trends = {tf: _trend("up") for tf in ("1Week", "1Hour", "15Min", "5Min")}
    trends["1Day"] = _trend("down")
    sc = build_scenario(bullish_facts(trends=trends))
    assert sc.mtf_conflict
    assert sc.outcome in (Outcome.BULLISH_SETUP, Outcome.WATCH)
    assert any("Konflikt" in r for r in sc.risks)


def test_poor_reward_risk_yields_watch() -> None:
    # resistance right above the price -> first target too close
    sc = build_scenario(bullish_facts(zones=[{"low": 98.9, "high": 99.1, "strength": 3},
                                             {"low": 100.2, "high": 100.3, "strength": 3}],
                                      key_levels={}))
    assert sc.outcome == Outcome.WATCH
    assert sc.reward_risk is not None and sc.reward_risk < 1.5


def test_after_hours_never_produces_immediate_entry() -> None:
    sc = build_scenario(bullish_facts(market_phase="after_hours"))
    assert sc.outcome == Outcome.BULLISH_SETUP


def test_previous_long_is_invalidated_when_stop_breached() -> None:
    prev = {"bias": "long", "invalidation_price": 101.0}
    sc = build_scenario(bullish_facts(), previous=prev)
    assert sc.outcome == Outcome.INVALIDATED


def test_bearish_mirror_produces_short_levels() -> None:
    trends = {tf: _trend("down") for tf in ("1Week", "1Day", "1Hour", "15Min", "5Min")}
    sc = build_scenario(bullish_facts(
        trends=trends, intraday={"vwap": 100.4, "atr_5m": 0.4, "rsi_5m": 40},
        relative_strength={"market": {"benchmark": "SPY", "rs_intraday": -1.0}},
        market_trend_5m="down",
        zones=[{"low": 100.9, "high": 101.1, "strength": 3},
               {"low": 97.2, "high": 97.6, "strength": 3}],
        key_levels={"prev_day_low": 98.4},
    ))
    assert sc.bias == "short"
    assert sc.entry_zone is not None and sc.stop is not None
    assert sc.targets[0] < sc.entry_zone[0] <= sc.entry_zone[1] < sc.stop
