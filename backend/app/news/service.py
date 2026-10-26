"""News intelligence: ingestion, de-duplication, novelty, and measured price reaction.

The price reaction is computed from market data – never inferred by the LLM.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.core.market_time import utcnow
from app.db import repositories as repo
from app.db.models import NewsRow
from app.db.session import Database
from app.domain.models import NewsItem
from app.providers.base import NewsProvider

log = logging.getLogger(__name__)
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "at", "by", "with"}


def normalize_headline(text: str) -> str:
    return " ".join(t for t in _TOKEN.findall(text.lower()) if t not in _STOP)


def content_hash(item: NewsItem) -> str:
    return hashlib.sha256(normalize_headline(item.headline).encode()).hexdigest()


def jaccard(a: str, b: str) -> float:
    sa, sb = set(normalize_headline(a).split()), set(normalize_headline(b).split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def price_reaction(
    minute: pd.DataFrame,
    bench: pd.DataFrame | None,
    published_at: datetime,
    horizons: tuple[int, ...] = (5, 15, 30),
) -> dict[str, Any] | None:
    """Return/excess return/RVOL after publication, relative to typical moves of the stock."""
    if minute.empty:
        return None
    pub = pd.Timestamp(published_at)
    before = minute[minute.index < pub]
    after = minute[minute.index >= pub]
    if before.empty or after.empty:
        return {"status": "pending", "note": "noch keine Kursdaten nach Veröffentlichung"}
    ref = float(before["close"].iloc[-1])
    gap_min = (after.index[0] - pub).total_seconds() / 60
    out: dict[str, Any] = {
        "status": "ok",
        "ref_price": ref,
        "first_bar_delay_min": round(gap_min, 1),
    }
    hist_vol = before["volume"].iloc[-390 * 5 :]
    base_vol = float(hist_vol.mean()) if len(hist_vol) else np.nan
    abs15 = before["close"].pct_change(15).abs().iloc[-390 * 10 :]
    typical15 = float(abs15.median()) if abs15.notna().any() else np.nan
    for h in horizons:
        window = after[after.index < pub + pd.Timedelta(minutes=h)]
        if window.empty:
            continue
        ret = float(window["close"].iloc[-1] / ref - 1)
        excess = ret
        if bench is not None and not bench.empty:
            b_before = bench[bench.index < pub]
            b_win = bench[(bench.index >= pub) & (bench.index < pub + pd.Timedelta(minutes=h))]
            if not b_before.empty and not b_win.empty:
                excess = ret - float(b_win["close"].iloc[-1] / b_before["close"].iloc[-1] - 1)
        rvol = float(window["volume"].mean() / base_vol) if base_vol and base_vol > 0 else None
        out[f"ret_{h}m_pct"] = round(ret * 100, 3)
        out[f"excess_{h}m_pct"] = round(excess * 100, 3)
        out[f"rvol_{h}m"] = round(rvol, 2) if rvol is not None else None
    ex15, rv15 = out.get("excess_15m_pct"), out.get("rvol_15m")
    if ex15 is not None and typical15 == typical15:
        threshold = max(0.3, 2 * typical15 * 100)
        out["typical_15m_move_pct"] = round(typical15 * 100, 3)
        out["significant"] = bool(abs(ex15) >= threshold and (rv15 or 0) >= 1.5)
        out["direction"] = "up" if ex15 > 0 else "down"
    return out


class NewsService:
    def __init__(self, db: Database, providers: list[NewsProvider]) -> None:
        self.db = db
        self.providers = providers

    @property
    def enabled(self) -> bool:
        return bool(self.providers)

    async def fetch_and_store(
        self, symbols: list[str], lookback: timedelta = timedelta(days=3)
    ) -> list[NewsRow]:
        """Fetch from all providers; returns rows that are new *and* novel."""
        now = utcnow()
        new_rows: list[NewsRow] = []
        for provider in self.providers:
            try:
                items = await provider.get_news(symbols, now - lookback, now, limit=50)
            except Exception as exc:
                log.warning(
                    "news provider failed", extra={"provider": provider.name, "error": str(exc)}
                )
                continue
            async with self.db.session() as s:
                recent = await repo.recent_news(s, None, now - timedelta(hours=72), limit=500)
                for item in sorted(items, key=lambda i: i.published_at):
                    h = content_hash(item)
                    dup = await repo.news_by_hash(s, h)
                    if dup is None:
                        dup = next(
                            (
                                r
                                for r in recent
                                if jaccard(r.headline, item.headline) >= 0.8
                                and set(r.symbols) & set(item.symbols)
                            ),
                            None,
                        )
                    row = NewsRow(
                        id=item.id,
                        provider=item.provider,
                        kind=item.kind,
                        source=item.source,
                        published_at=item.published_at,
                        first_seen_at=now,
                        headline=item.headline,
                        summary=item.summary or (item.content[:600] if item.content else None),
                        url=item.url
                        if (item.url or "").startswith(("https://", "http://"))
                        else None,
                        symbols=item.symbols,
                        content_hash=h,
                        duplicate_of=dup.id if dup and dup.id != item.id else None,
                    )
                    if await repo.upsert_news(s, row):
                        recent.append(row)
                        if row.duplicate_of is None:
                            new_rows.append(row)
        return new_rows

    async def recent(self, symbol: str, hours: int = 72, limit: int = 30) -> list[NewsRow]:
        async with self.db.session() as s:
            return await repo.recent_news(
                s, symbol.upper(), utcnow() - timedelta(hours=hours), limit
            )

    async def store_reaction(self, news_id: str, reaction: dict[str, Any]) -> None:
        async with self.db.session() as s:
            row = await s.get(NewsRow, news_id)
            if row is not None:
                row.reaction = reaction

    async def store_assessment(self, news_id: str, assessment: dict[str, Any]) -> None:
        async with self.db.session() as s:
            row = await s.get(NewsRow, news_id)
            if row is not None:
                row.assessment = assessment


def news_signal(row: NewsRow) -> dict[str, Any]:
    """Compact representation for the engine/LLM; direction only from a validated assessment."""
    assessment = row.assessment or {}
    reaction = row.reaction or {}
    direction = assessment.get("direction", "unclear")
    confirmed = bool(
        reaction.get("significant")
        and direction in ("bullish", "bearish")
        and (reaction.get("direction") == "up") == (direction == "bullish")
    )
    return {
        "id": row.id,
        "headline": row.headline,
        "summary": row.summary,
        "source": row.source,
        "published_at": row.published_at.isoformat(),
        "url": row.url,
        "kind": row.kind,
        "is_duplicate": row.duplicate_of is not None,
        "reaction": reaction or None,
        "direction": direction,
        "confirmed_by_price": confirmed,
    }
