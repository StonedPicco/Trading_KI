from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from app.analysis import indicators as ind
from tests.conftest import make_minute_bars, regular_session_frame


def test_sma_and_ema_match_reference() -> None:
    s = pd.Series([1.0, 2, 3, 4, 5, 6])
    assert ind.sma(s, 3).tolist()[2:] == [2.0, 3.0, 4.0, 5.0]
    # recursive EMA with alpha = 2/(n+1), seeded with the first value (adjust=False)
    e = ind.ema(s, 3)
    alpha = 0.5
    manual = [1.0]
    for x in s[1:]:
        manual.append(alpha * x + (1 - alpha) * manual[-1])
    assert np.allclose(e.dropna().to_numpy(), manual[2:])


def test_rsi_bounds_and_monotonic_series() -> None:
    up = pd.Series(np.arange(1, 40, dtype=float))
    down = pd.Series(np.arange(40, 1, -1, dtype=float))
    assert ind.rsi(up).dropna().iloc[-1] == pytest.approx(100.0)
    assert ind.rsi(down).dropna().iloc[-1] == pytest.approx(0.0)
    noisy = pd.Series(np.random.default_rng(0).normal(0, 1, 500).cumsum() + 100)
    r = ind.rsi(noisy).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_rsi_wilder_reference_value() -> None:
    # Alternating +1/-1 changes: average gain == average loss -> RSI 50 after warmup.
    closes = pd.Series([100 + (i % 2) for i in range(200)], dtype=float)
    assert ind.rsi(closes).iloc[-1] == pytest.approx(50.0, abs=2.0)


def test_atr_constant_range() -> None:
    idx = pd.date_range("2026-01-02", periods=50, freq="D", tz="UTC")
    df = pd.DataFrame({"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0}, index=idx)
    assert ind.atr(df, 14).iloc[-1] == pytest.approx(2.0)


def test_bollinger_width_zero_on_flat_series() -> None:
    bb = ind.bollinger(pd.Series([5.0] * 30))
    assert bb["upper"].iloc[-1] == pytest.approx(5.0)
    assert bb["width"].iloc[-1] == pytest.approx(0.0)


def test_macd_hist_is_line_minus_signal() -> None:
    s = pd.Series(np.linspace(10, 20, 100))
    m = ind.macd(s).dropna()
    assert np.allclose(m["hist"], m["macd"] - m["signal"])


def test_session_vwap_resets_each_session_and_ignores_extended_hours() -> None:
    day1 = make_minute_bars([10, 10, 10], datetime(2026, 10, 21, 13, 30, tzinfo=UTC))
    pre = make_minute_bars([50, 50], datetime(2026, 10, 22, 12, 0, tzinfo=UTC))  # pre-market
    day2 = make_minute_bars([20, 20, 20], datetime(2026, 10, 22, 13, 30, tzinfo=UTC))
    df = pd.concat([day1, pre, day2])
    v = ind.session_vwap(df)
    assert v.loc[day1.index].tolist() == pytest.approx([10, 10, 10])
    assert v.loc[pre.index].isna().all()
    assert v.loc[day2.index].tolist() == pytest.approx([20, 20, 20])


def test_rvol_is_one_for_identical_sessions_and_detects_spike() -> None:
    end = datetime(2026, 10, 22, 20, 0, tzinfo=UTC)
    df = regular_session_frame(25, end)
    df["volume"] = 1000.0
    last_ts = df.index[-1]
    df.loc[last_ts, "volume"] = 5000.0
    rv = ind.relative_volume(df)
    assert rv["rvol_bar"].iloc[-2] == pytest.approx(1.0)
    assert rv["rvol_bar"].iloc[-1] == pytest.approx(5.0)
    # cumulative RVOL only moves slightly by one spike bar
    assert 1.0 < rv["rvol_cum"].iloc[-1] < 1.02


def test_percentile_rank_range() -> None:
    s = pd.Series(np.arange(300, dtype=float))
    pr = ind.percentile_rank(s, 100).dropna()
    assert pr.iloc[-1] == pytest.approx(1.0)
    assert ((pr >= 0) & (pr <= 1)).all()
