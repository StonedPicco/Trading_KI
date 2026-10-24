"""Notification channels. In-app is implemented; Telegram/Discord/E-Mail/Push plug in as
additional ``Notifier`` implementations registered on the dispatcher."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from app.db import repositories as repo
from app.db.models import NotificationRow
from app.db.session import Database

log = logging.getLogger(__name__)

Severity = Literal["info", "warn", "alert"]


@dataclass
class Notification:
    dedupe_key: str
    kind: str
    title: str
    body: str
    severity: Severity = "info"
    symbol: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class Notifier(Protocol):
    name: str

    async def send(self, n: Notification) -> None: ...


class InAppNotifier:
    name = "in_app"

    def __init__(self, db: Database) -> None:
        self.db = db

    async def send(self, n: Notification) -> None:
        # Persistence + dedupe happen in the dispatcher; here we only emit the outbox event.
        async with self.db.session() as s:
            await repo.add_event(
                s,
                "notification",
                {
                    "kind": n.kind,
                    "title": n.title,
                    "body": n.body,
                    "severity": n.severity,
                    "symbol": n.symbol,
                    "payload": n.payload,
                },
                n.symbol,
            )


class NotificationDispatcher:
    def __init__(self, db: Database, channels: list[Notifier] | None = None) -> None:
        self.db = db
        self.channels: list[Notifier] = channels or [InAppNotifier(db)]

    def register(self, channel: Notifier) -> None:
        self.channels.append(channel)

    async def notify(self, n: Notification) -> bool:
        """Persist once per dedupe_key (DB UNIQUE constraint) and fan out. False = duplicate."""
        async with self.db.session() as s:
            inserted = await repo.insert_notification(
                s,
                NotificationRow(
                    dedupe_key=n.dedupe_key[:160],
                    symbol=n.symbol,
                    kind=n.kind,
                    severity=n.severity,
                    title=n.title[:200],
                    body=n.body,
                    payload=n.payload,
                    created_at=datetime.now(tz=UTC),
                ),
            )
        if not inserted:
            return False
        for ch in self.channels:
            try:
                await ch.send(n)
            except Exception as exc:  # one failing channel must not block the others
                log.warning("notifier failed", extra={"channel": ch.name, "error": str(exc)})
        return True
