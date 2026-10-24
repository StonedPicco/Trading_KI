"""Deterministic SYNTHETIC market data for development without API keys.

Everything produced here is labelled ``DataKind.DEMO`` / feed ``demo``. It is generated from a
seeded random process (regime-switching volatility, intraday U-shaped volume, occasional
jumps) and has **no relation to real prices**. It exists so the full pipeline (charts,
indicators, similarity search, signals) can be exercised end to end.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from app.core.market_time import session_times, trading_days, utcnow
from app.domain.models import BAR_COLUMNS, DataKind, Provenance, Timeframe
from app.providers.base import empty_bars

ANCHOR = date(2018, 1, 2)


def _seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:8], "little")


@lru_cache(maxsize=64)
def _daily_path(symbol: str) -> pd.DataFrame:
    """Seeded daily process per symbol: overnight gap and intraday return drawn independently.

    Intraday paths are Brownian bridges from the open to the close; because the close is drawn
    from the same distribution as a free walk's end point, the bridge is statistically a plain
    random walk (no artificial intraday predictability).
    """
    days = trading_days(ANCHOR, _last_session())
    rng = np.random.default_rng(_seed("daily", symbol))
    n = len(days)
    regime = np.cumsum(rng.random(n) < 0.02) % 3  # occasional volatility regime switches
    vol = np.array([0.009, 0.015, 0.026])[regime]
    gap = rng.normal(0, 1, n) * vol * 0.35
    intraday = vol * rng.standard_t(df=5, size=n) / np.sqrt(5 / 3)
    drift = 0.0002 if symbol not in ("SPY", "QQQ") else 0.0003
    start_price = 30 + (_seed("price", symbol) % 400)
    log_close = np.log(start_price) + np.cumsum(drift + gap + intraday)
    return pd.DataFrame(
        {"close": np.exp(log_close), "gap": gap, "vol": vol},
        index=pd.Index(days, name="day"),
    )


@lru_cache(maxsize=1)
def _last_session() -> date:
    from app.core.market_time import _calendar

    return _calendar().last_session.date()


def _bridge(rng: np.random.Generator, start: float, end: float, n: int, step: float) -> np.ndarray:
    """Log-price Brownian bridge with fat-tailed increments; returns n points ending at ``end``."""
    if n <= 0:
        return np.empty(0)
    w = np.cumsum(rng.standard_t(df=4, size=n) / np.sqrt(2) * step)
    t = np.arange(1, n + 1) / n
    return start + w - t * (w[-1] - (end - start))


@lru_cache(maxsize=4096)
def _intraday_day(symbol: str, day: date) -> pd.DataFrame:
    st = session_times(day)
    path = _daily_path(symbol)
    if st is None or day not in path.index:
        return empty_bars()
    pos = path.index.get_loc(day)
    row = path.iloc[pos]
    prev_close = float(path["close"].iloc[pos - 1]) if pos > 0 else float(row["close"])
    rng = np.random.default_rng(_seed("intraday", symbol, day.isoformat()))

    def minutes_between(a: datetime, b: datetime) -> int:
        return int((b - a).total_seconds() // 60)

    n_pre = minutes_between(st.pre_open, st.open)
    n_reg = minutes_between(st.open, st.close)
    n_aft = minutes_between(st.close, st.after_close)
    vol = float(row["vol"])
    log_prev, log_open = np.log(prev_close), np.log(prev_close) + float(row["gap"])
    log_close = np.log(float(row["close"]))
    pre = _bridge(rng, log_prev, log_open, n_pre, vol * 0.1 / np.sqrt(max(n_pre, 1)))
    reg = _bridge(rng, log_open, log_close, n_reg, vol / np.sqrt(max(n_reg, 1)))
    aft = log_close + np.cumsum(
        rng.standard_t(df=4, size=n_aft) / np.sqrt(2) * vol * 0.1 / np.sqrt(max(n_aft, 1))
    )
    logp = np.concatenate([pre, reg, aft])
    minutes = len(logp)
    idx = pd.date_range(st.pre_open, periods=minutes, freq="1min", tz="UTC")
    regular = (idx >= st.open) & (idx < st.close)

    close = np.exp(logp)
    open_ = np.concatenate([[prev_close], close[:-1]])
    open_[n_pre] = np.exp(log_open)  # regular session opens exactly at the gap price
    step = np.where(regular, vol / np.sqrt(max(n_reg, 1)), vol * 0.1 / np.sqrt(max(n_pre, 1)))
    wick = np.abs(rng.normal(0, step * 0.6)) * close
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - np.abs(rng.normal(0, step * 0.6)) * close

    minute_of_session = np.clip((idx - st.open).total_seconds() / 60.0, 0, None)
    session_len = max(n_reg, 1)
    u_shape = (
        1.0
        + 3.0 * np.exp(-minute_of_session / 25)
        + 2.0 * np.exp(-(session_len - minute_of_session) / 30)
    )
    base_vol = 2_000 + (_seed("vol", symbol) % 20_000)
    move = np.abs(np.diff(logp, prepend=logp[0])) / np.maximum(step, 1e-9)
    volume = base_vol * u_shape * np.where(regular, 1.0, 0.06) * rng.lognormal(0, 0.45, minutes)
    volume *= 1 + 0.8 * np.clip(move - 1.5, 0, 6)  # volume follows large moves
    vwap = (open_ + high + low + close) / 4

    df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.round(volume),
            "vwap": vwap,
            "trade_count": np.maximum(1, np.round(volume / 80)),
        },
        index=pd.DatetimeIndex(idx, name="ts"),
    )
    return df[BAR_COLUMNS]


class DemoMarketData:
    name = "demo"
    feed = "demo"

    def __init__(self, now: datetime | None = None) -> None:
        self._fixed_now = now

    def now(self) -> datetime:
        return self._fixed_now or utcnow()

    def provenance(self, timeframe: Timeframe, as_of: datetime | None = None) -> Provenance:
        return Provenance(
            provider="demo",
            feed="demo",
            data_kind=DataKind.DEMO,
            is_realtime=False,
            as_of=as_of,
            notes=["SIMULIERTE DATEN – keine echten Marktkurse. Nur für Entwicklung/Tests."],
        )

    async def get_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame:
        end = min(end, self.now())
        if end <= start:
            return empty_bars()
        symbol = symbol.upper()
        days = trading_days(start.date() - timedelta(days=1), end.date())
        if timeframe == Timeframe.D1:
            return _daily_from_minutes(symbol, days, start, end)
        if timeframe != Timeframe.M1:
            raise ValueError(f"demo provider only serves native timeframes, got {timeframe}")
        frames = [f for f in (_intraday_day(symbol, d) for d in days) if not f.empty]
        if not frames:
            return empty_bars()
        minute = pd.concat(frames)
        return minute[(minute.index >= start) & (minute.index < end)]

    async def aclose(self) -> None:
        return None


@lru_cache(maxsize=8192)
def _daily_bar(symbol: str, day: date) -> tuple[float, ...] | None:
    st = session_times(day)
    if st is None:
        return None
    df = _intraday_day(symbol, day)
    if df.empty:
        return None
    lo = df.index.searchsorted(pd.Timestamp(st.open))
    hi = df.index.searchsorted(pd.Timestamp(st.close))
    reg = df.iloc[lo:hi]
    vol = float(reg["volume"].sum())
    return (
        float(reg["open"].iloc[0]),
        float(reg["high"].max()),
        float(reg["low"].min()),
        float(reg["close"].iloc[-1]),
        vol,
        float((reg["vwap"] * reg["volume"]).sum() / max(vol, 1.0)),
        float(reg["trade_count"].sum()),
    )


def _daily_from_minutes(
    symbol: str, days: list[date], start: datetime, end: datetime
) -> pd.DataFrame:
    rows, index = [], []
    for d in days:
        st = session_times(d)
        # Only completed sessions appear as daily bars; the current session is partial.
        if (
            st is None
            or st.close > end
            or pd.Timestamp(d, tz="UTC") < pd.Timestamp(start.date(), tz="UTC")
        ):
            continue
        bar = _daily_bar(symbol, d)
        if bar is not None:
            rows.append(bar)
            index.append(pd.Timestamp(d, tz="UTC"))
    if not rows:
        return empty_bars()
    return pd.DataFrame(rows, columns=BAR_COLUMNS, index=pd.DatetimeIndex(index, name="ts"))
