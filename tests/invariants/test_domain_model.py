"""Invariant tests for the step-0 domain model.

Gates enforced here:
  - NavSeries: sorted ascending on construction
  - NavSeries: duplicate dates deduplicated, last entry wins
  - NavSeries: rejects non-Decimal nav values at construction
  - NavSeries.as_of: returns last available nav on-or-before the query date
  - NavSeries.month_end: picks the last trading day of each calendar month
  - NavSeries.month_end: weekend boundary — Friday nav selected when month-end is a weekend
  - NavSeries.month_end: never looks ahead into the next calendar month
  - ShareClass and Fund both satisfy ReturnSource (typed _check + runtime isinstance)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from foliolens.model.entities import Fund, ShareClass
from foliolens.model.sources import PricedSource, ReturnSource
from foliolens.model.value_objects import NavSeries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _nav(*rows: tuple[date, Decimal]) -> NavSeries:
    return NavSeries(amfi_code="999999", data=rows)


# ---------------------------------------------------------------------------
# NavSeries — sort
# ---------------------------------------------------------------------------


def test_nav_series_sorts_ascending() -> None:
    ns = _nav(
        (date(2024, 1, 5), Decimal("103.00")),
        (date(2024, 1, 2), Decimal("100.00")),
        (date(2024, 1, 3), Decimal("101.00")),
    )
    dates = [d for d, _ in ns.data]
    assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# NavSeries — dedup (last wins)
# ---------------------------------------------------------------------------


def test_nav_series_deduplicates_last_wins() -> None:
    ns = _nav(
        (date(2024, 1, 2), Decimal("100.00")),
        (date(2024, 1, 2), Decimal("100.50")),  # duplicate — last wins
    )
    assert len(ns.data) == 1
    assert ns.data[0][1] == Decimal("100.50")


# ---------------------------------------------------------------------------
# NavSeries — rejects non-Decimal
# ---------------------------------------------------------------------------


def test_nav_series_rejects_float() -> None:
    with pytest.raises(TypeError):
        NavSeries(
            amfi_code="999999",
            data=((date(2024, 1, 2), 100.0),),  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# NavSeries.as_of — last-on-or-before semantics
# ---------------------------------------------------------------------------


def test_as_of_exact_match() -> None:
    ns = _nav(
        (date(2024, 1, 2), Decimal("100.00")),
        (date(2024, 1, 5), Decimal("101.00")),
        (date(2024, 1, 10), Decimal("102.00")),
    )
    assert ns.as_of(date(2024, 1, 5)) == Decimal("101.00")


def test_as_of_between_dates_returns_previous() -> None:
    ns = _nav(
        (date(2024, 1, 2), Decimal("100.00")),
        (date(2024, 1, 5), Decimal("101.00")),
        (date(2024, 1, 10), Decimal("102.00")),
    )
    # Jan 7 has no NAV; last available is Jan 5
    assert ns.as_of(date(2024, 1, 7)) == Decimal("101.00")


def test_as_of_before_first_date_returns_none() -> None:
    ns = _nav((date(2024, 1, 2), Decimal("100.00")))
    assert ns.as_of(date(2024, 1, 1)) is None


def test_as_of_after_last_date_returns_last() -> None:
    ns = _nav(
        (date(2024, 1, 2), Decimal("100.00")),
        (date(2024, 1, 31), Decimal("105.00")),
    )
    assert ns.as_of(date(2024, 2, 15)) == Decimal("105.00")


# ---------------------------------------------------------------------------
# NavSeries.month_end — last trading day of each month
# ---------------------------------------------------------------------------


def test_month_end_picks_last_in_month() -> None:
    ns = _nav(
        (date(2024, 1, 2), Decimal("100.00")),
        (date(2024, 1, 15), Decimal("101.00")),
        (date(2024, 1, 30), Decimal("102.00")),
        (date(2024, 2, 1), Decimal("103.00")),
    )
    me = ns.month_end()
    jan_nav = next((nav for d, nav in me.data if d.month == 1), None)
    assert jan_nav == Decimal("102.00")


def test_month_end_weekend_boundary() -> None:
    # June 30 2024 is a Sunday; the last trading day is June 28 (Friday)
    ns = _nav(
        (date(2024, 6, 26), Decimal("500.00")),
        (date(2024, 6, 27), Decimal("501.00")),
        (date(2024, 6, 28), Decimal("502.00")),  # last before weekend month-end
        # no NAV on Jun 29 (Sat) or Jun 30 (Sun)
        (date(2024, 7, 1), Decimal("503.00")),
    )
    me = ns.month_end()
    jun = [(d, nav) for d, nav in me.data if d.month == 6]
    assert len(jun) == 1
    d_selected, nav_selected = jun[0]
    assert nav_selected == Decimal("502.00")
    assert d_selected == date(2024, 6, 28)


def test_month_end_no_lookahead() -> None:
    # July 1 must never appear as the June month-end entry
    ns = _nav(
        (date(2024, 1, 31), Decimal("100.00")),
        (date(2024, 2, 1), Decimal("101.00")),
    )
    me = ns.month_end()
    jan = [(d, nav) for d, nav in me.data if d.month == 1]
    assert len(jan) == 1
    assert jan[0][1] == Decimal("100.00")
    assert jan[0][0].month == 1


# ---------------------------------------------------------------------------
# ReturnSource conformance — typed check for mypy + runtime isinstance
# ---------------------------------------------------------------------------


def _check(x: ReturnSource) -> None:
    """Typed gate: mypy rejects a call if x does not structurally satisfy ReturnSource."""


def test_shareclass_satisfies_return_source() -> None:
    nav = _nav((date(2024, 1, 2), Decimal("100.00")))
    sc = ShareClass(
        id="SC001",
        amfi_code="999999",
        isin="INF999X01X99",
        plan="direct",
        option="growth",
        source=PricedSource(nav=nav),
    )
    _check(sc)
    assert isinstance(sc, ReturnSource)


def test_fund_satisfies_return_source() -> None:
    nav = _nav((date(2024, 1, 2), Decimal("100.00")))
    sc = ShareClass(
        id="SC001",
        amfi_code="999999",
        isin="INF999X01X99",
        plan="direct",
        option="growth",
        source=PricedSource(nav=nav),
    )
    fund = Fund(id="F001", name="Test Fund", representative=sc)
    _check(fund)
    assert isinstance(fund, ReturnSource)
