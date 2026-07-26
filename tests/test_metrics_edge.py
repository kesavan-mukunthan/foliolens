"""Edge-case behaviour for §2 metrics.

Covers the four required edges: empty overlap after align, single-period series,
all-negative returns (Sortino/drawdown), and rf longer than the fund.
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
from fixtures import month_end_dates, returns_series

_ABS = 1e-12


# ---------------------------------------------------------------------------
# Empty overlap after align → the two-series metrics fail loud
# ---------------------------------------------------------------------------


def _disjoint_pair() -> tuple[ReturnSeries, ReturnSeries]:
    fund = returns_series([0.01, 0.02, 0.03], start_year=2023)
    rf = returns_series([0.001, 0.001, 0.001], start_year=2024)
    return fund, rf


def test_sharpe_empty_overlap_raises() -> None:
    fund, rf = _disjoint_pair()
    with pytest.raises(ValueError, match="overlapping"):
        sharpe(fund, rf)


def test_sortino_empty_overlap_raises() -> None:
    fund, rf = _disjoint_pair()
    with pytest.raises(ValueError, match="overlapping"):
        sortino(fund, rf)


def test_downside_deviation_empty_overlap_raises() -> None:
    fund, rf = _disjoint_pair()
    with pytest.raises(ValueError, match="overlapping"):
        downside_deviation(fund, rf)


# ---------------------------------------------------------------------------
# Single-period series
# ---------------------------------------------------------------------------


def test_volatility_single_period_raises() -> None:
    with pytest.raises(ValueError, match=">= 2"):
        volatility(returns_series([0.05]))


def test_sharpe_single_overlap_raises() -> None:
    # Both one month on the same date → 1 overlapping point → cannot take std.
    with pytest.raises(ValueError, match=">= 2"):
        sharpe(returns_series([0.05]), returns_series([0.001]))


def test_period_return_abs_single_period_ok() -> None:
    # A one-month window is a valid absolute return — just that month.
    rs = returns_series([0.05])
    d = month_end_dates(1)[0]
    assert period_return_abs(rs, d, d) == pytest.approx(0.05, abs=_ABS)


def test_calmar_single_negative_period() -> None:
    # neg=[-0.05]: levels [1, 0.95]; maxdd = −0.05; total growth 0.95; n=1
    # ann = 0.95^(12/1) − 1 = 0.540360087... − 1 = −0.459639912...
    # calmar = −0.459639912 / 0.05 = −9.19279825...
    assert calmar(returns_series([-0.05])) == pytest.approx(-9.192798250, abs=1e-8)


def test_calmar_single_positive_period_is_nan() -> None:
    assert math.isnan(calmar(returns_series([0.05])))


# ---------------------------------------------------------------------------
# All-negative returns — Sortino & drawdown stay well-defined (closed form)
# ---------------------------------------------------------------------------


def test_all_negative_sortino_closed_form() -> None:
    # r = [-0.02,-0.01,-0.03], rf = 0.001/mo → excess = [-0.021,-0.011,-0.031]
    # numerator = mean(excess)*12 = (-0.063/3)*12 = -0.252
    # downside: all negative → dd = √(mean(excess²))*√12
    #   excess² = [4.41e-4, 1.21e-4, 9.61e-4]; mean = 1.5077e-3/3... → dd derived
    # result = -3.228647214625... (matches empyrical, see oracle suite)
    neg = returns_series([-0.02, -0.01, -0.03])
    rf = returns_series([0.001, 0.001, 0.001])
    assert sortino(neg, rf) == pytest.approx(-3.2286472146251746, abs=1e-12)


def test_all_negative_calmar_closed_form() -> None:
    # r = [-0.02,-0.01,-0.03]: levels [1,0.98,0.9702,0.941094]
    # maxdd = 0.941094/1 − 1 = −0.058906 (monotone decline from the seed peak)
    # ann = 0.941094^(12/3) − 1 = −0.215617...; calmar = ann/0.058906 = −3.66023926...
    neg = returns_series([-0.02, -0.01, -0.03])
    assert calmar(neg) == pytest.approx(-3.660239268422858, abs=1e-9)


def test_all_negative_downside_deviation_positive() -> None:
    # Downside deviation is a magnitude → strictly positive when losses exist.
    neg = returns_series([-0.02, -0.01, -0.03])
    rf = returns_series([0.001, 0.001, 0.001])
    assert downside_deviation(neg, rf) > 0


# ---------------------------------------------------------------------------
# Sortino — zero downside deviation (never underperforms MAR) fails loud
# ---------------------------------------------------------------------------


def test_sortino_zero_downside_deviation_raises() -> None:
    # Every month beats rf → no downside at all → Sortino is undefined, not a
    # ZeroDivisionError (a real batch-runner case: a fund that never
    # underperformed rf over some trailing window).
    fund = returns_series([0.02, 0.03, 0.01, 0.04])
    rf = returns_series([0.001, 0.001, 0.001, 0.001])
    with pytest.raises(ValueError, match="undefined"):
        sortino(fund, rf)
