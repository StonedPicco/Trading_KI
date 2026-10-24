from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from app.analysis import structure as st
from tests.conftest import make_minute_bars


def _bars(closes: list[float]) -> pd.DataFrame:
    return make_minute_bars(closes, datetime(2026, 10, 22, 13, 30, tzinfo=UTC), wick=0.0)


def test_swing_points_are_confirmed_after_right_bars() -> None:
    closes = [1, 2, 3, 5, 3, 2, 1, 2, 3, 2, 1]
    df = _bars(closes)
    df["high"] = df["close"]
    df["low"] = df["close"]
    swings = st.swing_points(df, left=2, right=2)
    high = next(s for s in swings if s.kind == "high")
    assert high.price == 5
    assert high.confirmed_at == df.index[5]  # 2 bars after the pivot


def test_structure_classification() -> None:
    def sw(kind: str, prices: list[float]) -> list[st.Swing]:
        ts = pd.Timestamp("2026-01-01", tz="UTC")
        return [st.Swing(ts, ts, p, kind) for p in prices]  # type: ignore[arg-type]

    assert st.classify_structure(sw("high", [10, 12]) + sw("low", [8, 9])).label == "HH_HL"
    assert st.classify_structure(sw("high", [12, 10]) + sw("low", [9, 8])).label == "LH_LL"
    assert st.classify_structure(sw("high", [12]) + sw("low", [9])).label == "insufficient"


def test_assess_trend_uptrend() -> None:
    x = np.arange(400, dtype=float)
    closes = 100 + 0.05 * x + 0.5 * np.sin(x / 6)  # rising with swings
    t = st.assess_trend(_bars(list(closes)), "5Min")
    assert t.direction == "up"
    assert t.structure == "HH_HL"


def test_zone_clustering_does_not_chain() -> None:
    ts = pd.Timestamp("2026-01-01", tz="UTC")
    # evenly spaced swings 0.4 apart with tolerance 0.5 would chain into one zone without the cap
    swings = {"1Hour": [st.Swing(ts, ts, 100 + 0.4 * i, "high") for i in range(20)]}
    zones = st.cluster_zones(swings, tolerance=0.5, price=104.0, max_zones=20)
    assert all(z.high - z.low <= 2 * 0.5 + 2 * 0.5 * 0.15 + 1e-9 for z in zones)
    assert len(zones) > 3


def test_breakout_and_false_breakout_detection() -> None:
    zone = st.Zone(low=99.5, high=100.0, touches=3, last_touch="", sources=["1Hour"])
    breakout = _bars([99.0, 99.4, 99.8, 100.4, 100.6, 100.8, 101.0])
    rvol = pd.Series(2.0, index=breakout.index)
    ev = st.detect_level_events(breakout, [zone], rvol, lookback=6)
    assert ev and ev[0].kind == "breakout" and ev[0].volume_confirmed

    fake = _bars([99.0, 99.4, 99.8, 99.9, 99.7, 99.6, 99.5])
    fake.iloc[3, fake.columns.get_loc("high")] = 100.6  # pierced, closed back below
    ev2 = st.detect_level_events(fake, [zone], None, lookback=6)
    assert ev2 and ev2[0].kind == "false_breakout_up" and not ev2[0].volume_confirmed


def test_gap_analysis() -> None:
    kl = st.KeyLevels(prev_day_close=100.0, session_open=102.0, session_low=99.5,
                      session_high=103.0)
    gap = st.gap_analysis(kl, daily_atr=2.0)
    assert gap is not None
    assert gap.direction == "up" and gap.gap_pct == 2.0 and gap.gap_atr == 1.0
    assert gap.filled


def test_rsi_divergence() -> None:
    ts = pd.Timestamp("2026-01-01", tz="UTC")
    highs = [st.Swing(ts, ts, 10, "high", 70.0), st.Swing(ts, ts, 11, "high", 60.0)]
    assert st.rsi_divergence(highs) == "bearish"
