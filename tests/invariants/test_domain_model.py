"""Invariant tests for the step-0 domain model.

Gates enforced here:
  - NavSeries: sorted ascending on construction
  - NavSeries: duplicate dates deduplicated (last wins)
  - NavSeries: nav values are Decimal; float is rejected
  - NavSeries.month_end: picks last available NAV on or before month-end
  - NavSeries.month_end: weekend boundary — Friday nav selected when month-end is Sunday
  - NavSeries.month_end: no look-ahead — July NAV never appears as June month-end
  - ShareClass satisfies ReturnSource: static typed-function check + runtime isinstance
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from foliolens.model.entities import ShareClass
from foliolens.model.sources import PricedSource, ReturnSource
from foliolens.model.value_objects import NavSeries


# ---------------------------------------------------------------------------
# NavSeries — sort
# ---------------------------------------------------------------------------


def test_nav_series_sorts_ascending() -> None:
    ns = NavSeries(
        amfi_code="999999",
        data=(
            (date(2024, 1, 5), Decimal("103.00")),
            (date(2024, 1, 2), Decimal("100.00")),
            (date(2024, 1, 3), Decimal("101.00")),
        ),
    )
    dates = [d for d, _ in ns.data]
    assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# NavSeries — dedup
# ---------------------------------------------------------------------------


def test_nav_series_deduplicates() -> None:
    ns = NavSeries(
        amfi_code="999999",
        data=(
            (date(2024, 1, 2), Decimal("100.00")),
            (date(2024, 1, 2), Decimal("100.50")),  # duplicate — last wins
        ),
    )
    assert len(ns.data) == 1
    assert ns.data[0][1] == Decimal("100.50")


# ---------------------------------------------------------------------------
# NavSeries — Decimal invariant
# ---------------------------------------------------------------------------


def test_nav_series_keeps_decimal() -> None:
    nav = Decimal("123.456789")
    ns = NavSeries(amfi_code="999999", data=((date(2024, 1, 2), nav),))
    stored = ns.data[0][1]
    assert isinstance(stored, Decimal)
    assert stored == nav


def test_nav_series_rejects_float() -> None:
    with pytest.raises(TypeError):
        NavSeries(
            amfi_code="999999",
            data=((date(2024, 1, 2), 100.0),),  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# NavSeries.month_end — basic selection
# ---------------------------------------------------------------------------


def test_month_end_picks_last_in_month() -> None:
    ns = NavSeries(
        amfi_code="999999",
        data=(
            (date(2024, 1, 2), Decimal("100.00")),
            (date(2024, 1, 15), Decimal("101.00")),
            (date(2024, 1, 30), Decimal("102.00")),
            (date(2024, 2, 1), Decimal("103.00")),
        ),
    )
    me = ns.month_end()
    jan_nav = next((nav for d, nav in me.data if d.month == 1), None)
    assert jan_nav == Decimal("102.00")


# ---------------------------------------------------------------------------
# NavSeries.month_end — weekend boundary
# ---------------------------------------------------------------------------


def test_month_end_weekend_boundary() -> None:
    # June 30 2024 is a Sunday; last available NAV is June 28 (Friday)
    ns = NavSeries(
        amfi_code="999999",
        data=(
            (date(2024, 6, 26), Decimal("500.00")),
            (date(2024, 6, 27), Decimal("501.00")),
            (date(2024, 6, 28), Decimal("502.00")),  # last before weekend month-end
            # no NAV on Jun 29 (Sat) or Jun 30 (Sun)
            (date(2024, 7, 1), Decimal("503.00")),
        ),
    )
    me = ns.month_end()
    jun = [(d, nav) for d, nav in me.data if d.month == 6]
    assert len(jun) == 1
    d_selected, nav_selected = jun[0]
    assert nav_selected == Decimal("502.00")
    assert d_selected == date(2024, 6, 28)


# ---------------------------------------------------------------------------
# NavSeries.month_end — no look-ahead
# ---------------------------------------------------------------------------


def test_month_end_no_lookahead() -> None:
    ns = NavSeries(
        amfi_code="999999",
        data=(
            (date(2024, 1, 31), Decimal("100.00")),
            (date(2024, 2, 1), Decimal("101.00")),  # must NOT appear as Jan month-end
        ),
    )
    me = ns.month_end()
    jan = [(d, nav) for d, nav in me.data if d.month == 1]
    assert len(jan) == 1
    assert jan[0][1] == Decimal("100.00")
    assert jan[0][0].month == 1  # selected date is in January, not February


# ---------------------------------------------------------------------------
# ShareClass satisfies ReturnSource
# ---------------------------------------------------------------------------


def _assert_is_return_source(s: ReturnSource) -> None:
    """Typed function: mypy rejects a call here if s does not satisfy ReturnSource."""


def test_shareclass_satisfies_return_source() -> None:
    nav = NavSeries(
        amfi_code="999999",
        data=((date(2024, 1, 2), Decimal("100.00")),),
    )
    sc = ShareClass(
        id="SC001",
        amfi_code="999999",
        isin="INF999X01X99",
        plan="direct",
        option="growth",
        source=PricedSource(nav=nav),
    )
    _assert_is_return_source(sc)  # mypy: ShareClass must satisfy ReturnSource structurally
    assert isinstance(sc, ReturnSource)  # runtime check via @runtime_checkable
