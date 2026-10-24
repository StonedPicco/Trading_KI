"""Application error types."""

from __future__ import annotations


class AppError(Exception):
    """Base class for expected, user-presentable errors."""


class ProviderError(AppError):
    def __init__(self, provider: str, message: str, status: int | None = None) -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.status = status


class InsufficientDataError(AppError):
    pass


class BudgetExceededError(AppError):
    pass
