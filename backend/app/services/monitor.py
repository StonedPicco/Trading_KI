"""Watches the watchlist and triggers analyses on relevant market changes.

Cheap checks run every tick; the full (expensive) analysis only runs when a trigger fires and
the per-symbol cooldown has elapsed (invalidations bypass the cooldown). Notifications are
de-duplicated by key through a UNIQUE constraint.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from app.analysis.indicators import regular_session_mask, relative_volume
from app.core.config import Settings
from app.core.market_time import MarketPhase, market_phase, ny_date, utcnow
from app.db import repositories as repo
from app.db.session import Database
from app.domain.models import Timeframe
from app.news.service import NewsService
from app.notifications.dispatcher import Notification, NotificationDispatcher, Severity
from app.services.analysis import AnalysisService
from app.services.market_data import MarketDataService

log = logging.getLogger(__name__)


@dataclass
class Trigger:
    kind: str
    dedupe_key: str
    title: str
    body: str
    severity: Severity = "info"
    bypass_cooldown: bool = False


def _intraday_return(minute: pd.DataFrame, now: datetime) -> float | None:
    session = ny_date(now)
    local = minute.index.tz_convert("America/New_York").date
    today = minute[(local == session) & regular_session_mask(minute.index)]
    if today.empty:
        return None
    return float(today["close"].iloc[-1] / today["open"].iloc[0] - 1) * 100


def detect_triggers(
    symbol: str,
    minute: pd.DataFrame,
    spy_minute: pd.DataFrame | None,
    last_analysis: dict[str, Any] | None,
    now: datetime,
) -> list[Trigger]:
    triggers: list[Trigger] = []
    if minute.empty:
        return triggers
    day = ny_date(now).isoformat()
    close = float(minute["close"].iloc[-1])
    facts = (last_analysis or {}).get("facts") or {}
    scenario = (last_analysis or {}).get("scenario") or {}
    ref = (last_analysis or {}).get("reference_price")

    # 1) level break relative to the zones of the previous analysis
    if ref:
        for z in facts.get("zones", []):
            if z.get("strength", 0) < 2:
                continue
            if ref <= z["high"] < close:
                triggers.append(
                    Trigger(
                        "level_break",
                        f"{symbol}:break:up:{z['high']:.2f}:{day}",
                        f"{symbol} über Widerstand {z['high']:.2f}",
                        f"Kurs {close:.2f} hat die Zone {z['low']:.2f}–{z['high']:.2f} "
                        "überschritten",
                        "warn",
                    )
                )
            elif ref >= z["low"] > close:
                triggers.append(
                    Trigger(
                        "level_break",
                        f"{symbol}:break:down:{z['low']:.2f}:{day}",
                        f"{symbol} unter Unterstützung {z['low']:.2f}",
                        f"Kurs {close:.2f} hat die Zone {z['low']:.2f}–{z['high']:.2f} "
                        "unterschritten",
                        "warn",
                    )
                )

    # 2) volume spike on the latest regular-session minute (time-of-day adjusted)
    tail = minute.iloc[-390 * 22 :]
    rv = relative_volume(tail)["rvol_bar"].dropna()
    if len(rv) and rv.index[-1] == minute.index[-1] and rv.iloc[-1] >= 3:
        window = pd.Timestamp(rv.index[-1]).floor("15min").strftime("%H%M")
        triggers.append(
            Trigger(
                "volume_spike",
                f"{symbol}:vol:{day}:{window}",
                f"{symbol}: ungewöhnliches Volumen",
                f"RVOL {rv.iloc[-1]:.1f}× im letzten Minutenbar",
                "info",
            )
        )

    # 3) relative move vs. SPY
    if spy_minute is not None and not spy_minute.empty:
        r_s, r_m = _intraday_return(minute, now), _intraday_return(spy_minute, now)
        atr_pct = (facts.get("daily") or {}).get("atr_pct") or 2.0
        if r_s is not None and r_m is not None and abs(r_s - r_m) >= max(1.5, 0.75 * atr_pct):
            direction = "up" if r_s > r_m else "down"
            triggers.append(
                Trigger(
                    "relative_move",
                    f"{symbol}:rel:{direction}:{day}",
                    f"{symbol} {'stärker' if direction == 'up' else 'schwächer'} als der Markt",
                    f"{r_s:+.2f} % vs. SPY {r_m:+.2f} % seit Eröffnung",
                    "info",
                )
            )

    # 4) invalidation of the current hypothesis
    inv, bias = scenario.get("invalidation_price"), scenario.get("bias")
    if inv and bias in ("long", "short"):
        hit = close < inv if bias == "long" else close > inv
        if hit:
            triggers.append(
                Trigger(
                    "invalidation",
                    f"{symbol}:inv:{(last_analysis or {}).get('id')}",
                    f"{symbol}: Hypothese invalidiert",
                    f"{bias}-Szenario: Kurs {close:.2f} jenseits {inv:.2f}",
                    "warn",
                    bypass_cooldown=True,
                )
            )
    return triggers


class MonitorService:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        market: MarketDataService,
        news: NewsService,
        analysis: AnalysisService,
        notifier: NotificationDispatcher,
    ) -> None:
        self.settings = settings
        self.db = db
        self.market = market
        self.news = news
        self.analysis = analysis
        self.notifier = notifier
        self._last_run: dict[str, datetime] = {}

    async def watchlist(self) -> list[str]:
        async with self.db.session() as s:
            rows = await repo.list_watchlist(s)
        return [r.symbol for r in rows]

    async def tick(self) -> dict[str, list[str]]:
        now = utcnow()
        phase = market_phase(now)
        fired: dict[str, list[str]] = {}
        if phase == MarketPhase.CLOSED:
            return fired
        symbols = await self.watchlist()
        spy = await self.market.get("SPY", Timeframe.M1, now, intraday_days=25)
        for symbol in symbols:
            try:
                fired[symbol] = await self._check(symbol, spy, now, phase)
            except Exception as exc:
                log.exception("monitor check failed", extra={"symbol": symbol, "error": str(exc)})
        async with self.db.session() as s:  # lets dashboards refresh charts without polling
            await repo.add_event(s, "bars.updated", {"symbols": symbols, "as_of": now.isoformat()})
        return fired

    async def _check(
        self, symbol: str, spy: pd.DataFrame, now: datetime, phase: MarketPhase
    ) -> list[str]:
        minute = await self.market.get(symbol, Timeframe.M1, now, intraday_days=25)
        async with self.db.session() as s:
            last = await repo.latest_analysis(s, symbol)
        last_dict = None
        if last is not None:
            last_dict = {
                "id": str(last.id),
                "facts": last.facts,
                "scenario": last.scenario,
                "reference_price": last.reference_price,
                "created_at": last.created_at,
            }
        triggers = detect_triggers(symbol, minute, spy if symbol != "SPY" else None, last_dict, now)

        # periodic refresh during regular hours if nothing else happened
        stale = last is None or (now - last.created_at) > timedelta(minutes=30)
        if not triggers and stale and phase == MarketPhase.REGULAR:
            triggers.append(Trigger("scheduled", f"{symbol}:sched:{now:%Y%m%d%H%M}", "", ""))

        new_triggers = []
        for t in triggers:
            if t.kind == "scheduled":
                new_triggers.append(t)
                continue
            if await self.notifier.notify(
                Notification(
                    dedupe_key=t.dedupe_key,
                    kind=t.kind,
                    title=t.title,
                    body=t.body,
                    severity=t.severity,
                    symbol=symbol,
                )
            ):
                new_triggers.append(t)
        if not new_triggers:
            return []
        cooldown = timedelta(seconds=self.settings.analysis_cooldown_seconds)
        last_run = self._last_run.get(symbol) or (last.created_at if last else None)
        bypass = any(t.bypass_cooldown for t in new_triggers)
        if last_run and now - last_run < cooldown and not bypass:
            return [t.kind for t in new_triggers]
        self._last_run[symbol] = now
        await self.analysis.analyze(
            symbol, trigger="+".join(sorted({t.kind for t in new_triggers}))
        )
        return [t.kind for t in new_triggers]

    async def news_tick(self) -> int:
        if not self.news.enabled:
            return 0
        symbols = await self.watchlist()
        if not symbols:
            return 0
        rows = await self.news.fetch_and_store(symbols)
        for row in rows:
            for symbol in set(row.symbols) & set(symbols):
                await self.notifier.notify(
                    Notification(
                        dedupe_key=f"news:{row.id}:{symbol}",
                        kind="news",
                        severity="info",
                        title=f"{symbol}: {row.headline[:150]}",
                        body=row.source or row.provider,
                        symbol=symbol,
                        payload={"news_id": row.id, "url": row.url},
                    )
                )
                if row.published_at > utcnow() - timedelta(hours=2):
                    last = self._last_run.get(symbol)
                    if last is None or utcnow() - last > timedelta(
                        seconds=self.settings.analysis_cooldown_seconds
                    ):
                        self._last_run[symbol] = utcnow()
                        await self.analysis.analyze(symbol, trigger="news")
        return len(rows)
