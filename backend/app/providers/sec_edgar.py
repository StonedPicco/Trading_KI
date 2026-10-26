"""SEC EDGAR filings (8-K, 10-Q, 10-K …) via the official data.sec.gov JSON API.

Fair-access policy (sec.gov/os/accessing-edgar-data): max 10 requests/second and a declared
User-Agent with contact information. Without ``SEC_USER_AGENT`` the adapter is disabled.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.errors import ProviderError
from app.domain.models import NewsItem
from app.providers.http import AsyncRateLimiter, request_json

RELEVANT_FORMS = {"8-K", "10-Q", "10-K", "6-K", "S-1", "424B4", "SC 13D", "4"}


def parse_submissions(payload: dict[str, Any], symbol: str, cik: int) -> list[NewsItem]:
    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    items: list[NewsItem] = []
    for i, form in enumerate(forms):
        if form not in RELEVANT_FORMS:
            continue
        accession = recent["accessionNumber"][i]
        accepted = recent.get("acceptanceDateTime", [None] * len(forms))[i]
        published = (
            datetime.fromisoformat(accepted.replace("Z", "+00:00"))
            if accepted
            else datetime.fromisoformat(recent["filingDate"][i]).replace(tzinfo=UTC)
        )
        doc = recent.get("primaryDocument", [""] * len(forms))[i]
        desc = recent.get("primaryDocDescription", [""] * len(forms))[i] or form
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{doc}"
            if doc
            else None
        )
        items.append(
            NewsItem(
                id=f"sec:{accession}",
                provider="sec_edgar",
                source="SEC EDGAR",
                published_at=published.astimezone(UTC),
                headline=f"{symbol}: {form} – {desc}",
                url=url,
                symbols=[symbol],
                kind="filing",
            )
        )
    return items


class SecEdgarFilings:
    name = "sec_edgar"

    def __init__(self, user_agent: str | None, http: httpx.AsyncClient | None = None) -> None:
        if not user_agent or "@" not in user_agent:
            raise ProviderError("sec_edgar", "SEC_USER_AGENT with contact e-mail required")
        self.http = http or httpx.AsyncClient(
            timeout=20.0, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        )
        self.limiter = AsyncRateLimiter(8, 1.0)
        self._cik_map: dict[str, int] | None = None

    async def cik_for(self, symbol: str) -> int | None:
        if self._cik_map is None:
            data = await request_json(
                self.http,
                "GET",
                "https://www.sec.gov/files/company_tickers.json",
                limiter=self.limiter,
                provider=self.name,
            )
            self._cik_map = {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}
        return self._cik_map.get(symbol.upper())

    async def get_news(
        self, symbols: list[str], start: datetime, end: datetime, limit: int = 50
    ) -> list[NewsItem]:
        items: list[NewsItem] = []
        for symbol in symbols:
            cik = await self.cik_for(symbol)
            if cik is None:
                continue
            payload = await request_json(
                self.http,
                "GET",
                f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                limiter=self.limiter,
                provider=self.name,
            )
            items.extend(
                i
                for i in parse_submissions(payload, symbol.upper(), cik)
                if start <= i.published_at < end
            )
        items.sort(key=lambda i: i.published_at, reverse=True)
        return items[:limit]

    async def aclose(self) -> None:
        await self.http.aclose()
