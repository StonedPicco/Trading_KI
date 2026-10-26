"""Structured JSON logging with secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

_SECRET_PATTERNS = [
    re.compile(r"(APCA-API-(?:KEY-ID|SECRET-KEY)['\"]?\s*[:=]\s*['\"]?)[^'\",\s}]+", re.I),
    re.compile(r"(x-api-key['\"]?\s*[:=]\s*['\"]?)[^'\",\s}]+", re.I),
    re.compile(r"(\"(?:key|secret)\"\s*:\s*\")[^\"]+", re.I),
    re.compile(r"(sk-ant-)[A-Za-z0-9_\-]+"),
]

_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1***", text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(payload, default=str))


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "apscheduler", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
