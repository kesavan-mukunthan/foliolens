"""Return engine.

Implements TWR (time-weighted return) and the SEBI annualisation rule:
  - period < 1 year  → absolute return (end/start − 1), never annualised
  - period ≥ 1 year  → CAGR (end/start)^(1/years) − 1
Day-count: anchored periods (1Y/3Y/5Y) use an integer-year exponent (1/n);
SI uses years = actual_days / 365. Matches AMC factsheet methodology.
Decimal throughout; no float in any stored or returned value.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, getcontext

from ..model.sources import ReturnSource
from ..model.value_objects import ReturnResult

getcontext().prec = 28

_ANCHOR_YEARS: dict[str, int] = {"1Y": 1, "3Y": 3, "5Y": 5}


def _subtract_years(d: date, n: int) -> date:
    """Subtract n calendar years; clamps Feb 29 → Feb 28 in non-leap target year."""
    try:
        return date(d.year - n, d.month, d.day)
    except ValueError:
        return date(d.year - n, 2, 28)


def period_return(
    source: ReturnSource,
    period: str,
    as_of: date,
) -> ReturnResult:
    """Compute TWR for a standard period ending on as_of.

    period: "1Y" | "3Y" | "5Y" | "SI"

    On a cashflow-free series, TWR equals the point-to-point geometric return.
    SEBI rule: actual_days < 365 → absolute; ≥ 365 → CAGR.
    CAGR exponent: 1/n for anchored periods (1Y/3Y/5Y); days/365 for SI.
    """
    series = source.value_series
    if not series.data:
        raise ValueError("empty NAV series")

    inception_date: date = series.data[0][0]

    if period == "SI":
        start_anchor = inception_date
    elif period == "1Y":
        start_anchor = _subtract_years(as_of, 1)
    elif period == "3Y":
        start_anchor = _subtract_years(as_of, 3)
    elif period == "5Y":
        start_anchor = _subtract_years(as_of, 5)
    else:
        raise ValueError(f"unknown period {period!r}; expected 1Y | 3Y | 5Y | SI")

    end_nav = series.as_of(as_of)
    start_nav = series.as_of(start_anchor)

    if end_nav is None:
        raise ValueError(f"no NAV on or before {as_of}")
    if start_nav is None:
        raise ValueError(f"no NAV on or before {start_anchor} (period {period})")

    actual_days = (as_of - start_anchor).days
    if actual_days <= 0:
        raise ValueError(f"non-positive period ({actual_days} days)")

    if actual_days < 365:
        value: Decimal = end_nav / start_nav - Decimal(1)
        method = "absolute"
    else:
        n = _ANCHOR_YEARS.get(period)
        years_d: Decimal = (
            Decimal(n) if n is not None else Decimal(actual_days) / Decimal(365)
        )
        value = (end_nav / start_nav) ** (Decimal(1) / years_d) - Decimal(1)
        method = "CAGR"

    return ReturnResult(
        value=value,
        period=period,
        start_date=start_anchor,
        end_date=as_of,
        start_nav=start_nav,
        end_nav=end_nav,
        method=method,
        days=actual_days,
    )
