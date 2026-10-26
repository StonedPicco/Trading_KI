"""Watchlist helpers."""

from __future__ import annotations

import re

from app.analysis.context import DEFAULT_SECTOR, SECTOR_ETFS
from app.container import Container
from app.db import repositories as repo

SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def normalize_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if not SYMBOL_RE.match(s):
        raise ValueError(f"ungültiges Tickersymbol: {symbol!r}")
    return s


async def ensure_default_watchlist(c: Container) -> None:
    async with c.db.session() as s:
        if await repo.list_watchlist(s):
            return
        for sym in c.settings.default_watchlist:
            await repo.add_watchlist(s, normalize_symbol(sym), DEFAULT_SECTOR.get(sym))


def validate_sector(etf: str | None) -> str | None:
    if etf is None or etf == "":
        return None
    etf = etf.upper()
    if etf not in SECTOR_ETFS and etf not in ("SPY", "QQQ", "IWM", "DIA"):
        raise ValueError(f"unbekannter Sektor-ETF {etf}")
    return etf
