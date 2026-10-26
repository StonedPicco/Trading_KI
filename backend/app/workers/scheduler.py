"""Background jobs. Run standalone with ``python -m app.workers.scheduler`` or embedded in the
API process (``RUN_WORKER_IN_API=true``, development only).

Jobs are idempotent: bars are upserted, notifications/outcomes are de-duplicated by DB
constraints, and APScheduler runs at most one instance of each job at a time.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text

from app.container import Container, build_container
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.watchlist import ensure_default_watchlist

log = logging.getLogger(__name__)
WORKER_LOCK_ID = 7_310_431  # arbitrary constant for pg_try_advisory_lock


async def _guard(name: str, coro_fn) -> None:  # type: ignore[no-untyped-def]
    try:
        await coro_fn()
    except Exception:
        log.exception("job failed", extra={"job": name})


def build_scheduler(c: Container) -> AsyncIOScheduler:
    s = AsyncIOScheduler(timezone="UTC")
    opts = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 30}
    s.add_job(
        _guard,
        "interval",
        args=["monitor", c.monitor.tick],
        seconds=c.settings.monitor_interval_seconds,
        id="monitor",
        **opts,
    )
    s.add_job(
        _guard, "interval", args=["news", c.monitor.news_tick], seconds=120, id="news", **opts
    )
    s.add_job(
        _guard,
        "interval",
        args=["evaluation", c.evaluation.run],
        seconds=300,
        id="evaluation",
        **opts,
    )
    return s


async def acquire_single_worker_lock(c: Container) -> bool:
    if c.db.dialect != "postgresql":
        return True
    # Session-level advisory lock: held as long as this connection stays open.
    conn = await c.db.engine.connect()
    got = await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": WORKER_LOCK_ID})
    if not bool(got.scalar()):
        await conn.close()
        return False
    c.closables.append(_LockHolder(conn))
    return True


class _LockHolder:
    def __init__(self, conn) -> None:  # type: ignore[no-untyped-def]
        self.conn = conn

    async def aclose(self) -> None:
        await self.conn.close()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    c = build_container(settings)
    if not await acquire_single_worker_lock(c):
        log.error("another worker holds the lock – exiting")
        return
    await ensure_default_watchlist(c)
    scheduler = build_scheduler(c)
    scheduler.start()
    log.info("worker started", extra={"provider": c.provider.name})
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # not available on Windows
            loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        scheduler.shutdown(wait=False)
        await c.aclose()


if __name__ == "__main__":
    asyncio.run(main())
