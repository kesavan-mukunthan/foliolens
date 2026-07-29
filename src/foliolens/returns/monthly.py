"""Calendar-derived month-end resampling — the sole month-end rule.

The former ``NavSeries.month_end()`` (deleted) picked the last NAV *present*
in each calendar month, with no regard for whether that month's history was
actually complete or whether the picked day was a real trading day.
:func:`month_end` fixes both: a month is only emitted once its *next* month
has begun publishing (no trailing partial month), and the emitted point is
relabelled onto the true calendar month-end date so every emitted date is a
genuine month-end, not whichever day happened to have a NAV.
"""
from __future__ import annotations

import calendar as _calendar_module
from collections import defaultdict
from datetime import date
from decimal import Decimal

import numpy as np

from foliolens.model.value_objects import NavSeries, ReturnSeries

from .calendar import TradingCalendar
from .convert import simple_return
from .frequency import Frequency


def month_end(nav: NavSeries, cal: TradingCalendar) -> NavSeries:
    """Resample ``nav`` to one point per complete calendar month.

    Month ``M`` is emitted iff (a) the fund's last NAV *within* ``M`` is dated
    **on or after** ``cal.last_trading_day(M)`` — the true last trading day of
    ``M`` — *and* (b) at least one NAV is dated in the strictly next calendar
    month (``M + 1``). Condition (b) withholds the trailing, still-accumulating
    month (no look-ahead). The emitted value is that last in-month NAV,
    relabelled onto the true calendar month-end date of ``M``, not the day the
    NAV was actually dated on.

    Condition (a) is the completeness test: a month is complete once the fund
    reached its close. The closing NAV may be dated *exactly* on the last
    trading day, or *after* it — a weekend-dated close (last trading day a
    Friday, NAV stamped the Saturday) or a fiscal-year-end (last trading day
    the 28th, NAV stamped the 31st) — either way the fund demonstrably reached
    the month's end. Only a *truncated* month, whose last NAV falls strictly
    *before* the last trading day, is rejected: the fund's history stopped
    short of the close, so the month is incomplete.

    ``cal.last_trading_day(M)`` returning ``None`` (``M`` absent from the
    derived calendar entirely) means ``M`` is not emitted.
    """
    if not nav.data:
        return NavSeries(nav.amfi_code, ())

    by_month: dict[tuple[int, int], dict[date, Decimal]] = defaultdict(dict)
    for d, v in nav.data:
        by_month[(d.year, d.month)][d] = v

    result: list[tuple[date, Decimal]] = []
    for year, month in sorted(by_month):
        last_trading_day = cal.last_trading_day(year, month)
        if last_trading_day is None:
            continue
        last_nav_date = max(by_month[(year, month)])
        if last_nav_date < last_trading_day:
            continue
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        if (next_year, next_month) not in by_month:
            continue
        calendar_month_end = date(
            year, month, _calendar_module.monthrange(year, month)[1]
        )
        result.append((calendar_month_end, by_month[(year, month)][last_nav_date]))

    return NavSeries(nav.amfi_code, tuple(result))


def _months_apart(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


def monthly_returns(nav: NavSeries, cal: TradingCalendar) -> ReturnSeries:
    """Monthly simple returns over :func:`month_end`, adjacent months only.

    A pair of consecutive ``month_end`` points that are not exactly one
    calendar month apart (a gap in the derived calendar) is dropped rather
    than emitted as a multi-month return mislabelled as monthly.
    """
    resampled = month_end(nav, cal)
    dates: list[date] = []
    values: list[float] = []
    for (prev_date, prev_nav), (curr_date, curr_nav) in zip(
        resampled.data, resampled.data[1:]
    ):
        if _months_apart(prev_date, curr_date) != 1:
            continue
        dates.append(curr_date)
        values.append(simple_return(prev_nav, curr_nav))

    return ReturnSeries(
        dates=tuple(dates),
        values=np.array(values, dtype=np.float64),
        frequency=Frequency.MONTHLY,
        base=Decimal("100"),
    )
