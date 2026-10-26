from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from asgi_lifespan import LifespanManager
from pydantic import SecretStr

from app.container import build_container
from app.core.config import Settings
from app.db.models import AnalysisRow
from app.main import create_app
from app.notifications.dispatcher import Notification
from app.providers.demo import DemoMarketData


def _settings(tmp_path: Path, **kw: object) -> Settings:
    return Settings(
        app_env="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        data_provider="demo",
        similarity_lookback_days=40,
        intraday_lookback_days=25,
        daily_lookback_days=400,
        default_watchlist=["AAPL"],
        **kw,  # type: ignore[arg-type]
    )


@pytest.fixture
async def client(tmp_path: Path, fixed_clock: datetime) -> AsyncIterator[httpx.AsyncClient]:
    settings = _settings(tmp_path)
    container = build_container(settings, provider=DemoMarketData())
    app = create_app(settings, container)
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        c.app = app  # type: ignore[attr-defined]
        yield c


async def test_health_reports_demo_mode(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/health")
    body = r.json()
    assert body["demo_mode"] is True
    assert body["provenance"]["data_kind"] == "demo"
    assert "disabled" in body["order_execution"]


async def test_watchlist_crud_and_validation(client: httpx.AsyncClient) -> None:
    assert [w["symbol"] for w in (await client.get("/api/watchlist")).json()] == ["AAPL"]
    r = await client.post("/api/watchlist", json={"symbol": "msft"})
    assert r.status_code == 201 and r.json() == {"symbol": "MSFT", "sector_etf": "XLK"}
    assert (await client.post("/api/watchlist", json={"symbol": "bad sym!"})).status_code == 422
    assert (await client.delete("/api/watchlist/MSFT")).status_code == 204
    assert (await client.delete("/api/watchlist/MSFT")).status_code == 404


async def test_bars_and_indicators(client: httpx.AsyncClient) -> None:
    r = (await client.get("/api/symbols/AAPL/bars", params={"tf": "15Min", "days": 3})).json()
    assert r["provenance"]["data_kind"] == "demo"
    times = [b["time"] for b in r["bars"]]
    assert times == sorted(times) and len(times) > 20
    ind = (await client.get("/api/symbols/AAPL/indicators", params={"tf": "5Min"})).json()
    assert {"ema20", "vwap", "rsi14", "macd_hist"} <= set(ind["series"])
    daily = (await client.get("/api/symbols/AAPL/bars", params={"tf": "1Day"})).json()
    assert len(daily["bars"]) > 100


async def test_full_analysis_is_stored_immutably(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/symbols/AAPL/analyze")
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["data_kind"] == "demo"
    assert a["outcome"] in {
        "bullish_setup",
        "bearish_setup",
        "long_entry",
        "short_entry",
        "watch",
        "no_trade",
        "insufficient_data",
        "invalidated",
    }
    assert a["narrative"]["meta"]["generated_by"] == "deterministic"
    assert a["narrative"]["uncertainty"][0].startswith("DEMO-DATEN")
    assert len(a["input_hash"]) == 64
    assert a["facts"]["similarity"]["status"] in ("ok", "insufficient_history")
    assert a["sources"][0]["data_kind"] == "demo"

    latest = (await client.get("/api/symbols/AAPL/analyses/latest")).json()
    assert latest["id"] == a["id"]
    hist = (await client.get("/api/analyses", params={"symbol": "AAPL"})).json()
    assert hist[0]["id"] == a["id"] and "facts" not in hist[0]
    sim = (await client.get("/api/symbols/AAPL/similar")).json()
    assert sim["analysis_id"] == a["id"]

    container = client.app.state.container  # type: ignore[attr-defined]
    async with container.db.sessionmaker() as s:
        row = await s.get(AnalysisRow, uuid.UUID(a["id"]))
        row.outcome = "long_entry"
        with pytest.raises(RuntimeError, match="immutable"):
            await s.flush()
        await s.rollback()
    async with container.db.sessionmaker() as s:
        row = await s.get(AnalysisRow, uuid.UUID(a["id"]))
        with pytest.raises(RuntimeError, match="immutable"):
            await s.delete(row)
            await s.flush()
        await s.rollback()
    # Raw SQL UPDATE/DELETE is blocked in PostgreSQL by a trigger (alembic 0001).


async def test_analysis_is_reproducible_for_same_inputs(client: httpx.AsyncClient) -> None:
    a = (await client.post("/api/symbols/AAPL/analyze")).json()
    # a second click within 10 s returns the same stored analysis (CPU guard)
    assert (await client.post("/api/symbols/AAPL/analyze")).json()["id"] == a["id"]
    container = client.app.state.container  # type: ignore[attr-defined]
    b = await container.analysis.analyze("AAPL", trigger="test")
    assert str(b.id) != a["id"]
    assert b.input_hash == a["input_hash"]
    assert b.scenario == a["scenario"] or b.outcome == "invalidated"


async def test_notifications_are_deduplicated(client: httpx.AsyncClient) -> None:
    container = client.app.state.container  # type: ignore[attr-defined]
    n = Notification(dedupe_key="AAPL:test:1", kind="test", title="t", body="b", symbol="AAPL")
    assert await container.notifier.notify(n) is True
    assert await container.notifier.notify(n) is False
    items = (await client.get("/api/notifications")).json()
    assert len([i for i in items if i["kind"] == "test"]) == 1
    nid = items[0]["id"]
    assert (await client.post(f"/api/notifications/{nid}/read")).status_code == 204


async def test_overview_and_performance(client: httpx.AsyncClient) -> None:
    await client.post("/api/symbols/AAPL/analyze")
    ov = (await client.get("/api/watchlist/overview")).json()
    assert ov[0]["symbol"] == "AAPL" and ov[0]["price"] > 0 and "signal" in ov[0]
    perf = (await client.get("/api/performance", params={"horizon": 60})).json()
    assert perf["n"] == 0  # nothing evaluated yet
    assert (await client.get("/api/performance", params={"horizon": 7})).status_code == 422


async def test_news_endpoint_without_providers(client: httpx.AsyncClient) -> None:
    r = (await client.get("/api/symbols/AAPL/news")).json()
    assert r["enabled"] is False and r["items"] == []


async def test_api_token_enforced(tmp_path: Path, fixed_clock: datetime) -> None:
    settings = _settings(tmp_path, api_token=SecretStr("s3cret"))
    app = create_app(settings, build_container(settings, provider=DemoMarketData()))
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        assert (await c.get("/api/watchlist")).status_code == 401
        ok = await c.get("/api/watchlist", headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 200
        assert (await c.get("/api/health")).status_code == 200


def test_production_guards() -> None:
    with pytest.raises(ValueError, match="demo"):
        Settings(
            app_env="production",
            data_provider="demo",
            run_worker_in_api=False,
            database_url="postgresql+asyncpg://x/y",
        )


async def test_static_dashboard_served_from_same_origin(client: httpx.AsyncClient) -> None:
    r = await client.get("/")
    assert r.status_code == 200
    assert "ATI Terminal" in r.text
    assert (await client.get("/api/health")).json()["status"] == "ok"  # API keeps precedence


def test_env_files_resolve_from_project_root(tmp_path: Path) -> None:
    from app.core.config import ENV_FILES, PROJECT_ROOT

    assert ENV_FILES[0] == PROJECT_ROOT / "config" / "alpaca.env"
    assert (PROJECT_ROOT / "backend" / "app").is_dir()
    keys = tmp_path / "alpaca.env"
    keys.write_text("ALPACA_API_KEY_ID=PKTEST\nALPACA_API_SECRET_KEY=secret\n")
    s = Settings(_env_file=(keys,), app_env="test")  # type: ignore[call-arg]
    assert s.resolved_data_provider() == "alpaca"
