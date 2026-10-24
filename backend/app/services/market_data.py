"""Market data access with a two-level cache (process memory + PostgreSQL).

* Cold start: load from DB, fetch what's missing from the provider, upsert into DB.
* Refresh: fetch the tail with a small overlap (last bars may be revised), upsert.
* Demo data is never persisted (it is regenerated deterministically on demand).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pandas as pd

from app.core.market_time import trading_days_back, utcnow
from app.db import repositories as repo
from app.db.session import Database
from app.domain.models import Provenance, Timeframe
from app.providers.base import MarketDataProvider, empty_bars

log = logging.getLogger(__name__)

TAIL_OVERLAP = {Timeframe.M1: timedelta(minutes=5), Timeframe.D1: timedelta(days=3)}


@dataclass
class Series:
    df: pd.DataFrame
    start: datetime
    end: datetime  # fetched up to (exclusive)
    refreshed_at: datetime


class MarketDataService:
    def __init__(
        self, provider: MarketDataProvider, db: Database, intraday_days: int, daily_days: int
    ) -> None:
        self.provider = provider
        self.db = db
        self.intraday_days = intraday_days
        self.daily_days = daily_days
        self.persist = provider.name != "demo"
        self._cache: dict[tuple[str, Timeframe], Series] = {}
        self._locks: dict[tuple[str, Timeframe], asyncio.Lock] = {}

    @property
    def feed(self) -> str:
        return self.provider.feed

    def provenance(self, as_of: datetime | None = None) -> Provenance:
        return self.provider.provenance(Timeframe.M1, as_of)

    def _default_start(self, tf: Timeframe, now: datetime) -> datetime:
        days = self.intraday_days if tf == Timeframe.M1 else self.daily_days
        if tf == Timeframe.M1:
            first = trading_days_back(now.date(), days)
            return datetime.combine(first, datetime.min.time(), tzinfo=UTC)
        return now - timedelta(days=days)

    async def get(
        self,
        symbol: str,
        tf: Timeframe,
        now: datetime | None = None,
        max_age_s: float = 30.0,
        intraday_days: int | None = None,
    ) -> pd.DataFrame:
        """Bars from the default lookback (or ``intraday_days``) up to now, refreshed if stale."""
        symbol = symbol.upper()
        now = now or utcnow()
        key = (symbol, tf)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            start = self._default_start(tf, now)
            if intraday_days and tf == Timeframe.M1:
                first = trading_days_back(now.date(), intraday_days)
                start = datetime.combine(first, datetime.min.time(), tzinfo=UTC)
            series = self._cache.get(key)
            if series is None or series.start > start:
                series = await self._cold_load(symbol, tf, start, now)
                self._cache[key] = series
            elif (now - series.refreshed_at).total_seconds() > max_age_s:
                await self._refresh_tail(symbol, tf, series, now)
            return series.df[series.df.index >= start]

    async def _cold_load(
        self, symbol: str, tf: Timeframe, start: datetime, now: datetime
    ) -> Series:
        df = empty_bars()
        fetch_from = start
        if self.persist:
            async with self.db.session() as s:
                cov = await repo.get_coverage(s, symbol, tf.value, self.feed)
                if cov and cov[0] <= start:
                    df = await repo.load_bars(s, symbol, tf.value, self.feed, start, now)
                    fetch_from = max(start, cov[1] - TAIL_OVERLAP[tf])
        fresh = await self.provider.get_bars(symbol, tf, fetch_from, now)
        if not fresh.empty:
            df = pd.concat([df[df.index < fresh.index[0]], fresh])
            df = df[~df.index.duplicated(keep="last")].sort_index()
        await self._persist(symbol, tf, fresh, start, now)
        log.info(
            "bars loaded",
            extra={"symbol": symbol, "tf": tf.value, "rows": len(df), "fetched": len(fresh)},
        )
        return Series(df=df, start=start, end=now, refreshed_at=now)

    async def _refresh_tail(
        self, symbol: str, tf: Timeframe, series: Series, now: datetime
    ) -> None:
        since = series.end - TAIL_OVERLAP[tf]
        fresh = await self.provider.get_bars(symbol, tf, since, now)
        if not fresh.empty:
            df = pd.concat([series.df[series.df.index < fresh.index[0]], fresh])
            series.df = df[~df.index.duplicated(keep="last")].sort_index()
        await self._persist(symbol, tf, fresh, since, now)
        series.end = now
        series.refreshed_at = now

    async def _persist(
        self, symbol: str, tf: Timeframe, df: pd.DataFrame, start: datetime, end: datetime
    ) -> None:
        if not self.persist:
            return
        kind = self.provider.provenance(tf).data_kind.value
        async with self.db.session() as s:
            await repo.upsert_bars(s, symbol, tf.value, self.feed, kind, df)
            await repo.set_coverage(s, symbol, tf.value, self.feed, start, end)

    def ingest_stream_bar(self, symbol: str, row: pd.DataFrame) -> None:
        """Merge a streamed 1-minute bar into the in-memory series (persisted on next refresh)."""
        series = self._cache.get((symbol.upper(), Timeframe.M1))
        if series is None:
            return
        df = pd.concat([series.df, row])
        series.df = df[~df.index.duplicated(keep="last")].sort_index()
