"""Technical indicators as pure, causal functions.

Every value at index *t* depends only on data at or before *t* (no look-ahead). Definitions:

* EMA: ``span=n``, ``adjust=False`` (recursive form used by most charting platforms)
* RSI / ATR: Wilder smoothing (``alpha = 1/n``)
* VWAP: anchored per NY trading date, regular session only by default
* RVOL: cumulative volume since session start vs. the mean cumulative volume at the same
  minute-of-session over the previous ``lookback`` sessions (today excluded)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

NY_TZ = "America/New_York"


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False, min_periods=n).mean()


def wilder(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = wilder(delta.clip(lower=0), n)
    loss = wilder(-delta.clip(upper=0), n)
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    # No losses in window -> RSI 100; no gains -> 0 (handled by rs=inf / rs=0).
    out = out.where(loss != 0, 100.0)
    return out.where(gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    )
    return ranges.max(axis=1, skipna=True)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return wilder(true_range(df), n)


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    std = close.rolling(n, min_periods=n).std(ddof=0)
    upper, lower = mid + k * std, mid - k * std
    width = (upper - lower) / mid
    pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
    return pd.DataFrame(
        {"mid": mid, "upper": upper, "lower": lower, "pct_b": pct_b, "width": width}
    )


def ny_session_date(index: pd.DatetimeIndex) -> pd.Index:
    return pd.Index(index.tz_convert(NY_TZ).date, name="session")


def regular_session_mask(index: pd.DatetimeIndex) -> np.ndarray:
    """True for bars starting within 09:30–16:00 NY. Early closes are handled by the data
    itself (no regular bars are printed after an early close)."""
    local = index.tz_convert(NY_TZ)
    minutes = local.hour * 60 + local.minute
    return np.asarray((minutes >= 570) & (minutes < 960))


def session_vwap(df: pd.DataFrame, regular_only: bool = True) -> pd.Series:
    price = df["vwap"].where(df["vwap"].notna(), (df["high"] + df["low"] + df["close"]) / 3)
    vol = df["volume"].fillna(0)
    mask = regular_session_mask(df.index) if regular_only else np.ones(len(df), dtype=bool)
    pv = (price * vol).where(mask, 0.0)
    v = vol.where(mask, 0.0)
    session = ny_session_date(df.index)
    cum_pv = pv.groupby(session).cumsum()
    cum_v = v.groupby(session).cumsum()
    out = cum_pv / cum_v.replace(0, np.nan)
    return out.where(mask)


def minute_of_session(index: pd.DatetimeIndex) -> np.ndarray:
    """Minutes since 09:30 NY (negative in pre-market)."""
    local = index.tz_convert(NY_TZ)
    return np.asarray(local.hour * 60 + local.minute - 570)


def relative_volume(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """Time-of-day adjusted RVOL for intraday bars (regular session).

    Returns ``rvol_bar`` (bar volume vs. same-minute average) and ``rvol_cum`` (cumulative volume
    since the open vs. same-minute cumulative average). Previous sessions only.
    """
    mask = regular_session_mask(df.index)
    reg = df.loc[mask, ["volume"]].copy()
    if reg.empty:
        return pd.DataFrame(index=df.index, columns=["rvol_bar", "rvol_cum"], dtype="float64")
    reg["session"] = ny_session_date(reg.index)
    reg["mos"] = minute_of_session(reg.index)
    reg["cum"] = reg.groupby("session")["volume"].cumsum()

    bar_tbl = reg.pivot_table(index="session", columns="mos", values="volume", aggfunc="sum")
    cum_tbl = reg.pivot_table(index="session", columns="mos", values="cum", aggfunc="last")
    cum_tbl = cum_tbl.ffill(axis=1)
    bar_base = bar_tbl.rolling(lookback, min_periods=max(3, lookback // 4)).mean().shift(1)
    cum_base = cum_tbl.rolling(lookback, min_periods=max(3, lookback // 4)).mean().shift(1)

    sessions, mos = reg["session"].to_numpy(), reg["mos"].to_numpy()
    bar_base_vals = bar_base.stack().reindex(list(zip(sessions, mos, strict=True))).to_numpy()
    cum_base_vals = cum_base.stack().reindex(list(zip(sessions, mos, strict=True))).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        rvol_bar = reg["volume"].to_numpy() / bar_base_vals
        rvol_cum = reg["cum"].to_numpy() / cum_base_vals
    out = pd.DataFrame(index=df.index, columns=["rvol_bar", "rvol_cum"], dtype="float64")
    out.loc[reg.index, "rvol_bar"] = np.where(np.isfinite(rvol_bar), rvol_bar, np.nan)
    out.loc[reg.index, "rvol_cum"] = np.where(np.isfinite(rvol_cum), rvol_cum, np.nan)
    return out


def daily_rvol(daily: pd.DataFrame, lookback: int = 20) -> pd.Series:
    base = daily["volume"].rolling(lookback, min_periods=5).mean().shift(1)
    return daily["volume"] / base


def percentile_rank(series: pd.Series, window: int = 252) -> pd.Series:
    """Rolling percentile rank (0..1) of the latest value within the trailing window."""

    def _rank(x: np.ndarray) -> float:
        return float((x[:-1] < x[-1]).mean()) if len(x) > 1 else np.nan

    return series.rolling(window, min_periods=max(20, window // 5)).apply(_rank, raw=True)
