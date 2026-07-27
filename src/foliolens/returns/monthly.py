"""Calendar-derived month-end resampling — the successor to ``NavSeries.month_end``.

``NavSeries.month_end()`` (``model/value_objects.py``) picks the last NAV
*present* in each calendar month, with no regard for whether that month's
history is actually complete or whether the picked day was a real trading
day. :func:`month_end` fixes both: a month is only emitted once its *next*
month has begun publishing (no trailing partial month), and the emitted
point is relabelled onto the true calendar month-end date so every emitted
date is a genuine month-end, not whichever day happened to have a NAV.
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

    Month ``M`` is emitted iff ``nav`` carries a NAV dated exactly
    ``cal.last_trading_day(M)`` *and* at least one NAV dated in the strictly
    next calendar month (``M + 1``) — the trailing, still-accumulating month
    is never emitted (no look-ahead-free partial month). The emitted point is
    relabelled onto the true calendar month-end date of ``M``, not the trading
    day the NAV was actually dated on.
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
        nav_on_last_trading_day = by_month[(year, month)].get(last_trading_day)
        if nav_on_last_trading_day is None:
            continue
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        if (next_year, next_month) not in by_month:
            continue
        calendar_month_end = date(
            year, month, _calendar_module.monthrange(year, month)[1]
        )
        result.append((calendar_month_end, nav_on_last_trading_day))

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
