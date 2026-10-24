from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.core.config import Settings
from app.core.errors import ProviderError
from app.domain.models import DataKind, Timeframe
from app.providers.alpaca import AlpacaBarStream, AlpacaClient, AlpacaMarketData, AlpacaNews
from app.providers.demo import DemoMarketData
from app.providers.sec_edgar import parse_submissions

BASE = "https://data.alpaca.markets"


def settings(**kw: object) -> Settings:
    return Settings(
        app_env="test",
        alpaca_api_key_id=SecretStr("kid"),
        alpaca_api_secret_key=SecretStr("sec"),
        **kw,  # type: ignore[arg-type]
    )


def _bar(t: str, c: float) -> dict[str, object]:
    return {"t": t, "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 100, "n": 5, "vw": c}


@respx.mock
async def test_alpaca_bars_pagination_headers_and_params() -> None:
    route = respx.get(f"{BASE}/v2/stocks/AAPL/bars").mock(
        side_effect=[
            httpx.Response(
                200, json={"bars": [_bar("2026-10-22T13:30:00Z", 10)], "next_page_token": "abc"}
            ),
            httpx.Response(
                200, json={"bars": [_bar("2026-10-22T13:31:00Z", 11)], "next_page_token": None}
            ),
        ]
    )
    md = AlpacaMarketData(AlpacaClient(settings()))
    df = await md.get_bars(
        "aapl",
        Timeframe.M1,
        datetime(2026, 10, 22, 13, 0, tzinfo=UTC),
        datetime(2026, 10, 22, 14, 0, tzinfo=UTC),
    )
    assert list(df["close"]) == [10, 11]
    first, second = route.calls[0].request, route.calls[1].request
    assert first.headers["APCA-API-KEY-ID"] == "kid"
    assert first.url.params["adjustment"] == "all"
    assert first.url.params["feed"] == "iex"
    assert second.url.params["page_token"] == "abc"
    prov = md.provenance(Timeframe.M1)
    assert prov.data_kind == DataKind.LIVE and prov.notes  # IEX caveat present
    await md.aclose()


@respx.mock
async def test_alpaca_free_sip_clamps_to_15_minutes_delay() -> None:
    route = respx.get(f"{BASE}/v2/stocks/AAPL/bars").mock(
        return_value=httpx.Response(200, json={"bars": [], "next_page_token": None})
    )
    md = AlpacaMarketData(AlpacaClient(settings(alpaca_feed="sip", alpaca_plan="basic")))
    now = datetime.now(tz=UTC)
    await md.get_bars("AAPL", Timeframe.M1, now - timedelta(hours=2), now)
    end = datetime.fromisoformat(route.calls[0].request.url.params["end"].replace("Z", "+00:00"))
    assert end <= now - timedelta(minutes=14)
    assert md.provenance(Timeframe.M1).data_kind == DataKind.DELAYED
    await md.aclose()


@respx.mock
async def test_alpaca_daily_bars_labelled_by_session_date() -> None:
    respx.get(f"{BASE}/v2/stocks/AAPL/bars").mock(
        return_value=httpx.Response(
            200, json={"bars": [_bar("2026-10-21T04:00:00Z", 10), _bar("2026-10-22T04:00:00Z", 11)]}
        )
    )
    md = AlpacaMarketData(AlpacaClient(settings()))
    df = await md.get_bars(
        "AAPL", Timeframe.D1, datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 23, tzinfo=UTC)
    )
    assert [ts.isoformat() for ts in df.index] == [
        "2026-10-21T00:00:00+00:00",
        "2026-10-22T00:00:00+00:00",
    ]
    await md.aclose()


@respx.mock
async def test_alpaca_retries_on_429_then_raises_on_403() -> None:
    respx.get(f"{BASE}/v2/stocks/AAPL/bars").mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "0"}),
            httpx.Response(403, text="subscription does not permit"),
        ]
    )
    md = AlpacaMarketData(AlpacaClient(settings()))
    with pytest.raises(ProviderError) as exc:
        await md.get_bars(
            "AAPL",
            Timeframe.M1,
            datetime(2026, 10, 22, 13, tzinfo=UTC),
            datetime(2026, 10, 22, 14, tzinfo=UTC),
        )
    assert exc.value.status == 403
    await md.aclose()


