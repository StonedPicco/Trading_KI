"""Data access helpers. Keep SQL here; services stay storage-agnostic."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AnalysisRow,
    BarCoverage,
    BarRow,
    EventRow,
    LLMUsageRow,
    NewsRow,
    NotificationRow,
    SignalOutcomeRow,
    WatchlistRow,
)
from app.domain.models import BAR_COLUMNS
from app.providers.base import empty_bars


def _insert(session: AsyncSession, table: Any) -> Any:
    dialect = session.get_bind().dialect.name
    return (pg_insert if dialect == "postgresql" else sqlite_insert)(table)


# ---------------------------------------------------------------- bars
async def upsert_bars(
    session: AsyncSession,
    symbol: str,
    timeframe: str,
    feed: str,
    data_kind: str,
    df: pd.DataFrame,
    chunk: int = 2000,
) -> int:
    if df.empty:
        return 0
    now = datetime.now(tz=UTC)
    records = [
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "feed": feed,
            "ts": ts.to_pydatetime(),
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
            "vwap": None if pd.isna(r.vwap) else r.vwap,
            "trade_count": None if pd.isna(r.trade_count) else r.trade_count,
            "data_kind": data_kind,
            "fetched_at": now,
        }
        for ts, r in zip(df.index, df.itertuples(index=False), strict=True)
    ]
    for i in range(0, len(records), chunk):
        stmt = _insert(session, BarRow).values(records[i : i + chunk])
        update_cols = {c: stmt.excluded[c] for c in (*BAR_COLUMNS, "data_kind", "fetched_at")}
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "feed", "ts"], set_=update_cols
        )
        await session.execute(stmt)
    return len(records)


async def load_bars(
    session: AsyncSession,
    symbol: str,
    timeframe: str,
    feed: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    rows = (
        await session.execute(
            select(
                BarRow.ts,
                BarRow.open,
                BarRow.high,
                BarRow.low,
                BarRow.close,
                BarRow.volume,
                BarRow.vwap,
                BarRow.trade_count,
            )
            .where(
                BarRow.symbol == symbol,
                BarRow.timeframe == timeframe,
                BarRow.feed == feed,
                BarRow.ts >= start,
                BarRow.ts < end,
            )
            .order_by(BarRow.ts)
        )
    ).all()
    if not rows:
        return empty_bars()
    df = pd.DataFrame(rows, columns=["ts", *BAR_COLUMNS]).set_index("ts")
    df.index = pd.DatetimeIndex(pd.to_datetime(df.index, utc=True), name="ts")
    return df.astype("float64")


async def get_coverage(
    session: AsyncSession, symbol: str, timeframe: str, feed: str
) -> tuple[datetime, datetime] | None:
    row = await session.get(BarCoverage, (symbol, timeframe, feed))
    return (row.start, row.end) if row else None


async def set_coverage(
    session: AsyncSession, symbol: str, timeframe: str, feed: str, start: datetime, end: datetime
) -> None:
    row = await session.get(BarCoverage, (symbol, timeframe, feed))
    if row is None:
        session.add(
            BarCoverage(symbol=symbol, timeframe=timeframe, feed=feed, start=start, end=end)
        )
    else:
        row.start, row.end = min(row.start, start), max(row.end, end)


# ---------------------------------------------------------------- watchlist
async def list_watchlist(session: AsyncSession) -> list[WatchlistRow]:
    return list(
        (await session.execute(select(WatchlistRow).order_by(WatchlistRow.added_at))).scalars()
    )


async def add_watchlist(session: AsyncSession, symbol: str, sector_etf: str | None) -> WatchlistRow:
    row = await session.get(WatchlistRow, symbol)
    if row is None:
        row = WatchlistRow(symbol=symbol, sector_etf=sector_etf, added_at=datetime.now(tz=UTC))
        session.add(row)
    elif sector_etf:
        row.sector_etf = sector_etf
    return row


async def remove_watchlist(session: AsyncSession, symbol: str) -> bool:
    row = await session.get(WatchlistRow, symbol)
    if row is None:
        return False
    await session.delete(row)
    return True


# ---------------------------------------------------------------- analyses
async def insert_analysis(session: AsyncSession, row: AnalysisRow) -> AnalysisRow:
    session.add(row)
    await session.flush()
    return row


async def latest_analysis(session: AsyncSession, symbol: str) -> AnalysisRow | None:
    return (
        await session.execute(
            select(AnalysisRow)
            .where(AnalysisRow.symbol == symbol)
            .order_by(AnalysisRow.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def list_analyses(
    session: AsyncSession, symbol: str | None = None, limit: int = 50
) -> list[AnalysisRow]:
    q = select(AnalysisRow).order_by(AnalysisRow.created_at.desc()).limit(limit)
    if symbol:
        q = q.where(AnalysisRow.symbol == symbol)
    return list((await session.execute(q)).scalars())


async def get_analysis(session: AsyncSession, analysis_id: uuid.UUID) -> AnalysisRow | None:
    return await session.get(AnalysisRow, analysis_id)


async def outcomes_for(
    session: AsyncSession, ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[SignalOutcomeRow]]:
    if not ids:
        return {}
    rows = (
        await session.execute(select(SignalOutcomeRow).where(SignalOutcomeRow.analysis_id.in_(ids)))
    ).scalars()
    out: dict[uuid.UUID, list[SignalOutcomeRow]] = {}
    for r in rows:
        out.setdefault(r.analysis_id, []).append(r)
    return out


async def analyses_pending_evaluation(
    session: AsyncSession, horizon_min: int, older_than: datetime, limit: int = 200
) -> list[AnalysisRow]:
    evaluated = select(SignalOutcomeRow.analysis_id).where(
        SignalOutcomeRow.horizon_min == horizon_min
    )
    q = (
        select(AnalysisRow)
        .where(AnalysisRow.created_at <= older_than, AnalysisRow.id.not_in(evaluated))
        .order_by(AnalysisRow.created_at)
        .limit(limit)
    )
    return list((await session.execute(q)).scalars())


async def insert_outcome(session: AsyncSession, row: SignalOutcomeRow) -> None:
    stmt = (
        _insert(session, SignalOutcomeRow)
        .values(
            analysis_id=row.analysis_id,
            horizon_min=row.horizon_min,
            evaluated_at=row.evaluated_at,
            ret_pct=row.ret_pct,
            mfe_pct=row.mfe_pct,
            mae_pct=row.mae_pct,
            result=row.result,
            r_multiple=row.r_multiple,
            details=row.details or {},
        )
        .on_conflict_do_nothing(index_elements=["analysis_id", "horizon_min"])
    )
    await session.execute(stmt)


# ---------------------------------------------------------------- news
async def upsert_news(session: AsyncSession, row: NewsRow) -> bool:
    """Insert if new. Returns True when the item was not stored before."""
    existing = await session.get(NewsRow, row.id)
    if existing is not None:
        return False
    session.add(row)
    await session.flush()
    return True


async def news_by_hash(session: AsyncSession, content_hash: str) -> NewsRow | None:
    return (
        await session.execute(
            select(NewsRow)
            .where(NewsRow.content_hash == content_hash, NewsRow.duplicate_of.is_(None))
            .limit(1)
        )
    ).scalar_one_or_none()


async def recent_news(
    session: AsyncSession, symbol: str | None, since: datetime, limit: int = 50
) -> list[NewsRow]:
    q = select(NewsRow).where(NewsRow.published_at >= since).order_by(NewsRow.published_at.desc())
    rows = list((await session.execute(q.limit(limit * 4 if symbol else limit))).scalars())
    if symbol:
        rows = [r for r in rows if symbol in (r.symbols or [])][:limit]
    return rows


# ---------------------------------------------------------------- events / notifications
async def add_event(
    session: AsyncSession, type_: str, payload: dict[str, Any], symbol: str | None = None
) -> None:
    session.add(
        EventRow(type=type_, symbol=symbol, payload=payload, created_at=datetime.now(tz=UTC))
    )


async def events_after(session: AsyncSession, last_id: int, limit: int = 100) -> list[EventRow]:
    q = select(EventRow).where(EventRow.id > last_id).order_by(EventRow.id).limit(limit)
    return list((await session.execute(q)).scalars())


async def max_event_id(session: AsyncSession) -> int:
    return int((await session.execute(select(func.max(EventRow.id)))).scalar() or 0)


async def insert_notification(session: AsyncSession, row: NotificationRow) -> bool:
    """Insert unless the dedupe_key exists. Returns True if inserted."""
    stmt = (
        _insert(session, NotificationRow)
        .values(
            dedupe_key=row.dedupe_key,
            symbol=row.symbol,
            kind=row.kind,
            severity=row.severity,
            title=row.title,
            body=row.body,
            payload=row.payload or {},
            created_at=row.created_at,
            read=False,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )
    result = await session.execute(stmt)
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def list_notifications(
    session: AsyncSession, unread_only: bool = False, limit: int = 50
) -> list[NotificationRow]:
    q = select(NotificationRow).order_by(NotificationRow.created_at.desc()).limit(limit)
    if unread_only:
        q = q.where(NotificationRow.read.is_(False))
    return list((await session.execute(q)).scalars())


async def mark_notification_read(session: AsyncSession, notification_id: int) -> bool:
    row = await session.get(NotificationRow, notification_id)
    if row is None:
        return False
    row.read = True
    return True


# ---------------------------------------------------------------- llm usage
async def llm_cost_on(session: AsyncSession, day: date) -> float:
    return float(
        (
            await session.execute(
                select(func.coalesce(func.sum(LLMUsageRow.cost_usd), 0.0)).where(
                    LLMUsageRow.day == day
                )
            )
        ).scalar()
        or 0.0
    )


async def llm_cached(session: AsyncSession, cache_key: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            select(LLMUsageRow)
            .where(LLMUsageRow.cache_key == cache_key)
            .order_by(LLMUsageRow.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row.response if row else None


async def record_llm_usage(session: AsyncSession, row: LLMUsageRow) -> None:
    session.add(row)
