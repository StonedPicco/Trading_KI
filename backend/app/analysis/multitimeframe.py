"""Resampling of native bars (1Min, 1Day) into higher timeframes."""

from __future__ import annotations

import pandas as pd

from app.domain.models import BAR_COLUMNS, Timeframe

_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
    "trade_count": "sum",
}


def resample_intraday(minute: pd.DataFrame, timeframe: Timeframe) -> pd.DataFrame:
    """Resample 1-minute bars. 5/15-min buckets align with the 09:30 open naturally; hourly
    buckets are offset by 30 minutes so they start at 09:30, 10:30, … (session aligned)."""
    if timeframe == Timeframe.M1 or minute.empty:
        return minute
    if not timeframe.is_intraday:
        raise ValueError("use resample_daily for daily/weekly bars")
    offset = "30min" if timeframe == Timeframe.H1 else None
    df = minute.copy()
    df["pv"] = df["vwap"].fillna(df["close"]) * df["volume"]
    rule = f"{timeframe.minutes}min"
    res = df.resample(rule, label="left", closed="left", offset=offset)
    out = res.agg({**_AGG, "pv": "sum"})
    out = out.dropna(subset=["open"])
    out["vwap"] = out["pv"] / out["volume"].where(out["volume"] > 0)
    return out[BAR_COLUMNS]


def resample_daily(daily: pd.DataFrame, timeframe: Timeframe) -> pd.DataFrame:
    if timeframe == Timeframe.D1 or daily.empty:
        return daily
    if timeframe != Timeframe.W1:
        raise ValueError(f"unsupported timeframe {timeframe}")
    df = daily.copy()
    df["pv"] = df["vwap"].fillna(df["close"]) * df["volume"]
    week_start = df.index.normalize() - pd.to_timedelta(df.index.day_of_week, unit="D")
    out = df.groupby(week_start).agg({**_AGG, "pv": "sum"})
    out.index = pd.DatetimeIndex(out.index, name="ts")
    out["vwap"] = out["pv"] / out["volume"].where(out["volume"] > 0)
    return out[BAR_COLUMNS]


def build_timeframes(minute: pd.DataFrame, daily: pd.DataFrame) -> dict[Timeframe, pd.DataFrame]:
    return {
        Timeframe.M1: minute,
        Timeframe.M5: resample_intraday(minute, Timeframe.M5),
        Timeframe.M15: resample_intraday(minute, Timeframe.M15),
        Timeframe.H1: resample_intraday(minute, Timeframe.H1),
        Timeframe.D1: daily,
        Timeframe.W1: resample_daily(daily, Timeframe.W1),
    }
