"""MarketDataService caching/persistence with a fake (non-demo) provider.

Runs on SQLite by default; set TEST_DATABASE_URL=postgresql+asyncpg://... to also exercise
PostgreSQL (CI does this).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from app.db.models import Base
from app.db.session import Database
from app.domain.models import DataKind, Provenance, Timeframe
from app.services.market_data import MarketDataService
from tests.conftest import regular_session_frame

NOW = datetime(2026, 10, 22, 17, 45, tzinfo=UTC)


class FakeProvider:
    name = "fake"
    feed = "iex"

    def __init__(self) -> None:
        self.minute = regular_session_frame(30, datetime(2026, 10, 22, 20, 0, tzinfo=UTC))
        self.calls: list[tuple[str, datetime, datetime]] = []

    def provenance(self, timeframe: Timeframe, as_of: datetime | None = None) -> Provenance:
        return Provenance(
            provider="fake", feed="iex", data_kind=DataKind.LIVE, is_realtime=True, as_of=as_of
        )

    async def get_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame:
        self.calls.append((timeframe.value, start, end))
        df = self.minute
        return df[(df.index >= start) & (df.index < end)]

    async def aclose(self) -> None:
        return None


@pytest.fixture(params=["sqlite", "postgres"])
async def db(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Database]:
    if request.param == "sqlite":
        database = Database(f"sqlite+aiosqlite:///{tmp_path / 'md.db'}")
    else:
        url = os.environ.get("TEST_DATABASE_URL")
        if not url:
            pytest.skip("TEST_DATABASE_URL not set")
        database = Database(url)
        async with database.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    await database.create_all()
    yield database
    await database.dispose()


async def test_cold_load_persists_and_second_instance_fetches_only_tail(db: Database) -> None:
    provider = FakeProvider()
    svc = MarketDataService(provider, db, intraday_days=10, daily_days=30)  # type: ignore[arg-type]
    df = await svc.get("TEST", Timeframe.M1, NOW)
    assert not df.empty and df.index[-1] < NOW
    assert len(provider.calls) == 1

    # within max_age: served from memory, no provider call
    await svc.get("TEST", Timeframe.M1, NOW + timedelta(seconds=5))
    assert len(provider.calls) == 1

    # stale: tail refresh with overlap
    later = NOW + timedelta(minutes=3)
    await svc.get("TEST", Timeframe.M1, later)
    assert len(provider.calls) == 2
    _, start, end = provider.calls[-1]
    assert start == NOW - timedelta(minutes=5) and end == later

    # new process: loads from DB and only fetches from the stored coverage end
    provider2 = FakeProvider()
    svc2 = MarketDataService(provider2, db, intraday_days=10, daily_days=30)  # type: ignore[arg-type]
    df2 = await svc2.get("TEST", Timeframe.M1, later)
    assert len(provider2.calls) == 1
    assert provider2.calls[0][1] == later - timedelta(minutes=5)
    src = provider2.minute
    expected = src[(src.index >= df2.index[0]) & (src.index < later)]
    pd.testing.assert_frame_equal(df2, expected, check_freq=False)
