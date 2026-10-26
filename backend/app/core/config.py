"""Application configuration loaded from environment variables / .env.

Secrets are typed as ``SecretStr`` so they never appear in reprs or logs.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root (backend/app/core/config.py -> parents[3]); env files are looked up there so the
# one-click start works regardless of the working directory. Missing files are ignored.
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Later files override earlier ones; real environment variables override all files.
# config/alpaca.env is written by the start scripts on first launch (gitignored).
ENV_FILES = (PROJECT_ROOT / "config" / "alpaca.env", PROJECT_ROOT / ".env", Path(".env"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES, extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./ati_dev.db"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    # Optional shared secret for the API (recommended whenever not bound to localhost).
    api_token: SecretStr | None = None

    # Market data
    data_provider: Literal["auto", "alpaca", "demo"] = "auto"
    alpaca_api_key_id: SecretStr | None = None
    alpaca_api_secret_key: SecretStr | None = None
    alpaca_feed: Literal["iex", "sip"] = "iex"
    # "basic" = free plan: SIP history excludes the latest 15 minutes, IEX is real-time.
    alpaca_plan: Literal["basic", "algo_trader_plus"] = "basic"
    alpaca_use_stream: bool = False
    alpaca_data_base_url: str = "https://data.alpaca.markets"
    alpaca_stream_base_url: str = "wss://stream.data.alpaca.markets"
    alpaca_requests_per_minute: int = 190
    intraday_lookback_days: int = 60
    similarity_lookback_days: int = 250
    daily_lookback_days: int = 730

    # SEC EDGAR requires a descriptive User-Agent incl. contact e-mail (fair access policy).
    sec_user_agent: str | None = None

    # LLM
    llm_provider: Literal["none", "anthropic"] = "none"
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    llm_news_model: str = "claude-opus-5-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_daily_budget_usd: float = 5.0
    llm_server_side_fallback: bool = True

    # Monitoring
    run_worker_in_api: bool = True
    monitor_interval_seconds: int = 60
    analysis_cooldown_seconds: int = 300
    default_watchlist: list[str] = Field(default_factory=lambda: ["AAPL", "NVDA", "SPY"])

    # Evaluation / statistics
    calibration_min_samples: int = 50
    similarity_min_samples: int = 30
    min_reward_risk: float = 1.5

    @field_validator(
        "alpaca_api_key_id",
        "alpaca_api_secret_key",
        "anthropic_api_key",
        "api_token",
        "sec_user_agent",
        mode="before",
    )
    @classmethod
    def _empty_to_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.app_env == "production":
            if self.resolved_data_provider() == "demo":
                raise ValueError("production requires a real market data provider (not demo)")
            if self.run_worker_in_api:
                raise ValueError("production requires a separate worker process")
            if self.database_url.startswith("sqlite"):
                raise ValueError("production requires PostgreSQL")
        return self

    def resolved_data_provider(self) -> Literal["alpaca", "demo"]:
        if self.data_provider != "auto":
            return self.data_provider
        if self.alpaca_api_key_id and self.alpaca_api_secret_key:
            return "alpaca"
        return "demo"

    def llm_enabled(self) -> bool:
        return self.llm_provider == "anthropic" and self.anthropic_api_key is not None


@lru_cache
def get_settings() -> Settings:
    return Settings()
