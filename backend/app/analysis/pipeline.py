"""Pure fact computation for one symbol at one point in time.

``compute_facts`` is used identically by the live AnalysisService and the backtester. It
truncates every input to information available at ``as_of`` (look-ahead guard) and synthesises
today's daily bar from completed minute bars, so a provider's (possibly final) daily bar for the
current session can never leak into the analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.analysis import context, structure
from app.analysis.indicators import (
    atr,
    bollinger,
    macd,
    regular_session_mask,
    relative_volume,
    rsi,
    session_vwap,
    sma,
)
from app.analysis.multitimeframe import build_timeframes
from app.analysis.similarity import build_feature_table, find_analogs
from app.core.market_time import market_phase, ny_date
from app.domain.models import BAR_COLUMNS, Provenance, Timeframe


@dataclass
class SymbolData:
    symbol: str
    minute: pd.DataFrame
    daily: pd.DataFrame


@dataclass
class FactInputs:
    target: SymbolData
    market: SymbolData | None  # SPY
    sector: SymbolData | None  # sector ETF
    as_of: datetime
    provenance: Provenance
    news_signals: list[dict[str, Any]] = field(default_factory=list)
    run_similarity: bool = True
    similarity_min_samples: int = 30
    # Optional precomputed feature table over the *full* history (backtests). Safe because
    # feature columns are causal and outcome columns are only read for earlier sessions.
    feature_table: pd.DataFrame | None = None


def truncate(data: SymbolData, as_of: datetime) -> SymbolData:
    """Keep minute bars completed by ``as_of`` and daily bars of *previous* sessions, then
    append a synthetic daily bar for the current session built from regular-session minutes."""
    minute = data.minute[data.minute.index + timedelta(minutes=1) <= as_of]
    session = ny_date(as_of)
    daily = data.daily[data.daily.index.date < session]
    if not minute.empty:
        local_dates = minute.index.tz_convert("America/New_York").date
        today = minute[(local_dates == session) & regular_session_mask(minute.index)]
        if not today.empty:
            vol = today["volume"].sum()
            row = pd.DataFrame(
                {
                    "open": [today["open"].iloc[0]],
                    "high": [today["high"].max()],
                    "low": [today["low"].min()],
                    "close": [today["close"].iloc[-1]],
                    "volume": [vol],
                    "vwap": [
                        float((today["vwap"].fillna(today["close"]) * today["volume"]).sum() / vol)
                        if vol > 0
                        else np.nan
                    ],
                    "trade_count": [today["trade_count"].sum()],
                },
                index=pd.DatetimeIndex([pd.Timestamp(session, tz="UTC")], name="ts"),
            )
            daily = pd.concat([daily, row[BAR_COLUMNS]])
    return SymbolData(data.symbol, minute, daily)


def data_quality(minute: pd.DataFrame, daily: pd.DataFrame, as_of: datetime) -> dict[str, Any]:
    issues: list[str] = []
    info: list[str] = []
    if minute.empty:
        return {"ok": False, "issues": ["keine Intraday-Daten"], "info": []}
    last_ts = minute.index[-1]
    phase = market_phase(as_of)
    age_min = (as_of - (last_ts + timedelta(minutes=1)).to_pydatetime()).total_seconds() / 60
    if phase.value == "regular" and age_min > 10:
        issues.append(f"Daten veraltet: letzter Bar vor {age_min:.0f} Min.")
    elif phase.value in ("pre_market", "after_hours") and age_min > 60:
        info.append(f"Letzter Bar vor {age_min:.0f} Min. (außerbörslich, dünner Handel)")
    bad_ohlc = int(
        (
            (minute["low"] > minute[["open", "close"]].min(axis=1) + 1e-9)
            | (minute["high"] < minute[["open", "close"]].max(axis=1) - 1e-9)
        ).sum()
    )
    if bad_ohlc:
        info.append(f"{bad_ohlc} Bars mit inkonsistentem OHLC")
    if not minute.index.is_monotonic_increasing:
        issues.append("Zeitstempel nicht monoton")
    sessions = pd.Index(minute.index.tz_convert("America/New_York").date).unique()
    if len(sessions) < 5:
        issues.append(f"nur {len(sessions)} Intraday-Sessions verfügbar (min. 5)")
    if len(daily) < 60:
        issues.append(f"nur {len(daily)} Tagesbars (min. 60)")
    session = ny_date(as_of)
    today = minute[
        (minute.index.tz_convert("America/New_York").date == session)
        & regular_session_mask(minute.index)
    ]
    missing_pct = None
    if not today.empty:
        span = int((today.index[-1] - today.index[0]).total_seconds() // 60) + 1
        missing_pct = round(100 * (1 - len(today) / span), 1)
        if missing_pct > 30:
            info.append(f"{missing_pct} % Minuten ohne Umsatz (dünner Handel im Feed)")
    return {
        "ok": not issues,
        "issues": issues,
        "info": info,
        "last_bar_ts": last_ts.isoformat(),
        "bars_today": len(today),
        "missing_minutes_pct": missing_pct,
        "age_minutes": round(age_min, 1),
    }


def _last(series: pd.Series) -> float | None:
    s = series.dropna()
    return round(float(s.iloc[-1]), 4) if len(s) else None


def compute_facts(inp: FactInputs) -> dict[str, Any]:
    as_of = inp.as_of
    tgt = truncate(inp.target, as_of)
    mkt = truncate(inp.market, as_of) if inp.market else None
    sec = truncate(inp.sector, as_of) if inp.sector else None
    session = ny_date(as_of)
    phase = market_phase(as_of)

    dq = data_quality(tgt.minute, tgt.daily, as_of)
    facts: dict[str, Any] = {
        "symbol": inp.target.symbol,
        "as_of": as_of.isoformat(),
        "session": session.isoformat(),
        "market_phase": phase.value,
        "provenance": inp.provenance.model_dump(mode="json"),
        "data_quality": dq,
        "price": float(tgt.minute["close"].iloc[-1]) if not tgt.minute.empty else float("nan"),
    }
    if tgt.minute.empty or len(tgt.daily) < 2:
        facts["data_quality"]["ok"] = False
        return facts

    # Intraday indicators/trends use the regular session (RTH) only: thin extended-hours trading
    # distorts ATR, RSI and structure. Extended hours still feed key levels (PM high/low) and price.
    rth_minute = tgt.minute[regular_session_mask(tgt.minute.index)]
    if rth_minute.empty:
        facts["data_quality"]["ok"] = False
        facts["data_quality"]["issues"].append("keine Daten der regulären Handelszeit")
        return facts
    tfs = build_timeframes(rth_minute, tgt.daily)
    facts["trends"] = {
        tf.value: structure.assess_trend(df, tf.value).to_dict()
        for tf, df in tfs.items()
        if tf != Timeframe.M1
    }

    m5 = tfs[Timeframe.M5]
    m15 = tfs[Timeframe.M15]
    price = facts["price"]
    vwap_series = session_vwap(rth_minute)
    rv5 = relative_volume(m5)
    a5 = atr(m5)
    bb = bollinger(m5["close"])
    m15_recent = m15.iloc[-200:]
    swings_15 = [s for s in structure.swing_points(m15_recent) if s.confirmed_at <= m15.index[-1]]
    facts["intraday"] = {
        "vwap": _last(vwap_series),
        "atr_5m": _last(a5),
        "rsi_5m": _last(rsi(m5["close"])),
        "macd_hist_5m": _last(macd(m5["close"])["hist"]),
        "bb_5m": {k: _last(bb[k]) for k in ("upper", "mid", "lower", "pct_b", "width")},
        "rvol_cum": _last(rv5["rvol_cum"]),
        "rvol_bar_5m": _last(rv5["rvol_bar"]),
        "divergence_15m": structure.rsi_divergence(swings_15),
    }
    d = tgt.daily
    d_atr = atr(d)
    facts["daily"] = {
        "atr": _last(d_atr),
        "atr_pct": round(float(d_atr.iloc[-1] / d["close"].iloc[-1] * 100), 3)
        if pd.notna(d_atr.iloc[-1])
        else None,
        "sma50": _last(sma(d["close"], 50)),
        "sma200": _last(sma(d["close"], 200)),
        "change_pct": round(float(price / d["close"].iloc[-2] - 1) * 100, 3)
        if len(d) > 1
        else None,
    }

    kl = structure.key_levels(tgt.minute, tgt.daily, session)
    facts["key_levels"] = kl.to_dict()
    gap = structure.gap_analysis(kl, facts["daily"]["atr"])
    facts["gap"] = gap.__dict__ if gap else None

    h1 = tfs[Timeframe.H1].iloc[-20 * 16 :]  # ~20 sessions incl. extended hours
    swings = {
        "1Hour": [s for s in structure.swing_points(h1) if s.confirmed_at <= h1.index[-1]],
        # Completed sessions only; daily swings need 3 confirming sessions.
        "1Day": structure.swing_points(d.iloc[-260:-1] if len(d) > 1 else d, 3, 3)[-30:],
    }
    daily_atr = facts["daily"]["atr"] or price * 0.02
    tol = daily_atr * 0.35
    zones = [
        z
        for z in structure.cluster_zones(swings, tol, price, max_zones=12)
        if abs(z.mid - price) <= 4 * daily_atr
    ]
    facts["zones"] = [z.to_dict() for z in zones]
    events = structure.detect_level_events(m5, zones, rv5["rvol_bar"])
    facts["level_events"] = [e.__dict__ for e in events]

    rs: dict[str, Any] = {}
    if mkt and not mkt.minute.empty:
        rs["market"] = context.relative_strength(
            mkt.symbol, tgt.minute, tgt.daily, mkt.minute, mkt.daily, session
        ).to_dict()
        mkt_rth = mkt.minute[regular_session_mask(mkt.minute.index)]
        mkt_m5 = build_timeframes(mkt_rth, mkt.daily)[Timeframe.M5]
        facts["market_trend_5m"] = structure.assess_trend(mkt_m5, "5Min").direction
    if sec and not sec.minute.empty:
        rs["sector"] = context.relative_strength(
            sec.symbol, tgt.minute, tgt.daily, sec.minute, sec.daily, session
        ).to_dict()
    facts["relative_strength"] = rs
    facts["volatility"] = context.volatility_regime(d).to_dict()
    facts["liquidity"] = context.liquidity(d, inp.provenance.feed).to_dict()

    if inp.run_similarity:
        table = (
            inp.feature_table[inp.feature_table.index + timedelta(minutes=5) <= as_of]
            if inp.feature_table is not None
            else build_feature_table(tgt.minute, tgt.daily)
        )
        sim = None
        if not table.empty:
            complete = table.index[table.index + timedelta(minutes=5) <= as_of]
            query_ts = complete[-1] if len(complete) else table.index[-1]
            sim = find_analogs(table, query_ts=query_ts, min_samples=inp.similarity_min_samples)
        facts["similarity"] = sim.to_dict() if sim else {"status": "insufficient_history"}
    facts["news_signals"] = inp.news_signals
    return facts
