"""Provider interfaces. Implementations: alpaca.py, demo.py, sec_edgar.py."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol, runtime_checkable

import pandas as pd

from app.domain.models import BAR_COLUMNS, Bar, NewsItem, Provenance, Timeframe

# Provider-native timeframes. Everything else is resampled locally (analysis.multitimeframe).
NATIVE_TIMEFRAMES = (Timeframe.M1, Timeframe.D1)


@runtime_checkable
class MarketDataProvider(Protocol):
    name: str
    feed: str

    def provenance(self, timeframe: Timeframe, as_of: datetime | None = None) -> Provenance: ...

    async def get_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Return OHLCV bars in [start, end) indexed by UTC bar-start timestamp.

        Prices must be split/dividend adjusted. Intraday bars include extended hours.
        """
        ...

    async def aclose(self) -> None: ...


@runtime_checkable
class NewsProvider(Protocol):
    name: str

    async def get_news(
        self, symbols: list[str], start: datetime, end: datetime, limit: int = 50
    ) -> list[NewsItem]: ...

    async def aclose(self) -> None: ...


def empty_bars() -> pd.DataFrame:
    df = pd.DataFrame(columns=BAR_COLUMNS, dtype="float64")
    df.index = pd.DatetimeIndex([], tz="UTC", name="ts")
    return df


def bars_to_frame(bars: Iterable[Bar]) -> pd.DataFrame:
    rows = [b.model_dump() for b in bars]
    if not rows:
        return empty_bars()
    df = pd.DataFrame(rows).set_index("ts")
    df.index = pd.DatetimeIndex(pd.to_datetime(df.index, utc=True), name="ts")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    for col in BAR_COLUMNS:
        if col not in df:
            df[col] = float("nan")
    return df[BAR_COLUMNS].astype("float64")
