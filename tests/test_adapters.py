"""§5 adapter delegation — ``*_of(investment, …)`` equals the pure function.

The adapters carry no arithmetic (``spec-analytics §5``): each reads
``investment.returns`` (rf/MAR read ``.returns`` too) and hands the series to the
pure function. So every adapter must return *exactly* what the pure function
returns on the same series — the delegation contract, asserted bit-for-bit.
"""
from __future__ import annotations

import numpy as np

from foliolens.analytics import (
    best_period,
    best_period_of,
    calmar,
    calmar_of,
    downside_deviation,
    downside_deviation_of,
    kurtosis,
    kurtosis_of,
    pct_positive,
    pct_positive_of,
    period_return_abs,
    period_return_abs_of,
    rolling_return,
    rolling_return_of,
    rolling_returns,
    rolling_returns_of,
    sharpe,
    sharpe_of,
    skew,
    skew_of,
    sortino,
    sortino_of,
    volatility,
    volatility_of,
    worst_period,
    worst_period_of,
)
from foliolens.model.value_objects import ReturnSeries
from fixtures import fixed_investment, month_end_dates, rf_investment


def _fund() -> object:
    # 6 monthly returns — enough for skew (>=3) and kurtosis (>=4).
    return fixed_investment([0.02, -0.01, 0.03, 0.00, 0.015, -0.005])


def _same_series(a: ReturnSeries, b: ReturnSeries) -> bool:
    return a.dates == b.dates and np.array_equal(a.values, b.values) and a.base == b.base


# ---------------------------------------------------------------------------
# §2 peers
# ---------------------------------------------------------------------------


def test_period_return_abs_of_delegates() -> None:
    fund = _fund()
    dts = month_end_dates(6)
    assert period_return_abs_of(fund, dts[0], dts[5]) == period_return_abs(
        fund.returns, dts[0], dts[5]
    )


def test_volatility_of_delegates() -> None:
    fund = _fund()
    assert volatility_of(fund) == volatility(fund.returns)


def test_downside_deviation_of_delegates() -> None:
    fund, rf = _fund(), rf_investment()
    assert downside_deviation_of(fund, rf) == downside_deviation(
        fund.returns, rf.returns
    )


def test_sharpe_of_delegates() -> None:
    fund, rf = _fund(), rf_investment()
    assert sharpe_of(fund, rf) == sharpe(fund.returns, rf.returns)


def test_sortino_of_delegates() -> None:
    fund, rf = _fund(), rf_investment()
    assert sortino_of(fund, rf) == sortino(fund.returns, rf.returns)


def test_calmar_of_delegates() -> None:
    fund = _fund()
    assert calmar_of(fund) == calmar(fund.returns)


# ---------------------------------------------------------------------------
# §4 peers
# ---------------------------------------------------------------------------


def test_rolling_return_of_delegates() -> None:
    fund = _fund()
    assert _same_series(rolling_return_of(fund, 3), rolling_return(fund.returns, 3))


def test_rolling_returns_of_delegates() -> None:
    fund = _fund()
    got = rolling_returns_of(fund)
    want = rolling_returns(fund.returns)
    assert got.keys() == want.keys()
    assert all(_same_series(got[k], want[k]) for k in want)


def test_pct_positive_of_delegates() -> None:
    fund = _fund()
    assert pct_positive_of(fund) == pct_positive(fund.returns)


def test_best_period_of_delegates() -> None:
    fund = _fund()
    assert best_period_of(fund) == best_period(fund.returns)


def test_worst_period_of_delegates() -> None:
    fund = _fund()
    assert worst_period_of(fund) == worst_period(fund.returns)


def test_skew_of_delegates() -> None:
    fund = _fund()
    assert skew_of(fund) == skew(fund.returns)


def test_kurtosis_of_delegates() -> None:
    fund = _fund()
    assert kurtosis_of(fund) == kurtosis(fund.returns)
