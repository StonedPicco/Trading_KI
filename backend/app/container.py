"""Composition root: builds providers and services from settings."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.config import Settings
from app.db.session import Database
from app.llm.anthropic_client import AnthropicLLMClient
from app.llm.base import LLMClient
from app.news.service import NewsService
from app.notifications.dispatcher import NotificationDispatcher
from app.providers.base import MarketDataProvider, NewsProvider
from app.providers.demo import DemoMarketData
from app.services.analysis import AnalysisService
from app.services.evaluation import EvaluationService
from app.services.market_data import MarketDataService
from app.services.monitor import MonitorService

log = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    db: Database
    provider: MarketDataProvider
    market: MarketDataService
    news: NewsService
    llm: LLMClient | None
    notifier: NotificationDispatcher
    analysis: AnalysisService
    evaluation: EvaluationService
    monitor: MonitorService
    closables: list[object] = field(default_factory=list)

    async def aclose(self) -> None:
        for c in self.closables:
            close = getattr(c, "aclose", None)
            if close:
                await close()
        await self.db.dispose()


def build_container(
    settings: Settings,
    provider: MarketDataProvider | None = None,
    news_providers: list[NewsProvider] | None = None,
    llm: LLMClient | None = None,
) -> Container:
    db = Database(settings.database_url)
    closables: list[object] = []
    if provider is None:
        if settings.resolved_data_provider() == "alpaca":
            from app.providers.alpaca import AlpacaClient, AlpacaMarketData, AlpacaNews

            client = AlpacaClient(settings)
            provider = AlpacaMarketData(client)
            if news_providers is None:
                news_providers = [AlpacaNews(client)]
        else:
            provider = DemoMarketData()
            log.warning("DEMO MODE: no market data keys configured – serving SIMULATED data")
    closables.append(provider)
    if news_providers is None:
        news_providers = []
    if settings.sec_user_agent:
        from app.providers.sec_edgar import SecEdgarFilings

        sec = SecEdgarFilings(settings.sec_user_agent)
        news_providers = [*news_providers, sec]
        closables.append(sec)
    if llm is None and settings.llm_enabled():
        assert settings.anthropic_api_key is not None
        llm = AnthropicLLMClient(
            settings.anthropic_api_key.get_secret_value(),
            settings.llm_model,
            settings.llm_effort,
            settings.llm_server_side_fallback,
        )
    market = MarketDataService(
        provider, db, settings.intraday_lookback_days, settings.daily_lookback_days
    )
    news = NewsService(db, news_providers)
    notifier = NotificationDispatcher(db)
    analysis = AnalysisService(
        settings, db, market, news, llm, notifier, similarity_days=settings.similarity_lookback_days
    )
    return Container(
        settings=settings,
        db=db,
        provider=provider,
        market=market,
        news=news,
        llm=llm,
        notifier=notifier,
        analysis=analysis,
        evaluation=EvaluationService(db, market),
        monitor=MonitorService(settings, db, market, news, analysis, notifier),
        closables=closables,
    )