@respx.mock
async def test_alpaca_news_parsing() -> None:
    respx.get(f"{BASE}/v1beta1/news").mock(
        return_value=httpx.Response(
            200,
            json={
                "news": [
                    {
                        "id": 42,
                        "headline": " Acme beats ",
                        "created_at": "2026-10-22T12:00:00Z",
                        "updated_at": "2026-10-22T12:05:00Z",
                        "summary": "s",
                        "content": "",
                        "url": "https://x",
                        "symbols": ["acme"],
                        "source": "benzinga",
                    },
                    {"id": 43},
                ],
                "next_page_token": None,
            },
        )
    )
    news = AlpacaNews(AlpacaClient(settings()))
    items = await news.get_news(
        ["ACME"], datetime(2026, 10, 21, tzinfo=UTC), datetime(2026, 10, 23, tzinfo=UTC)
    )
    assert len(items) == 1  # malformed item skipped
    assert items[0].id == "alpaca:42" and items[0].headline == "Acme beats"
    assert items[0].symbols == ["ACME"] and items[0].content is None
    await news.aclose()


async def test_alpaca_stream_message_handling() -> None:
    got: list[tuple[str, float]] = []

    async def on_bar(sym: str, bar: object) -> None:
        got.append((sym, bar.close))  # type: ignore[attr-defined]

    stream = AlpacaBarStream(settings(), on_bar)
    await stream.handle_message(
        json.dumps(
            [
                {"T": "success", "msg": "authenticated"},
                {"T": "b", "S": "AAPL", **_bar("2026-10-22T13:30:00Z", 10)},
            ]
        )
    )
    assert got == [("AAPL", 10.0)]
    assert stream.url.endswith("/v2/iex")


def test_missing_keys_raise() -> None:
    with pytest.raises(ProviderError):
        AlpacaClient(Settings(app_env="test"))


async def test_demo_provider_is_labelled_and_deterministic() -> None:
    now = datetime(2026, 10, 22, 17, 45, tzinfo=UTC)
    p = DemoMarketData(now=now)
    a = await p.get_bars("AAPL", Timeframe.M1, now - timedelta(days=3), now)
    b = await p.get_bars("AAPL", Timeframe.M1, now - timedelta(days=3), now)
    assert a.equals(b)
    assert a.index[-1] < now
    assert p.provenance(Timeframe.M1).data_kind == DataKind.DEMO
    d = await p.get_bars("AAPL", Timeframe.D1, now - timedelta(days=10), now)
    assert d.index[-1].date() < now.date()  # current session is not a completed daily bar
    assert (
        (a["low"] <= a[["open", "close"]].min(axis=1))
        & (a["high"] >= a[["open", "close"]].max(axis=1))
    ).all()


def test_sec_submissions_parsing() -> None:
    payload = {
        "filings": {
            "recent": {
                "form": ["8-K", "S-8", "10-Q"],
                "accessionNumber": ["0001-26-1", "0001-26-2", "0001-26-3"],
                "filingDate": ["2026-10-20", "2026-10-19", "2026-10-01"],
                "acceptanceDateTime": ["2026-10-20T16:05:00.000Z", None, None],
                "primaryDocument": ["a.htm", "b.htm", "c.htm"],
                "primaryDocDescription": ["Results", "", "Quarterly"],
            }
        }
    }
    items = parse_submissions(payload, "ACME", 1234)
    assert [i.id for i in items] == ["sec:0001-26-1", "sec:0001-26-3"]
    assert items[0].url == "https://www.sec.gov/Archives/edgar/data/1234/0001261/a.htm"
    assert items[0].published_at == datetime(2026, 10, 20, 16, 5, tzinfo=UTC)
