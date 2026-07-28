"""Wiring tests for Investment.returns(freq) — §1.

Gates enforced here:
  - ShareClass.returns(MONTHLY) returns ReturnSeries, values dtype == float64
  - ShareClass.returns(MONTHLY) length matches the calendar-derived monthly panel
  - ShareClass.returns(MONTHLY) is the same object on every access (eager panel, no recompute)
  - Fund.returns(MONTHLY) delegates to representative.returns(MONTHLY) (same object)
  - rf fixture satisfies Investment protocol without isinstance, returns float64
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np

from foliolens.model.investments import Fund, Investment, share_class_from_nav
from foliolens.model.value_objects import NavSeries, ReturnSeries
from foliolens.returns.frequency import Frequency
from fixtures import FixedReturnsInvestment, rf_investment, synthetic_calendar  # tests/ on sys.path via pytest


def _nav(*rows: tuple[date, Decimal]) -> NavSeries:
    return NavSeries(amfi_code="999999", data=rows)


def _shareclass():
    """ShareClass with daily NAVs spanning 3 calendar months -> 2 month-end returns.

    The NAV series (and so the calendar, built from its own dates) carries one
    extra point in April — the month after the last intended month (March) —
    so the M+1 rule actually emits March; without it, March would never be
    emitted (the still-accumulating trailing month is never emitted).
    """
    nav = _nav(
        (date(2024, 1, 31), Decimal("100.00")),
        (date(2024, 2, 29), Decimal("102.00")),
        (date(2024, 3, 28), Decimal("105.06")),
        (date(2024, 4, 1), Decimal("105.50")),
    )
    cal = synthetic_calendar([d for d, _ in nav.data])
    return share_class_from_nav(
        "SC999", nav, cal, isin="INF999X01X99", plan="direct", option="growth"
    )


# ---------------------------------------------------------------------------
# ShareClass.returns(MONTHLY)
# ---------------------------------------------------------------------------


def test_shareclass_returns_type() -> None:
    assert isinstance(_shareclass().returns(Frequency.MONTHLY), ReturnSeries)


def test_shareclass_returns_dtype_float64() -> None:
    assert _shareclass().returns(Frequency.MONTHLY).values.dtype == np.float64


def test_shareclass_returns_length_is_month_ends_minus_one() -> None:
    sc = _shareclass()
    # 3 emitted month-ends (Jan/Feb/Mar, thanks to the extra April calendar
    # date) -> 2 consecutive-month returns.
    assert len(sc.returns(Frequency.MONTHLY)) == 2


def test_shareclass_returns_is_stable_across_accesses() -> None:
    sc = _shareclass()
    # Eager panel: every access is a dict lookup of the same precomputed object.
    assert sc.returns(Frequency.MONTHLY) is sc.returns(Frequency.MONTHLY)


# ---------------------------------------------------------------------------
# Fund.returns(MONTHLY)
# ---------------------------------------------------------------------------


def test_fund_returns_delegates_to_representative() -> None:
    sc = _shareclass()
    fund = Fund(id="F999", name="Test Fund", representative=sc)
    assert fund.returns(Frequency.MONTHLY) is fund.representative.returns(Frequency.MONTHLY)


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
    assert rf_investment().returns(Frequency.MONTHLY).values.dtype == np.float64


def test_rf_fixture_no_network() -> None:
    # conftest._no_network blocks all socket calls; this must not raise
    fixture = rf_investment()
    _ = fixture.returns(Frequency.MONTHLY)
