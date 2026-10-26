"""REST API."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.analysis.context import DEFAULT_SECTOR
from app.analysis.indicators import bollinger, ema, macd, relative_volume, rsi, session_vwap
from app.analysis.multitimeframe import resample_daily, resample_intraday
from app.container import Container
from app.core.jsonsafe import to_jsonable
from app.core.market_time import market_phase, ny_date, trading_days_back, utcnow
from app.db import repositories as repo
from app.db.models import AnalysisRow
from app.domain.models import Timeframe
from app.news.service import news_signal
from app.services.evaluation import performance_summary
from app.services.watchlist import normalize_symbol, validate_sector

router = APIRouter(prefix="/api")


def container(request: Request) -> Container:
    return request.app.state.container


def symbol_param(symbol: str) -> str:
    try:
        return normalize_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


# ------------------------------------------------------------------ health
@router.get("/health")
async def health(c: Container = Depends(container)) -> dict[str, Any]:
    prov = c.market.provenance(utcnow())
    return {
        "status": "ok",
        "env": c.settings.app_env,
        "market_phase": market_phase(utcnow()).value,
        "provenance": to_jsonable(prov),
        "demo_mode": prov.is_demo,
        "llm": {"enabled": c.llm is not None, "model": c.llm.model if c.llm else None},
        "news_providers": [p.name for p in c.news.providers],
        "order_execution": "disabled – analysis only",
    }


# ------------------------------------------------------------------ watchlist
class WatchlistIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)
    sector_etf: str | None = None


@router.get("/watchlist")
async def get_watchlist(c: Container = Depends(container)) -> list[dict[str, Any]]:
    async with c.db.session() as s:
        rows = await repo.list_watchlist(s)
    return [{"symbol": r.symbol, "sector_etf": r.sector_etf, "added_at": r.added_at} for r in rows]


@router.post("/watchlist", status_code=201)
async def add_watchlist(body: WatchlistIn, c: Container = Depends(container)) -> dict[str, Any]:
    try:
        sym = normalize_symbol(body.symbol)
        sector = validate_sector(body.sector_etf)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    async with c.db.session() as s:
        row = await repo.add_watchlist(s, sym, sector or DEFAULT_SECTOR.get(sym))
        return {"symbol": row.symbol, "sector_etf": row.sector_etf}


@router.delete("/watchlist/{symbol}", status_code=204)
async def delete_watchlist(
    symbol: str = Depends(symbol_param), c: Container = Depends(container)
) -> None:
    async with c.db.session() as s:
        if not await repo.remove_watchlist(s, symbol):
            raise HTTPException(404, "not in watchlist")


@router.get("/watchlist/overview")
async def watchlist_overview(c: Container = Depends(container)) -> list[dict[str, Any]]:
    now = utcnow()
    async with c.db.session() as s:
        rows = await repo.list_watchlist(s)
    out = []
    for w in rows:
        item: dict[str, Any] = {"symbol": w.symbol, "sector_etf": w.sector_etf}
        try:
            minute = await c.market.get(w.symbol, Timeframe.M1, now, intraday_days=25)
            daily = await c.market.get(w.symbol, Timeframe.D1, now)
        except Exception as exc:
            item["error"] = str(exc)
            out.append(item)
            continue
        if not minute.empty:
            last = float(minute["close"].iloc[-1])
            # Reference session = session of the latest bar (weekends/holidays: last session).
            session = ny_date(minute.index[-1].to_pydatetime())
            prev = daily[daily.index.date < session]
            prev_close = float(prev["close"].iloc[-1]) if not prev.empty else None
            local = minute.index.tz_convert("America/New_York").date
            today = minute[local == session]
            rv = relative_volume(minute.iloc[-390 * 22 :])["rvol_cum"].dropna()
            item.update(
                {
                    "price": last,
                    "prev_close": prev_close,
                    "change_pct": round((last / prev_close - 1) * 100, 3) if prev_close else None,
                    "session": session.isoformat(),
                    "volume_today": float(today["volume"].sum()) if not today.empty else 0.0,
                    "rvol": round(float(rv.iloc[-1]), 2) if len(rv) else None,
                    "last_bar": minute.index[-1].isoformat(),
                }
            )
        async with c.db.session() as s:
            a = await repo.latest_analysis(s, w.symbol)
            news = await repo.recent_news(s, w.symbol, now - timedelta(hours=24), 20)
        item["news_24h"] = len([n for n in news if n.duplicate_of is None])
        if a:
            item["signal"] = {
                "id": str(a.id),
                "outcome": a.outcome,
                "label": a.scenario.get("label"),
                "created_at": a.created_at,
                "data_kind": a.data_kind,
            }
        out.append(to_jsonable(item))
    return out


# ------------------------------------------------------------------ bars & indicators
async def _bars(c: Container, symbol: str, tf: Timeframe, days: int) -> tuple[pd.DataFrame, Any]:
    now = utcnow()
    if tf.is_intraday:
        minute = await c.market.get(symbol, Timeframe.M1, now, intraday_days=max(days + 3, 25))
        df = resample_intraday(minute, tf)
        start = pd.Timestamp(trading_days_back(now.date(), days), tz="UTC")
        return df, start
    daily = await c.market.get(symbol, Timeframe.D1, now)
    df = resample_daily(daily, tf)
    return df, df.index[0] if len(df) else None


def _series(s: pd.Series, start: Any, keep_gaps: bool = False) -> list[dict[str, Any]]:
    """Chart points from ``start``. With ``keep_gaps`` NaNs become ``value: null`` so the chart
    can break the line (e.g. session-anchored VWAP between sessions)."""
    s = s[s.index >= start]
    if not keep_gaps:
        s = s.dropna()
    return [
        {"time": int(ts.timestamp()), "value": None if pd.isna(v) else round(float(v), 4)}
        for ts, v in s.items()
    ]


@router.get("/symbols/{symbol}/bars")
async def get_bars(
    symbol: str = Depends(symbol_param),
    tf: Timeframe = Timeframe.M5,
    days: int = Query(5, ge=1, le=250),
    c: Container = Depends(container),
) -> dict[str, Any]:
    df, start = await _bars(c, symbol, tf, days)
    view = df[df.index >= start] if start is not None else df
    return {
        "symbol": symbol,
        "timeframe": tf.value,
        "provenance": to_jsonable(c.market.provenance()),
        "bars": [
            {
                "time": int(ts.timestamp()),
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for ts, r in zip(view.index, view.itertuples(index=False), strict=True)
        ],
    }


@router.get("/symbols/{symbol}/indicators")
async def get_indicators(
    symbol: str = Depends(symbol_param),
    tf: Timeframe = Timeframe.M5,
    days: int = Query(5, ge=1, le=250),
    c: Container = Depends(container),
) -> dict[str, Any]:
    df, start = await _bars(c, symbol, tf, days)
    if df.empty:
        return {"symbol": symbol, "timeframe": tf.value, "series": {}}
    bb = bollinger(df["close"])
    m = macd(df["close"])
    series = {
        "ema20": _series(ema(df["close"], 20), start),
        "ema50": _series(ema(df["close"], 50), start),
        "bb_upper": _series(bb["upper"], start),
        "bb_lower": _series(bb["lower"], start),
        "rsi14": _series(rsi(df["close"]), start),
        "macd": _series(m["macd"], start),
        "macd_signal": _series(m["signal"], start),
        "macd_hist": _series(m["hist"], start),
    }
    if tf.is_intraday:
        series["vwap"] = _series(session_vwap(df), start, keep_gaps=True)
    return {"symbol": symbol, "timeframe": tf.value, "series": series}


# ------------------------------------------------------------------ analyses
def _analysis_out(
    a: AnalysisRow, outcomes: list[Any] | None = None, full: bool = True
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": str(a.id),
        "symbol": a.symbol,
        "created_at": a.created_at,
        "data_as_of": a.data_as_of,
        "trigger": a.trigger,
        "outcome": a.outcome,
        "bias": a.bias,
        "reference_price": a.reference_price,
        "market_phase": a.market_phase,
        "data_kind": a.data_kind,
        "scenario": a.scenario,
        "narrative": a.narrative,
        "provenance": a.provenance,
        "sources": a.sources,
        "input_hash": a.input_hash,
        "engine_version": a.engine_version,
        "llm_model": a.llm_model,
    }
    if full:
        d["facts"] = a.facts
    if outcomes is not None:
        d["outcomes"] = [
            {
                "horizon_min": o.horizon_min,
                "ret_pct": o.ret_pct,
                "mfe_pct": o.mfe_pct,
                "mae_pct": o.mae_pct,
                "result": o.result,
                "r_multiple": o.r_multiple,
                "evaluated_at": o.evaluated_at,
            }
            for o in sorted(outcomes, key=lambda o: o.horizon_min)
        ]
    return to_jsonable(d)


@router.post("/symbols/{symbol}/analyze")
async def analyze(
    symbol: str = Depends(symbol_param), c: Container = Depends(container)
) -> dict[str, Any]:
    # Analyses cost seconds of CPU: repeated clicks within 10 s return the fresh result.
    async with c.db.session() as s:
        recent = await repo.latest_analysis(s, symbol)
    if recent is not None and (utcnow() - recent.created_at).total_seconds() < 10:
        return _analysis_out(recent)
    row = await c.analysis.analyze(symbol, trigger="manual")
    return _analysis_out(row)


@router.get("/symbols/{symbol}/analyses/latest")
async def latest(
    symbol: str = Depends(symbol_param), c: Container = Depends(container)
) -> dict[str, Any]:
    async with c.db.session() as s:
        row = await repo.latest_analysis(s, symbol)
    if row is None:
        raise HTTPException(404, "noch keine Analyse")
    return _analysis_out(row)


@router.get("/analyses")
async def list_analyses(
    symbol: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    c: Container = Depends(container),
) -> list[dict[str, Any]]:
    sym = normalize_symbol(symbol) if symbol else None
    async with c.db.session() as s:
        rows = await repo.list_analyses(s, sym, limit)
        outs = await repo.outcomes_for(s, [r.id for r in rows])
    return [_analysis_out(r, outs.get(r.id, []), full=False) for r in rows]


@router.get("/analyses/{analysis_id}")
async def get_analysis(analysis_id: uuid.UUID, c: Container = Depends(container)) -> dict[str, Any]:
    async with c.db.session() as s:
        row = await repo.get_analysis(s, analysis_id)
        if row is None:
            raise HTTPException(404, "not found")
        outs = await repo.outcomes_for(s, [row.id])
    return _analysis_out(row, outs.get(row.id, []))


@router.get("/symbols/{symbol}/similar")
async def similar(
    symbol: str = Depends(symbol_param), c: Container = Depends(container)
) -> dict[str, Any]:
    async with c.db.session() as s:
        row = await repo.latest_analysis(s, symbol)
    if row is None:
        raise HTTPException(404, "noch keine Analyse – zuerst analysieren")
    return to_jsonable(
        {
            "analysis_id": str(row.id),
            "created_at": row.created_at,
            "data_kind": row.data_kind,
            "similarity": row.facts.get("similarity"),
        }
    )


@router.get("/symbols/{symbol}/news")
async def news(
    symbol: str = Depends(symbol_param),
    hours: int = Query(72, ge=1, le=720),
    c: Container = Depends(container),
) -> dict[str, Any]:
    rows = await c.news.recent(symbol, hours=hours, limit=50)
    return {
        "symbol": symbol,
        "enabled": c.news.enabled,
        "providers": [p.name for p in c.news.providers],
        "items": to_jsonable(
            [
                {
                    **news_signal(r),
                    "assessment": r.assessment,
                    "symbols": r.symbols,
                    "first_seen_at": r.first_seen_at,
                    "duplicate_of": r.duplicate_of,
                }
                for r in rows
            ]
        ),
    }


@router.get("/performance")
async def performance(
    horizon: int = Query(60), symbol: str | None = None, c: Container = Depends(container)
) -> dict[str, Any]:
    if horizon not in (15, 60, 240):
        raise HTTPException(422, "horizon must be 15, 60 or 240")
    async with c.db.session() as s:
        rows = await repo.list_analyses(s, normalize_symbol(symbol) if symbol else None, 2000)
        outs = await repo.outcomes_for(s, [r.id for r in rows])
    return to_jsonable(performance_summary(rows, outs, horizon, c.settings.calibration_min_samples))


# ------------------------------------------------------------------ notifications
@router.get("/notifications")
async def notifications(
    unread_only: bool = False, limit: int = Query(50, le=200), c: Container = Depends(container)
) -> list[dict[str, Any]]:
    async with c.db.session() as s:
        rows = await repo.list_notifications(s, unread_only, limit)
    return to_jsonable(
        [
            {
                "id": r.id,
                "symbol": r.symbol,
                "kind": r.kind,
                "severity": r.severity,
                "title": r.title,
                "body": r.body,
                "payload": r.payload,
                "created_at": r.created_at,
                "read": r.read,
            }
            for r in rows
        ]
    )


@router.post("/notifications/{notification_id}/read", status_code=204)
async def mark_read(notification_id: int, c: Container = Depends(container)) -> None:
    async with c.db.session() as s:
        if not await repo.mark_notification_read(s, notification_id):
            raise HTTPException(404, "not found")
