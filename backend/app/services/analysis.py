"""Orchestrates one complete analysis and stores it immutably."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.analysis.context import DEFAULT_SECTOR
from app.analysis.pipeline import FactInputs, SymbolData, compute_facts
from app.core.config import Settings
from app.core.errors import BudgetExceededError
from app.core.jsonsafe import canonical_hash, to_jsonable
from app.core.market_time import utcnow
from app.db import repositories as repo
from app.db.models import AnalysisRow, LLMUsageRow
from app.db.session import Database
from app.domain.models import Timeframe
from app.llm.base import LLMClient
from app.llm.null_client import deterministic_narrative
from app.llm.prompts import SYSTEM_PROMPT, build_prompt
from app.llm.schemas import AnalystNarrative
from app.llm.validator import validate_narrative
from app.news.service import NewsService, news_signal, price_reaction
from app.notifications.dispatcher import Notification, NotificationDispatcher
from app.services.market_data import MarketDataService
from app.signals.engine import ENGINE_VERSION, Outcome, build_scenario

log = logging.getLogger(__name__)

NOTIFY_OUTCOMES = {
    Outcome.LONG_ENTRY: "alert",
    Outcome.SHORT_ENTRY: "alert",
    Outcome.INVALIDATED: "warn",
    Outcome.BULLISH_SETUP: "info",
    Outcome.BEARISH_SETUP: "info",
}


class AnalysisService:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        market: MarketDataService,
        news: NewsService,
        llm: LLMClient | None,
        notifier: NotificationDispatcher,
        similarity_days: int = 250,
    ) -> None:
        self.settings = settings
        self.db = db
        self.market = market
        self.news = news
        self.llm = llm
        self.notifier = notifier
        self.similarity_days = similarity_days
        self._locks: dict[str, asyncio.Lock] = {}

    async def sector_for(self, symbol: str) -> str | None:
        async with self.db.session() as s:
            for w in await repo.list_watchlist(s):
                if w.symbol == symbol and w.sector_etf:
                    return w.sector_etf
        return DEFAULT_SECTOR.get(symbol)

    async def _load(self, symbol: str, now: datetime, days: int | None) -> SymbolData:
        minute = await self.market.get(symbol, Timeframe.M1, now, intraday_days=days)
        daily = await self.market.get(symbol, Timeframe.D1, now)
        return SymbolData(symbol, minute, daily)

    async def analyze(self, symbol: str, trigger: str = "manual") -> AnalysisRow:
        symbol = symbol.upper()
        lock = self._locks.setdefault(symbol, asyncio.Lock())
        async with lock:
            return await self._analyze(symbol, trigger)

    async def _analyze(self, symbol: str, trigger: str) -> AnalysisRow:
        now = utcnow()
        target = await self._load(symbol, now, self.similarity_days)
        market = await self._load("SPY", now, 10) if symbol != "SPY" else None
        sector_sym = await self.sector_for(symbol)
        sector = await self._load(sector_sym, now, 10) if sector_sym else None
        as_of = (
            (target.minute.index[-1] + timedelta(minutes=1)).to_pydatetime()
            if not target.minute.empty
            else now
        )
        as_of = min(as_of, now)

        news_rows = await self.news.recent(symbol, hours=72, limit=20) if self.news.enabled else []
        for news_row in news_rows:
            if not news_row.reaction or news_row.reaction.get("status") == "pending":
                reaction = price_reaction(
                    target.minute, market.minute if market else None, news_row.published_at
                )
                if reaction:
                    await self.news.store_reaction(news_row.id, to_jsonable(reaction))
                    news_row.reaction = reaction
        signals = [news_signal(r) for r in news_rows if r.duplicate_of is None]

        provenance = self.market.provenance(as_of)
        inputs = FactInputs(
            target=target,
            market=market,
            sector=sector,
            as_of=as_of,
            provenance=provenance,
            news_signals=[
                s
                for s in signals
                if datetime.fromisoformat(s["published_at"]) > as_of - timedelta(hours=24)
            ],
            similarity_min_samples=self.settings.similarity_min_samples,
        )
        facts = to_jsonable(await asyncio.to_thread(compute_facts, inputs))

        async with self.db.session() as s:
            prev = await repo.latest_analysis(s, symbol)
        previous = prev.scenario if prev and prev.created_at > now - timedelta(hours=8) else None
        scenario = to_jsonable(
            build_scenario(facts, self.settings.min_reward_risk, previous).to_dict()
        )

        narrative, llm_meta = await self._narrative(facts, scenario, signals)

        sources: list[dict[str, Any]] = [
            {
                "type": "market_data",
                "provider": provenance.provider,
                "feed": provenance.feed,
                "data_kind": provenance.data_kind.value,
                "as_of": as_of.isoformat(),
            }
        ]
        sources += [
            {
                "type": s["kind"],
                "id": s["id"],
                "title": s["headline"],
                "url": s["url"],
                "published_at": s["published_at"],
                "source": s["source"],
            }
            for s in signals
        ]

        row = AnalysisRow(
            id=uuid.uuid4(),
            symbol=symbol,
            created_at=now,
            data_as_of=as_of,
            trigger=trigger,
            outcome=scenario["outcome"],
            bias=scenario["bias"],
            reference_price=float(scenario["reference_price"] or 0.0),
            market_phase=facts.get("market_phase", "closed"),
            data_kind=provenance.data_kind.value,
            scenario=scenario,
            facts=facts,
            narrative=narrative,
            provenance=to_jsonable(provenance),
            sources=sources,
            input_hash=canonical_hash({"facts": facts, "engine": ENGINE_VERSION}),
            engine_version=ENGINE_VERSION,
            llm_model=llm_meta.get("model"),
        )
        async with self.db.session() as s:
            await repo.insert_analysis(s, row)
            await repo.add_event(
                s,
                "analysis.created",
                {
                    "id": str(row.id),
                    "symbol": symbol,
                    "outcome": row.outcome,
                    "label": scenario["label"],
                    "price": row.reference_price,
                },
                symbol,
            )
        for a in narrative.get("news_assessments", []):
            await self.news.store_assessment(a["news_id"], a)
        await self._maybe_notify(row, scenario)
        log.info(
            "analysis stored",
            extra={"symbol": symbol, "outcome": row.outcome, "trigger": trigger, "id": str(row.id)},
        )
        return row

    async def _narrative(
        self, facts: dict[str, Any], scenario: dict[str, Any], news: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        fallback = deterministic_narrative(facts, scenario)
        meta: dict[str, Any] = {"generated_by": "deterministic", "model": None}
        if self.llm is None:
            return {**fallback.model_dump(), "meta": meta}, meta
        prompt = build_prompt(facts, scenario, news)
        cache_key = canonical_hash({"prompt": prompt, "model": self.llm.model})
        try:
            async with self.db.session() as s:
                cached = await repo.llm_cached(s, cache_key)
                if cached is None:
                    spent = await repo.llm_cost_on(s, utcnow().date())
                    if spent >= self.settings.llm_daily_budget_usd:
                        raise BudgetExceededError(f"LLM-Tagesbudget erreicht ({spent:.2f} USD)")
            if cached is not None:
                narrative = AnalystNarrative.model_validate(cached)
                meta = {"generated_by": "llm_cache", "model": self.llm.model}
            else:
                result = await self.llm.analyze(SYSTEM_PROMPT, prompt)
                narrative = result.narrative
                meta = {
                    "generated_by": "llm",
                    "model": result.model,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "cost_usd": result.cost_usd,
                }
                async with self.db.session() as s:
                    await repo.record_llm_usage(
                        s,
                        LLMUsageRow(
                            day=utcnow().date(),
                            created_at=datetime.now(tz=UTC),
                            model=result.model,
                            purpose="analysis",
                            input_tokens=result.input_tokens,
                            output_tokens=result.output_tokens,
                            cost_usd=result.cost_usd,
                            cache_key=cache_key,
                            response=narrative.model_dump(),
                        ),
                    )
        except Exception as exc:  # LLM is optional: never fail the analysis because of it
            log.warning("llm narrative unavailable", extra={"error": str(exc)})
            meta["llm_error"] = str(exc)
            return {**fallback.model_dump(), "meta": meta}, meta

        checked, report = validate_narrative(narrative, facts, scenario, news)
        meta["validation"] = {"ok": report.ok, "errors": report.errors, "warnings": report.warnings}
        if not report.ok:
            log.warning("llm output rejected", extra={"errors": report.errors[:5]})
            meta["generated_by"] = "deterministic (LLM-Ausgabe verworfen)"
            return {**fallback.model_dump(), "meta": meta}, meta
        return {**checked.model_dump(), "meta": meta}, meta

    async def _maybe_notify(self, row: AnalysisRow, scenario: dict[str, Any]) -> None:
        try:
            outcome = Outcome(row.outcome)
        except ValueError:
            return
        severity = NOTIFY_OUTCOMES.get(outcome)
        if severity is None:
            return
        entry = scenario.get("entry_zone") or [row.reference_price, row.reference_price]
        bucket = round(float(entry[0]), 1)
        await self.notifier.notify(
            Notification(
                dedupe_key=f"{row.symbol}:{outcome.value}:{bucket}:{row.created_at.date()}",
                kind="setup",
                severity=severity,  # type: ignore[arg-type]
                title=f"{row.symbol}: {scenario['label']}",
                body="; ".join(scenario.get("reasons", [])[:3]),
                symbol=row.symbol,
                payload={"analysis_id": str(row.id), "data_kind": row.data_kind},
            )
        )
