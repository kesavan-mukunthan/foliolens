"""Wiring tests for Investment.returns — §1.

Gates enforced here:
  - ShareClass.returns returns ReturnSeries, values dtype == float64
  - ShareClass.returns length == month-ends in NAV − 1
  - ShareClass.returns is cached (second access returns same object)
  - Fund.returns delegates to representative.returns (same object)
  - rf fixture satisfies Investment protocol without isinstance, returns float64
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np

from foliolens.model.investments import Fund, Investment, ShareClass
from foliolens.model.sources import PricedSource
from foliolens.model.value_objects import NavSeries, ReturnSeries
from fixtures import FixedReturnsInvestment, rf_investment  # tests/ on sys.path via pytest


def _nav(*rows: tuple[date, Decimal]) -> NavSeries:
    return NavSeries(amfi_code="999999", data=rows)


def _shareclass() -> ShareClass:
    """ShareClass with daily NAVs spanning 3 calendar months → 2 month-end returns."""
    nav = _nav(
        (date(2024, 1, 31), Decimal("100.00")),
        (date(2024, 2, 29), Decimal("102.00")),
        (date(2024, 3, 28), Decimal("105.06")),
    )
    return ShareClass(
        id="SC999",
        amfi_code="999999",
        isin="INF999X01X99",
        plan="direct",
        option="growth",
        source=PricedSource(nav=nav),
    )


# ---------------------------------------------------------------------------
# ShareClass.returns
# ---------------------------------------------------------------------------


def test_shareclass_returns_type() -> None:
    assert isinstance(_shareclass().returns, ReturnSeries)


def test_shareclass_returns_dtype_float64() -> None:
    assert _shareclass().returns.values.dtype == np.float64


def test_shareclass_returns_length_is_month_ends_minus_one() -> None:
    sc = _shareclass()
    month_end_count = len(sc.source.nav.month_end())
    assert len(sc.returns) == month_end_count - 1


def test_shareclass_returns_cached() -> None:
    sc = _shareclass()
    assert sc.returns is sc.returns  # cached_property — same object on second access


# ---------------------------------------------------------------------------
# Fund.returns
# ---------------------------------------------------------------------------


def test_fund_returns_delegates_to_representative() -> None:
    sc = _shareclass()
    fund = Fund(id="F999", name="Test Fund", representative=sc)
    assert fund.returns is fund.representative.returns


# ---------------------------------------------------------------------------
# rf fixture — isinstance-free protocol check + dtype + no network
# ---------------------------------------------------------------------------


def _check_investment(x: Investment) -> None:
    """Typed gate: mypy rejects this call if x doesn't structurally satisfy Investment."""


def test_rf_fixture_protocol_check() -> None:
    fixture = rf_investment()
    _check_investment(fixture)  # isinstance-free — structural mypy check only
    assert isinstance(fixture, FixedReturnsInvestment)
    assert fixture.benchmark is None
    assert fixture.holdings == ()


def test_rf_fixture_returns_dtype_float64() -> None:
    assert rf_investment().returns.values.dtype == np.float64


def test_rf_fixture_no_network() -> None:
    # conftest._no_network blocks all socket calls; this must not raise
    fixture = rf_investment()
    _ = fixture.returns
