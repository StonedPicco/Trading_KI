"""SQLAlchemy ORM models. Schema changes go through Alembic migrations (backend/alembic)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    Uuid,
    event,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes on every backend (SQLite stores naive values)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime not allowed")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


# BIGINT autoincrement does not work on SQLite; use INTEGER there.
AutoId = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy API
        dict[str, Any]: JSON,
        list[Any]: JSON,
        datetime: UTCDateTime,
    }


class BarRow(Base):
    __tablename__ = "bars"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    feed: Mapped[str] = mapped_column(String(8), primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    vwap: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_count: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_kind: Mapped[str] = mapped_column(String(12))
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime)


class BarCoverage(Base):
    """Which [start, end) ranges have been fetched per series – avoids refetching empty spans."""

    __tablename__ = "bar_coverage"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    feed: Mapped[str] = mapped_column(String(8), primary_key=True)
    start: Mapped[datetime] = mapped_column(UTCDateTime)
    end: Mapped[datetime] = mapped_column(UTCDateTime)


class WatchlistRow(Base):
    __tablename__ = "watchlist"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    sector_etf: Mapped[str | None] = mapped_column(String(8), nullable=True)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AnalysisRow(Base):
    """Immutable record of a live analysis. Never updated or deleted (DB trigger + ORM guard)."""

    __tablename__ = "analyses"
    __table_args__ = (Index("ix_analyses_symbol_created", "symbol", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    data_as_of: Mapped[datetime] = mapped_column(UTCDateTime)
    trigger: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32))
    bias: Mapped[str] = mapped_column(String(8))
    reference_price: Mapped[float] = mapped_column(Float)
    market_phase: Mapped[str] = mapped_column(String(16))
    data_kind: Mapped[str] = mapped_column(String(12))
    scenario: Mapped[dict[str, Any]] = mapped_column(JSON)
    facts: Mapped[dict[str, Any]] = mapped_column(JSON)
    narrative: Mapped[dict[str, Any]] = mapped_column(JSON)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON)
    sources: Mapped[list[Any]] = mapped_column(JSON)
    input_hash: Mapped[str] = mapped_column(String(64))
    engine_version: Mapped[str] = mapped_column(String(16))
    llm_model: Mapped[str | None] = mapped_column(String(64), nullable=True)


@event.listens_for(AnalysisRow, "before_update")
def _forbid_update(*_: Any) -> None:
    raise RuntimeError("analyses are immutable")


@event.listens_for(AnalysisRow, "before_delete")
def _forbid_delete(*_: Any) -> None:
    raise RuntimeError("analyses are immutable")


class SignalOutcomeRow(Base):
    __tablename__ = "signal_outcomes"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("analyses.id"), primary_key=True
    )
    horizon_min: Mapped[int] = mapped_column(Integer, primary_key=True)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ret_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mfe_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    result: Mapped[str] = mapped_column(String(16))  # target|stop|open|not_triggered|n_a
    r_multiple: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class NewsRow(Base):
    __tablename__ = "news_items"
    __table_args__ = (Index("ix_news_published", "published_at"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
    headline: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    symbols: Mapped[list[Any]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    duplicate_of: Mapped[str | None] = mapped_column(String(96), nullable=True)
    reaction: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    assessment: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class EventRow(Base):
    """Outbox: worker writes, API tails and pushes over WebSocket."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(AutoId, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(32))
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class NotificationRow(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(AutoId, primary_key=True, autoincrement=True)
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(8))  # info|warn|alert
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class LLMUsageRow(Base):
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(AutoId, primary_key=True, autoincrement=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    model: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(32))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Float)
    cache_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
