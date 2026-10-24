"""Alpaca Market Data adapter (REST bars + news, WebSocket bar stream).

Endpoints used (Market Data API v2 / v1beta1):
  GET  {base}/v2/stocks/{symbol}/bars        historical bars, paginated via next_page_token
  GET  {base}/v1beta1/news                   Benzinga news
  WSS  {stream}/v2/{feed}                    real-time bars

Endpoint shapes follow Alpaca's public documentation; they could not be re-verified against the
live API from the build environment (network policy), see docs/research.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pandas as pd

from app.core.config import Settings
from app.core.errors import ProviderError
from app.domain.models import Bar, DataKind, NewsItem, Provenance, Timeframe
from app.providers.base import bars_to_frame, empty_bars
from app.providers.http import AsyncRateLimiter, request_json

log = logging.getLogger(__name__)

SIP_FREE_DELAY = timedelta(minutes=15)
_TF_MAP = {Timeframe.M1: "1Min", Timeframe.D1: "1Day"}


def _rfc3339(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_bar(raw: dict[str, Any]) -> Bar:
    return Bar(
        ts=datetime.fromisoformat(raw["t"].replace("Z", "+00:00")),
        open=float(raw["o"]),
        high=float(raw["h"]),
        low=float(raw["l"]),
        close=float(raw["c"]),
        volume=float(raw["v"]),
        vwap=float(raw["vw"]) if raw.get("vw") is not None else None,
        trade_count=int(raw["n"]) if raw.get("n") is not None else None,
    )


def parse_news(raw: dict[str, Any]) -> NewsItem:
    def _ts(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None

    published = _ts(raw.get("created_at"))
    if published is None:
        raise ValueError("news item without created_at")
    return NewsItem(
        id=f"alpaca:{raw['id']}",
        provider="alpaca",
        source=raw.get("source"),
        published_at=published,
        updated_at=_ts(raw.get("updated_at")),
        headline=str(raw.get("headline", "")).strip(),
        summary=(raw.get("summary") or None),
        content=(raw.get("content") or None),
        url=raw.get("url"),
        symbols=[str(s).upper() for s in raw.get("symbols", [])],
    )


class AlpacaClient:
    """Shared HTTP client + rate limiter for bars and news."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        if not (settings.alpaca_api_key_id and settings.alpaca_api_secret_key):
            raise ProviderError("alpaca", "ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY not set")
        self.settings = settings
        self.http = http or httpx.AsyncClient(
            base_url=settings.alpaca_data_base_url,
            timeout=httpx.Timeout(20.0),
            headers={
                "APCA-API-KEY-ID": settings.alpaca_api_key_id.get_secret_value(),
                "APCA-API-SECRET-KEY": settings.alpaca_api_secret_key.get_secret_value(),
            },
        )
        self.limiter = AsyncRateLimiter(settings.alpaca_requests_per_minute, 60.0)

    async def get(self, path: str, params: dict[str, Any]) -> Any:
        return await request_json(
            self.http, "GET", path, params=params, limiter=self.limiter, provider="alpaca"
        )

    async def aclose(self) -> None:
        await self.http.aclose()


class AlpacaMarketData:
    name = "alpaca"

    def __init__(self, client: AlpacaClient) -> None:
        self.client = client
        self.settings = client.settings
        self.feed: str = self.settings.alpaca_feed

    @property
    def _sip_delayed(self) -> bool:
        return self.feed == "sip" and self.settings.alpaca_plan == "basic"

    def provenance(self, timeframe: Timeframe, as_of: datetime | None = None) -> Provenance:
        notes: list[str] = []
        if self.feed == "iex":
            notes.append(
                "IEX-Feed: Echtzeit, aber nur eine Börse (Teil des Gesamtvolumens). "
                "Absolute Volumina sind nicht konsolidiert; RVOL ist IEX-intern vergleichbar."
            )
        if self._sip_delayed:
            notes.append("SIP im Gratisplan: die letzten 15 Minuten sind nicht abrufbar.")
        return Provenance(
            provider="alpaca",
            feed=self.feed,
            data_kind=DataKind.DELAYED if self._sip_delayed else DataKind.LIVE,
            is_realtime=not self._sip_delayed,
            delay_minutes=15 if self._sip_delayed else 0,
            as_of=as_of,
            notes=notes,
        )

    async def get_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame:
        if timeframe not in _TF_MAP:
            raise ValueError(f"alpaca adapter only fetches native timeframes, got {timeframe}")
        if self._sip_delayed:
            end = min(end, datetime.now(tz=UTC) - SIP_FREE_DELAY)
        if end <= start:
            return empty_bars()
        params: dict[str, Any] = {
            "timeframe": _TF_MAP[timeframe],
            "start": _rfc3339(start),
            "end": _rfc3339(end),
            "limit": 10000,
            "adjustment": "all",
            "feed": self.feed,
            "sort": "asc",
        }
        bars: list[Bar] = []
        for _ in range(500):  # hard page cap as safety net
            payload = await self.client.get(f"/v2/stocks/{symbol.upper()}/bars", params)
            bars.extend(parse_bar(b) for b in (payload.get("bars") or []))
            token = payload.get("next_page_token")
            if not token:
                break
            params["page_token"] = token
        df = bars_to_frame(bars)
        if timeframe == Timeframe.D1:
            # Daily bars are labelled by session date (00:00 UTC of the NY trading date).
            df.index = pd.DatetimeIndex(
                pd.to_datetime(df.index.tz_convert("America/New_York").date).tz_localize("UTC"),
                name="ts",
            )
            return df[
                (df.index >= start.replace(hour=0, minute=0, second=0, microsecond=0))
                & (df.index < end)
            ]
        return df[(df.index >= start) & (df.index < end)]

    async def aclose(self) -> None:
        await self.client.aclose()


