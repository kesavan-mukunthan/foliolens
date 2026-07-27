"""Month-end + frequency invariants — fixture fund 108466 via DataAccess.

(a) every monthly date is a genuine calendar month-end
(b) 2026-06 is absent (its trading history stops mid-month, on 2026-06-19,
    with no NAV yet published in July 2026 — a still-accumulating month)
(c) adjacent monthly dates are exactly one calendar month apart
(d) aligning two mismatched-frequency ``ReturnSeries`` raises

RED (this commit): (a)-(c) run over the OLD path (``NavSeries.month_end()``
+ ``to_returns``), which picks whatever NAV happens to exist per calendar
month with no regard for completeness or the true month-end date. (d)
exercises ``series_ops.align_dated``, which does not yet know about
``Frequency`` at all. Step 1.7 repoints (a)-(c) at the new calendar-derived
``monthly_returns`` path once it lands, at which point all four go green.
"""
from __future__ import annotations

import calendar as _calendar_module
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from foliolens.analytics.series_ops import align_dated
from foliolens.data_access import DataAccess
from foliolens.model.value_objects import ReturnSeries
from foliolens.returns.convert import to_returns
from foliolens.returns.frequency import Frequency

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "nav_snapshots"
_AMFI_CODE = "108466"


def _monthly_dates() -> tuple[date, ...]:
    da = DataAccess(FIXTURES)
    nav = da.load_nav_series(_AMFI_CODE)
    return to_returns(nav.month_end(), frequency=Frequency.MONTHLY).dates


def _is_calendar_month_end(d: date) -> bool:
    return d.day == _calendar_module.monthrange(d.year, d.month)[1]


def _months_apart(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


def test_every_monthly_date_is_a_calendar_month_end() -> None:
    dates = _monthly_dates()
    assert dates, "expected a non-empty monthly panel for fixture fund 108466"
    assert all(_is_calendar_month_end(d) for d in dates)


def test_trailing_partial_month_is_absent() -> None:
    # 2026-06 has NAV only through 2026-06-19 with no July 2026 NAV yet — a
    # still-accumulating month, never emitted.
    dates = _monthly_dates()
    assert not any(d.year == 2026 and d.month == 6 for d in dates)


def test_adjacent_monthly_dates_are_one_month_apart() -> None:
    dates = _monthly_dates()
    assert len(dates) >= 2
    for prev_date, curr_date in zip(dates, dates[1:]):
        assert _months_apart(prev_date, curr_date) == 1


def test_align_dated_rejects_frequency_mismatch() -> None:
    monthly = ReturnSeries(
        dates=(date(2024, 1, 31), date(2024, 2, 29)),
        values=np.array([0.01, 0.02], dtype=np.float64),
        frequency=Frequency.MONTHLY,
    )
    daily = ReturnSeries(
        dates=(date(2024, 1, 31), date(2024, 2, 29)),
        values=np.array([0.001, 0.002], dtype=np.float64),
        frequency=Frequency.DAILY,
    )
    with pytest.raises(ValueError, match="frequency mismatch"):
        align_dated(monthly, daily)
