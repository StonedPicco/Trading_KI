from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.core.market_time import (
    MarketPhase,
    is_trading_day,
    market_phase,
    previous_trading_day,
    session_times,
    trading_days_back,
)


def test_regular_and_extended_phases_in_edt() -> None:
    # 2026-10-22 is EDT (UTC-4): regular session 13:30–20:00 UTC
    assert market_phase(datetime(2026, 10, 22, 9, 0, tzinfo=UTC)) == MarketPhase.PRE
    assert market_phase(datetime(2026, 10, 22, 13, 30, tzinfo=UTC)) == MarketPhase.REGULAR
    assert market_phase(datetime(2026, 10, 22, 19, 59, tzinfo=UTC)) == MarketPhase.REGULAR
    assert market_phase(datetime(2026, 10, 22, 20, 0, tzinfo=UTC)) == MarketPhase.AFTER
    assert market_phase(datetime(2026, 10, 23, 0, 1, tzinfo=UTC)) == MarketPhase.CLOSED


def test_dst_shift_after_november() -> None:
    # 2026-11-02 is EST (UTC-5): open at 14:30 UTC
    st = session_times(date(2026, 11, 2))
    assert st is not None
    assert st.open == datetime(2026, 11, 2, 14, 30, tzinfo=UTC)


def test_holiday_and_early_close() -> None:
    assert not is_trading_day(date(2026, 11, 26))  # Thanksgiving
    st = session_times(date(2026, 11, 27))  # day after Thanksgiving: 13:00 ET close
    assert st is not None and st.is_early_close
    assert st.close == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    assert market_phase(datetime(2026, 11, 27, 18, 30, tzinfo=UTC)) == MarketPhase.AFTER


def test_weekend_closed_and_previous_trading_day() -> None:
    assert market_phase(datetime(2026, 10, 24, 15, 0, tzinfo=UTC)) == MarketPhase.CLOSED
    assert previous_trading_day(date(2026, 10, 26)) == date(2026, 10, 23)


def test_trading_days_back() -> None:
    assert trading_days_back(date(2026, 10, 23), 1) == date(2026, 10, 23)
    assert trading_days_back(date(2026, 10, 23), 5) == date(2026, 10, 19)


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError):
        market_phase(datetime(2026, 10, 22, 15, 0))