class AlpacaNews:
    name = "alpaca_news"

    def __init__(self, client: AlpacaClient) -> None:
        self.client = client

    async def get_news(
        self, symbols: list[str], start: datetime, end: datetime, limit: int = 50
    ) -> list[NewsItem]:
        params: dict[str, Any] = {
            "symbols": ",".join(s.upper() for s in symbols),
            "start": _rfc3339(start),
            "end": _rfc3339(end),
            "limit": min(limit, 50),
            "sort": "desc",
            "include_content": "true",
        }
        items: list[NewsItem] = []
        while len(items) < limit:
            payload = await self.client.get("/v1beta1/news", params)
            for raw in payload.get("news") or []:
                try:
                    items.append(parse_news(raw))
                except (KeyError, ValueError):
                    log.warning("skipping malformed news item", extra={"raw_id": raw.get("id")})
            token = payload.get("next_page_token")
            if not token:
                break
            params["page_token"] = token
        return items[:limit]

    async def aclose(self) -> None:
        await self.client.aclose()


BarCallback = Callable[[str, Bar], Awaitable[None]]


class AlpacaBarStream:
    """Real-time minute bars over WebSocket with reconnect + backoff.

    After a reconnect the caller should REST-backfill the gap (MarketDataService does this on
    its regular refresh), since bars emitted while disconnected are not replayed.
    """

    def __init__(self, settings: Settings, on_bar: BarCallback) -> None:
        self.settings = settings
        self.on_bar = on_bar
        self.symbols: set[str] = set()
        self._stop = asyncio.Event()

    @property
    def url(self) -> str:
        return f"{self.settings.alpaca_stream_base_url}/v2/{self.settings.alpaca_feed}"

    def stop(self) -> None:
        self._stop.set()

    async def run(self, symbols: list[str]) -> None:
        import websockets

        assert self.settings.alpaca_api_key_id and self.settings.alpaca_api_secret_key
        self.symbols = {s.upper() for s in symbols}
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url, ping_interval=20) as ws:
                    await ws.send(
                        json.dumps(
                            {
                                "action": "auth",
                                "key": self.settings.alpaca_api_key_id.get_secret_value(),
                                "secret": self.settings.alpaca_api_secret_key.get_secret_value(),
                            }
                        )
                    )
                    await ws.send(json.dumps({"action": "subscribe", "bars": sorted(self.symbols)}))
                    backoff = 1.0
                    async for message in ws:
                        await self.handle_message(message)
                        if self._stop.is_set():
                            break
            except Exception as exc:
                log.warning("alpaca stream disconnected", extra={"error": str(exc)})
            if not self._stop.is_set():
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def handle_message(self, message: str | bytes) -> None:
        for msg in json.loads(message):
            kind = msg.get("T")
            if kind == "b":
                await self.on_bar(msg["S"], parse_bar(msg))
            elif kind == "error":
                log.error(
                    "alpaca stream error", extra={"code": msg.get("code"), "msg": msg.get("msg")}
                )
                if msg.get("code") in (
                    402,
                    404,
                    406,
                    409,
                ):  # auth / limits – no point retrying fast
                    await asyncio.sleep(30)
