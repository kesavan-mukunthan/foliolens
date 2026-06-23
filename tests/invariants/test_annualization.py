"""Invariants: SEBI annualisation rule — absolute < 1Y, CAGR ≥ 1Y, day-count = days/365."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from foliolens.model.sources import PricedSource
from foliolens.model.value_objects import NavSeries
from foliolens.returns.engine import period_return


def _source(*rows: tuple[date, Decimal]) -> PricedSource:
    return PricedSource(nav=NavSeries(amfi_code="999999", data=rows))


def test_sub_year_is_absolute() -> None:
    """A 6-month period returns (end/start − 1), not annualised."""
    start = date(2024, 1, 2)
    end = date(2024, 7, 2)
    start_nav = Decimal("100")
    end_nav = Decimal("106")
    source = _source((start, start_nav), (end, end_nav))

    result = period_return(source, "SI", end)  # inception to 6 months later

    expected = end_nav / start_nav - Decimal(1)
    assert result.method == "absolute"
    assert result.value == expected


def test_over_year_is_cagr() -> None:
    """A 3Y period returns (end/start)^(1/years) − 1."""
    start = date(2020, 1, 2)
    end = date(2023, 1, 2)
    start_nav = Decimal("100")
    end_nav = Decimal("133.1")  # ~10% CAGR over 3Y
    source = _source((start, start_nav), (end, end_nav))

    result = period_return(source, "3Y", end)

    actual_days = (end - start).days
    years_d = Decimal(actual_days) / Decimal(365)
    expected = (end_nav / start_nav) ** (Decimal(1) / years_d) - Decimal(1)

    assert result.method == "CAGR"
    assert result.value == expected


def test_one_year_boundary() -> None:
    """Exactly 1Y (365 days) uses the CAGR path; CAGR == absolute at exactly 1.0 years."""
    start = date(2023, 1, 2)
    end = date(2024, 1, 2)
    actual_days = (end - start).days
    # 2023 is not a leap year, so Jan 2 → Jan 2 = 365 days
    assert actual_days == 365, f"expected 365 days, got {actual_days}"

    start_nav = Decimal("100")
    end_nav = Decimal("115")
    source = _source((start, start_nav), (end, end_nav))

    result = period_return(source, "1Y", end)

    assert result.method == "CAGR"
    # at exactly 1Y, CAGR = (end/start)^(1/1) - 1 = absolute return
    absolute = end_nav / start_nav - Decimal(1)
    assert result.value == absolute


def test_daycount_is_365() -> None:
    """years == actual_days / 365 (AMFI convention, not 360 or 252)."""
    # start must align with the 3Y anchor: _subtract_years(2024-01-02, 3) = 2021-01-02
    start = date(2021, 1, 2)
    end = date(2024, 1, 2)
    start_nav = Decimal("100")
    end_nav = Decimal("150")
    source = _source((start, start_nav), (end, end_nav))

    result = period_return(source, "3Y", end)

    actual_days = (end - start).days
    years_expected = Decimal(actual_days) / Decimal(365)
    expected_value = (end_nav / start_nav) ** (Decimal(1) / years_expected) - Decimal(1)

    assert result.days == actual_days
    assert result.value == expected_value


def test_sub_year_uses_absolute_not_annualised() -> None:
    """Explicit sanity: 6-month absolute return is NOT the same as annualised."""
    start = date(2024, 1, 2)
    end = date(2024, 7, 2)
    start_nav = Decimal("100")
    end_nav = Decimal("105")
    source = _source((start, start_nav), (end, end_nav))

    result = period_return(source, "SI", end)

    actual_days = (end - start).days
    absolute = end_nav / start_nav - Decimal(1)
    years_d = Decimal(actual_days) / Decimal(365)
    annualised = (end_nav / start_nav) ** (Decimal(1) / years_d) - Decimal(1)

    assert result.method == "absolute"
    assert result.value == absolute
    assert result.value != annualised  # 5% absolute ≠ ~10.28% annualised
