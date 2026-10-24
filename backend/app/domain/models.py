"""Core domain types shared across providers, analysis, persistence and API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Timeframe(StrEnum):
    M1 = "1Min"
    M5 = "5Min"
    M15 = "15Min"
    H1 = "1Hour"
    D1 = "1Day"
    W1 = "1Week"

    @property
    def minutes(self) -> int:
        return {"1Min": 1, "5Min": 5, "15Min": 15, "1Hour": 60, "1Day": 1440, "1Week": 10080}[
            self.value
        ]

    @property
    def is_intraday(self) -> bool:
        return self.minutes < 1440


class DataKind(StrEnum):
    """Distinguishes real from simulated data. Never mix kinds in one computation."""

    LIVE = "live"  # real-time market data
    DELAYED = "delayed"  # real data, delayed by provider/licence
    HISTORICAL = "historical"  # real data, loaded from historical endpoints
    DEMO = "demo"  # synthetic, generated locally – NOT market data


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    feed: str
    data_kind: DataKind
    is_realtime: bool
    delay_minutes: int = 0
    as_of: datetime | None = None
    notes: list[str] = Field(default_factory=list)

    @property
    def is_demo(self) -> bool:
        return self.data_kind == DataKind.DEMO


class Bar(BaseModel):
    model_config = ConfigDict(frozen=True)

    ts: datetime  # bar start, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    trade_count: int | None = None


class NewsItem(BaseModel):
    id: str  # "<provider>:<provider_id>"
    provider: str
    source: str | None = None
    published_at: datetime
    updated_at: datetime | None = None
    headline: str
    summary: str | None = None
    content: str | None = None
    url: str | None = None
    symbols: list[str] = Field(default_factory=list)
    kind: str = "news"  # news | filing


BAR_COLUMNS = ["open", "high", "low", "close", "volume", "vwap", "trade_count"]
