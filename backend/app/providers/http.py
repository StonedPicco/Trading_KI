"""HTTP helpers: async rate limiting and retry with exponential backoff."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

import httpx

from app.core.errors import ProviderError

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class AsyncRateLimiter:
    """Token bucket limiting requests to ``rate`` per ``per`` seconds."""

    def __init__(self, rate: int, per: float = 60.0) -> None:
        self.capacity = max(1, rate)
        self.tokens = float(self.capacity)
        self.fill_rate = self.capacity / per
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self.tokens = min(
                    self.capacity, self.tokens + (now - self.updated) * self.fill_rate
                )
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.fill_rate)


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    limiter: AsyncRateLimiter | None = None,
    params: dict[str, Any] | None = None,
    max_attempts: int = 5,
    provider: str = "http",
) -> Any:
    delay = 1.0
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        if limiter:
            await limiter.acquire()
        try:
            resp = await client.request(method, url, params=params)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_error = exc
            log.warning("transport error", extra={"provider": provider, "attempt": attempt})
        else:
            if resp.status_code < 400:
                return resp.json()
            if resp.status_code not in RETRYABLE_STATUS:
                raise ProviderError(
                    provider,
                    f"HTTP {resp.status_code} for {url}: {resp.text[:300]}",
                    status=resp.status_code,
                )
            last_error = ProviderError(
                provider, f"HTTP {resp.status_code}", status=resp.status_code
            )
            retry_after = resp.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                delay = max(delay, float(retry_after))
            log.warning(
                "retryable status",
                extra={"provider": provider, "status": resp.status_code, "attempt": attempt},
            )
        if attempt < max_attempts:
            await asyncio.sleep(delay + random.uniform(0, 0.25 * delay))  # noqa: S311
            delay = min(delay * 2, 30.0)
    raise ProviderError(provider, f"giving up after {max_attempts} attempts: {last_error}")
