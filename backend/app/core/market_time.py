"""US equity market calendar and session helpers.

All timestamps in the system are timezone-aware UTC. Session logic is evaluated in
America/New_York using the XNYS calendar (holidays, early closes).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

NY = ZoneInfo("America/New_York")
PRE_MARKET_OPEN = time(4, 0)
AFTER_HOURS_CLOSE = time(20, 0)


class MarketPhase(StrEnum):
    PRE = "pre_market"
    REGULAR = "regular"
    AFTER = "after_hours"
    CLOSED = "closed"


@dataclass(frozen=True)
class SessionTimes:
    day: date
    pre_open: datetime
    open: datetime
    close: datetime
    after_close: datetime

    @property
    def is_early_close(self) -> bool:
        return self.close.astimezone(NY).time() < time(16, 0)


@lru_cache(maxsize=1)
def _calendar() -> xcals.ExchangeCalendar:
    return xcals.get_calendar("XNYS")


def ensure_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        raise ValueError("naive datetime not allowed; use timezone-aware UTC")
    return ts.astimezone(UTC)


def ny_date(ts: datetime) -> date:
    return ensure_utc(ts).astimezone(NY).date()


def is_trading_day(day: date) -> bool:
    return bool(_calendar().is_session(pd.Timestamp(day)))


def session_times(day: date) -> SessionTimes | None:
    cal = _calendar()
    label = pd.Timestamp(day)
    if not cal.is_session(label):
        return None
    open_ = cal.session_open(label).to_pydatetime().astimezone(UTC)
    close = cal.session_close(label).to_pydatetime().astimezone(UTC)
    pre_open = datetime.combine(day, PRE_MARKET_OPEN, tzinfo=NY).astimezone(UTC)
    # After-hours runs until 20:00 ET, also on early-close days.
    after_close = datetime.combine(day, AFTER_HOURS_CLOSE, tzinfo=NY).astimezone(UTC)
    return SessionTimes(
        day=day, pre_open=pre_open, open=open_, close=close, after_close=after_close
    )


def market_phase(ts: datetime) -> MarketPhase:
    ts = ensure_utc(ts)
    st = session_times(ny_date(ts))
    if st is None:
        return MarketPhase.CLOSED
    if st.pre_open <= ts < st.open:
        return MarketPhase.PRE
    if st.open <= ts < st.close:
        return MarketPhase.REGULAR
    if st.close <= ts < st.after_close:
        return MarketPhase.AFTER
    return MarketPhase.CLOSED


def trading_days(start: date, end: date) -> list[date]:
    """Inclusive list of XNYS sessions between start and end."""
    cal = _calendar()
    first = max(pd.Timestamp(start), cal.first_session)
    last = min(pd.Timestamp(end), cal.last_session)
    if first > last:
        return []
    return [d.date() for d in cal.sessions_in_range(first, last)]


def previous_trading_day(day: date) -> date:
    probe = day - timedelta(days=1)
    for _ in range(15):
        if is_trading_day(probe):
            return probe
        probe -= timedelta(days=1)
    raise ValueError(f"no trading day found before {day}")


def trading_days_back(end: date, n: int) -> date:
    """Return the session date ``n`` trading days before ``end`` (inclusive count)."""
    cal = _calendar()
    label = pd.Timestamp(end)
    if not cal.is_session(label):
        label = cal.date_to_session(label, direction="previous")
    idx = cal.sessions.get_loc(label)
    return cal.sessions[max(0, idx - n + 1)].date()


_fixed_now: datetime | None = None


def set_fixed_now(ts: datetime | None) -> None:
    """Freeze the application clock (tests, backtests, demo replays). ``None`` unfreezes."""
    global _fixed_now
    _fixed_now = ensure_utc(ts) if ts is not None else None


def utcnow() -> datetime:
    return _fixed_now or datetime.now(tz=UTC)
