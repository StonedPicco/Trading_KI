"""Market context: volatility regime, relative strength vs. market and sector, liquidity."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

from app.analysis.indicators import atr, percentile_rank, regular_session_mask

SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLE": "Energy",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}

# Small static default mapping; users can override per watchlist entry.
DEFAULT_SECTOR = {
    "AAPL": "XLK",
    "MSFT": "XLK",
    "NVDA": "XLK",
    "AMD": "XLK",
    "AVGO": "XLK",
    "INTC": "XLK",
    "GOOGL": "XLC",
    "GOOG": "XLC",
    "META": "XLC",
    "NFLX": "XLC",
    "AMZN": "XLY",
    "TSLA": "XLY",
    "HD": "XLY",
    "NKE": "XLY",
    "JPM": "XLF",
    "BAC": "XLF",
    "GS": "XLF",
    "V": "XLF",
    "MA": "XLF",
    "XOM": "XLE",
    "CVX": "XLE",
    "UNH": "XLV",
    "JNJ": "XLV",
    "LLY": "XLV",
    "PFE": "XLV",
    "BA": "XLI",
    "CAT": "XLI",
    "WMT": "XLP",
    "KO": "XLP",
    "PG": "XLP",
}


@dataclass
class VolatilityRegime:
    atr_pct: float | None  # daily ATR(14) as % of close
    percentile_1y: float | None
    regime: Literal["low", "normal", "high", "unknown"]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def volatility_regime(daily: pd.DataFrame) -> VolatilityRegime:
    if len(daily) < 30:
        return VolatilityRegime(None, None, "unknown")
    atr_pct = atr(daily) / daily["close"] * 100
    pct = percentile_rank(atr_pct, 252)
    last_pct = float(pct.iloc[-1]) if pd.notna(pct.iloc[-1]) else None
    regime: Literal["low", "normal", "high", "unknown"] = "unknown"
    if last_pct is not None:
        regime = "low" if last_pct < 0.25 else "high" if last_pct > 0.75 else "normal"
    return VolatilityRegime(round(float(atr_pct.iloc[-1]), 3), last_pct, regime)


def regime_series(daily: pd.DataFrame) -> pd.Series:
    """Per-session volatility regime known *before* the session (shifted by one day)."""
    atr_pct = atr(daily) / daily["close"]
    pct = percentile_rank(atr_pct, 252).shift(1)
    labels = np.where(pct < 0.25, "low", np.where(pct > 0.75, "high", "normal"))
    out = pd.Series(labels, index=daily.index.date, dtype="object")
    return out.where(pct.notna().to_numpy(), "unknown")


def _session_return(minute: pd.DataFrame, session: date) -> float | None:
    local_dates = minute.index.tz_convert("America/New_York").date
    today = minute[(local_dates == session) & regular_session_mask(minute.index)]
    if today.empty:
        return None
    return float(today["close"].iloc[-1] / today["open"].iloc[0] - 1)


def _n_day_return(daily: pd.DataFrame, last_price: float, n: int) -> float | None:
    if len(daily) < n + 1:
        return None
    return float(last_price / daily["close"].iloc[-(n + 1)] - 1)


@dataclass
class RelativeStrength:
    benchmark: str
    stock_intraday: float | None
    bench_intraday: float | None
    rs_intraday: float | None  # difference in percentage points
    stock_5d: float | None
    bench_5d: float | None
    rs_5d: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def relative_strength(
    benchmark: str,
    stock_minute: pd.DataFrame,
    stock_daily: pd.DataFrame,
    bench_minute: pd.DataFrame,
    bench_daily: pd.DataFrame,
    session: date,
) -> RelativeStrength:
    def pct(x: float | None) -> float | None:
        return None if x is None else round(x * 100, 3)

    s_i, b_i = _session_return(stock_minute, session), _session_return(bench_minute, session)
    s_last = float(stock_minute["close"].iloc[-1]) if not stock_minute.empty else None
    b_last = float(bench_minute["close"].iloc[-1]) if not bench_minute.empty else None
    prev_s = stock_daily[stock_daily.index.date < session]
    prev_b = bench_daily[bench_daily.index.date < session]
    s_5 = _n_day_return(prev_s, s_last, 5) if s_last else None
    b_5 = _n_day_return(prev_b, b_last, 5) if b_last else None
    return RelativeStrength(
        benchmark=benchmark,
        stock_intraday=pct(s_i),
        bench_intraday=pct(b_i),
        rs_intraday=pct(s_i - b_i) if s_i is not None and b_i is not None else None,
        stock_5d=pct(s_5),
        bench_5d=pct(b_5),
        rs_5d=pct(s_5 - b_5) if s_5 is not None and b_5 is not None else None,
    )


@dataclass
class Liquidity:
    avg_daily_volume_20d: float | None
    avg_dollar_volume_20d: float | None
    level: Literal["high", "medium", "low", "unknown"]
    note: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def liquidity(daily: pd.DataFrame, feed: str) -> Liquidity:
    if len(daily) < 5:
        return Liquidity(None, None, "unknown")
    tail = daily.iloc[-21:-1] if len(daily) > 21 else daily.iloc[:-1]
    vol = float(tail["volume"].mean())
    dollar = float((tail["volume"] * tail["close"]).mean())
    note = None
    if feed == "iex":
        # IEX volume is a fraction of consolidated volume; thresholds scaled accordingly.
        level = "high" if dollar > 10e6 else "medium" if dollar > 1e6 else "low"
        note = "Volumen nur IEX (nicht konsolidiert); Schwellen entsprechend skaliert."
    else:
        level = "high" if dollar > 200e6 else "medium" if dollar > 20e6 else "low"
    return Liquidity(round(vol), round(dollar), level, note)  # type: ignore[arg-type]
