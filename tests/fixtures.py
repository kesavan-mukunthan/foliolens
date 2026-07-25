"""Test-only synthetic investments satisfying the Investment protocol without I/O."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

import numpy as np

from foliolens.model.investments import SeriesInvestment, ShareClass
from foliolens.model.sources import PricedSource
from foliolens.model.value_objects import NavSeries, ReturnSeries

# The return-space Investment (id + materialised ReturnSeries, no NAV, no I/O)
# now lives in the model as SeriesInvestment. Tests use it directly; the old
# fixture-local name is kept as an alias so existing imports and isinstance
# checks continue to hold.
FixedReturnsInvestment = SeriesInvestment


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def month_end_dates(
    n: int, start_year: int = 2023, start_month: int = 1
) -> tuple[date, ...]:
    """``n`` consecutive calendar month-end dates from ``start_year/start_month``."""
    return tuple(
        _month_end(
            start_year + (start_month - 1 + i) // 12,
            (start_month - 1 + i) % 12 + 1,
        )
        for i in range(n)
    )


def returns_series(
    values: object, start_year: int = 2023, start_month: int = 1
) -> ReturnSeries:
    """Build a monthly ``ReturnSeries`` from ``values`` on consecutive month-ends."""
    arr = np.asarray(values, dtype=np.float64)
    return ReturnSeries(
        dates=month_end_dates(len(arr), start_year, start_month),
        values=arr,
    )


def fixed_investment(
    values: object, start_year: int = 2023, start_month: int = 1, id: str = "test"
) -> FixedReturnsInvestment:
    """A ``FixedReturnsInvestment`` wrapping a monthly ``ReturnSeries``."""
    return FixedReturnsInvestment(
        id=id,
        returns_series=returns_series(values, start_year, start_month),
    )


def daily_nav(
    values: object, start: date = date(2024, 1, 1), amfi_code: str = "888888"
) -> NavSeries:
    """A daily (consecutive-day) Decimal ``NavSeries`` from ``values``.

    Consecutive calendar days keep the series unambiguously daily (no month-end
    resampling): the §3 drawdown family reads the raw daily NAV so an intra-month
    trough is captured. Values become ``Decimal`` — NAV is a figure of record.
    """
    data = tuple(
        (start + timedelta(days=i), Decimal(str(v))) for i, v in enumerate(values)  # type: ignore[call-overload]
    )
    return NavSeries(amfi_code=amfi_code, data=data)


def daily_shareclass(
    values: object, start: date = date(2024, 1, 1), id: str = "SCDAILY"
) -> ShareClass:
    """A ``ShareClass`` priced on a daily NAV series — for the §3 daily adapters."""
    nav = daily_nav(values, start)
    return ShareClass(
        id=id,
        amfi_code=nav.amfi_code,
        isin="INF888X01X88",
        plan="direct",
        option="growth",
        source=PricedSource(nav=nav),
    )


def rf_investment() -> FixedReturnsInvestment:
    """Risk-free fixture: 36 monthly period-end dates, constant 6% p.a. monthly return."""
    monthly_r = (1.06) ** (1 / 12) - 1
    dates = tuple(
        _month_end(2023 + (m - 1) // 12, (m - 1) % 12 + 1) for m in range(1, 37)
    )
    values = np.full(36, monthly_r, dtype=np.float64)
    return FixedReturnsInvestment(
        id="rf-fixture",
        returns_series=ReturnSeries(dates=dates, values=values),
    )
