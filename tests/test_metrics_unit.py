"""Closed-form unit tests for §2 metrics on FixedReturnsInvestment.

Every expected value is computed by hand in the comment above its assertion;
the constants were derived from those formulas (independent of the oracle,
which is checked separately in test_metrics_oracle.py).

Base series r = [0.02, -0.01, 0.03, 0.00] on month-ends Jan..Apr 2023.
rf = constant 0.001 / month over the same dates.
"""
from __future__ import annotations

import math

import pytest

from foliolens.analytics.metrics import (
    calmar,
    downside_deviation,
    period_return_abs,
    sharpe,
    sortino,
    volatility,
)
from foliolens.model.value_objects import ReturnSeries
from fixtures import FixedReturnsInvestment, fixed_investment, month_end_dates, returns_series

_ABS = 1e-12


def _fund() -> FixedReturnsInvestment:
    return fixed_investment([0.02, -0.01, 0.03, 0.00])


def _rf() -> ReturnSeries:
    return returns_series([0.001, 0.001, 0.001, 0.001])


# ---------------------------------------------------------------------------
# period_return_abs — Π(1+r) − 1 over a between-slice
# ---------------------------------------------------------------------------


def test_period_return_abs_full_window() -> None:
    # (1.02)(0.99)(1.03)(1.00) − 1 = 1.040094 − 1 = 0.040094
    # (Apr = 0.00, so the 4-month window coincides with the Jan..Mar window.)
    rs = _fund().returns
    dts = month_end_dates(4)
    got = period_return_abs(rs, dts[0], dts[3])
    assert got == pytest.approx(0.040094, abs=_ABS)


def test_period_return_abs_three_month_window() -> None:
    # Jan..Mar only: (1.02)(0.99)(1.03) − 1 = 1.040094 − 1 = 0.040094
    rs = _fund().returns
    dts = month_end_dates(4)
    got = period_return_abs(rs, dts[0], dts[2])
    assert got == pytest.approx(0.040094, abs=_ABS)


def test_period_return_abs_one_month_window() -> None:
    # Single month Feb: just −0.01.
    rs = _fund().returns
    dts = month_end_dates(4)
    got = period_return_abs(rs, dts[1], dts[1])
    assert got == pytest.approx(-0.01, abs=_ABS)


def test_period_return_abs_empty_window_raises() -> None:
    rs = _fund().returns
    with pytest.raises(ValueError, match="no returns in window"):
        period_return_abs(rs, month_end_dates(1, 2030)[0], month_end_dates(1, 2030)[0])


# ---------------------------------------------------------------------------
# volatility — std(ddof=1) × √12
# ---------------------------------------------------------------------------


def test_volatility_closed_form() -> None:
    # mean = 0.01; deviations [0.01,-0.02,0.02,-0.01]; Σd² = 0.0010
    # sample var = 0.0010/3 = 0.000333...; std = 0.018257418583...
    # × √12 (=3.4641016151) = 0.063245553203...
    got = volatility(_fund().returns)
    assert got == pytest.approx(0.06324555320336758, abs=_ABS)


# ---------------------------------------------------------------------------
# downside_deviation — √(mean(min(excess,0)²)) × √12, MAR = rf series
# ---------------------------------------------------------------------------


def test_downside_deviation_closed_form() -> None:
    # excess = r − rf = [0.019, -0.011, 0.029, -0.001]
    # min(·,0) = [0, -0.011, 0, -0.001]; squares [0, 1.21e-4, 0, 1e-6]
    # mean over N=4 = 1.22e-4/4 = 3.05e-5; sqrt = 0.005522680509...
    # × √12 = 0.019131126469...
    got = downside_deviation(_fund().returns, _rf())
    assert got == pytest.approx(0.01913112646970899, abs=_ABS)


# ---------------------------------------------------------------------------
# sharpe — mean(excess)/std(excess,ddof=1) × √12
# ---------------------------------------------------------------------------


def test_sharpe_closed_form() -> None:
    # excess = [0.019,-0.011,0.029,-0.001]; mean = 0.009
    # std(ddof=1) = 0.018257418583 (deviations unchanged by the constant shift)
    # sharpe = 0.009/0.018257418583 × √12 = 1.707629936490...
    got = sharpe(_fund().returns, _rf())
    assert got == pytest.approx(1.7076299364909246, abs=_ABS)


# ---------------------------------------------------------------------------
# sortino — (mean(excess) × 12) / downside_deviation, MAR = rf
# ---------------------------------------------------------------------------


def test_sortino_closed_form() -> None:
    # numerator = 0.009 × 12 = 0.108; denominator = 0.019131126469 (above)
    # sortino = 0.108 / 0.019131126469 = 5.645250433684...
    got = sortino(_fund().returns, _rf())
    assert got == pytest.approx(5.6452504336846205, abs=_ABS)


# ---------------------------------------------------------------------------
# calmar — annualised return / |max drawdown| over the return series
# ---------------------------------------------------------------------------


def test_calmar_closed_form() -> None:
    # levels (peak seeded at 1): [1, 1.02, 1.0098, 1.040094, 1.040094]
    # max drawdown = 1.0098/1.02 − 1 = −0.01 (the Feb dip from the Jan peak)
    # total growth = 1.040094; n=4 → ann = 1.040094^(12/4) − 1 = 0.125169038769...
    # calmar = 0.125169038769 / 0.01 = 12.516903876915...
    got = calmar(_fund().returns)
    assert got == pytest.approx(12.516903876915103, abs=1e-9)


def test_calmar_no_drawdown_is_nan() -> None:
    # Monotonically rising series never draws down → no finite Calmar.
    rs = returns_series([0.01, 0.02, 0.03])
    assert math.isnan(calmar(rs))
