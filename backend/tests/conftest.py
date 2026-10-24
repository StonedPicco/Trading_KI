from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.core.market_time import session_times, set_fixed_now, trading_days
from app.domain.models import BAR_COLUMNS

# Thursday, regular session (13:45 New York)
FIXED_NOW = datetime(2026, 10, 22, 17, 45, tzinfo=UTC)


@pytest.fixture
def fixed_clock() -> Iterator[datetime]:
    set_fixed_now(FIXED_NOW)
    yield FIXED_NOW
    set_fixed_now(None)


def make_minute_bars(
    closes: list[float] | np.ndarray, start: datetime, volume: float = 1000.0, wick: float = 0.0
) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    idx = pd.date_range(start, periods=len(closes), freq="1min", tz="UTC", name="ts")
    opens = np.concatenate([[closes[0]], closes[:-1]])
    df = pd.DataFrame({
        "open": opens,
        "high": np.maximum(opens, closes) + wick,
        "low": np.minimum(opens, closes) - wick,
        "close": closes,
        "volume": np.full(len(closes), volume),
        "vwap": (opens + closes) / 2,
        "trade_count": np.full(len(closes), 10.0),
    }, index=idx)
    return df[BAR_COLUMNS]


def regular_session_frame(
    days: int, end_day: datetime, seed: int = 1, start_price: float = 100.0, vol: float = 0.0008
) -> pd.DataFrame:
    """Random-walk regular-session minute bars for ``days`` sessions ending at ``end_day``."""
    rng = np.random.default_rng(seed)
    sessions = trading_days((end_day - timedelta(days=days * 2)).date(), end_day.date())[-days:]
    frames = []
    price = start_price
    for d in sessions:
        st = session_times(d)
        assert st is not None
        n = int((st.close - st.open).total_seconds() // 60)
        closes = price * np.exp(np.cumsum(rng.normal(0, vol, n)))
        price = float(closes[-1])
        frames.append(make_minute_bars(closes, st.open, volume=float(rng.integers(500, 1500))))
    return pd.concat(frames)


def daily_from_minutes(minute: pd.DataFrame) -> pd.DataFrame:
    local = minute.index.tz_convert("America/New_York")
    g = minute.groupby(local.date)
    out = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
        "close": g["close"].last(), "volume": g["volume"].sum(), "vwap": g["vwap"].mean(),
        "trade_count": g["trade_count"].sum(),
    })
    out.index = pd.DatetimeIndex(pd.to_datetime(out.index).tz_localize("UTC"), name="ts")
    return out[BAR_COLUMNS]
