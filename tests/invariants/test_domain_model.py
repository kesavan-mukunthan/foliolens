"""Invariant tests for the step-0 domain model.

Gates enforced here:
  - NavSeries: sorted ascending on construction
  - NavSeries: duplicate dates deduplicated, last entry wins
  - NavSeries: rejects non-Decimal nav values at construction
  - NavSeries.as_of: returns last available nav on-or-before the query date
  - ShareClass and Fund both satisfy ReturnSource (typed _check + runtime isinstance)

Calendar-derived month-end resampling (last trading day of each month, weekend
boundary, no-lookahead, strict M+1 completeness) lives in
``returns/monthly.month_end`` and is covered by ``tests/invariants/test_month_end.py``
— ``NavSeries.month_end()`` itself was deleted.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from foliolens.model.investments import Fund, share_class_from_nav
from foliolens.model.sources import ReturnSource
from foliolens.model.value_objects import NavSeries
from fixtures import synthetic_calendar


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
# ReturnSource conformance — typed check for mypy + runtime isinstance
# ---------------------------------------------------------------------------


def _check(x: ReturnSource) -> None:
    """Typed gate: mypy rejects a call if x does not structurally satisfy ReturnSource."""


def _minimal_shareclass():
    nav = _nav(
        (date(2024, 1, 2), Decimal("100.00")),
        (date(2024, 2, 2), Decimal("101.00")),
    )
    cal = synthetic_calendar([d for d, _ in nav.data])
    return share_class_from_nav(
        "SC001", nav, cal, isin="INF999X01X99", plan="direct", option="growth"
    )


def test_shareclass_satisfies_return_source() -> None:
    sc = _minimal_shareclass()
    _check(sc)
    assert isinstance(sc, ReturnSource)


def test_fund_satisfies_return_source() -> None:
    sc = _minimal_shareclass()
    fund = Fund(id="F001", name="Test Fund", representative=sc)
    _check(fund)
    assert isinstance(fund, ReturnSource)
