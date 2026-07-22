"""Own-vs-oracle acceptance for §2 metrics — the spec-analytics §2 gate.

Oracle = empyrical-reloaded with periodicity declared **monthly** (annualisation
factor 12). Tolerance is the value recorded in spec-analytics §2: own↔oracle
relative ≤ 1e-6 on frozen fixture ReturnSeries. No published or live series
enters here (analytics decoupling rule).
"""
from __future__ import annotations

import empyrical

from foliolens.analytics.metrics import (
    calmar,
    downside_deviation,
    sharpe,
    sortino,
    volatility,
)
from foliolens.analytics.series_ops import align
from foliolens.model.value_objects import ReturnSeries
from fixtures import rf_investment, returns_series

_REL = 1e-6

# Deterministic 36-month fixture: -0.01, 0.00, 0.01, 0.02, 0.03 repeating.
# Positive drift (so ratios are comfortably non-zero) with real negative months
# (so a drawdown exists and downside deviation is non-trivial).
_FUND_VALUES = [((i % 5) - 1) / 100.0 for i in range(36)]


def _fund() -> ReturnSeries:
    return returns_series(_FUND_VALUES)


def _rel_close(own: float, oracle: float) -> bool:
    return abs(own - oracle) <= _REL * abs(oracle)


# ---------------------------------------------------------------------------
# Single-argument metrics vs empyrical (fund and rf share all 36 dates)
# ---------------------------------------------------------------------------


def test_volatility_vs_oracle() -> None:
    rs = _fund()
    oracle = empyrical.annual_volatility(rs.values, period="monthly")
    assert _rel_close(volatility(rs), float(oracle))


def test_calmar_vs_oracle() -> None:
    rs = _fund()
    oracle = empyrical.calmar_ratio(rs.values, period="monthly")
    assert _rel_close(calmar(rs), float(oracle))


# ---------------------------------------------------------------------------
# rf-taking metrics vs empyrical (rf passed as the aligned per-period array)
# ---------------------------------------------------------------------------


def test_downside_deviation_vs_oracle() -> None:
    rs = _fund()
    rf = rf_investment().returns
    r, f = align(rs, rf)  # 36 common months
    oracle = empyrical.downside_risk(r, required_return=f, period="monthly")
    assert _rel_close(downside_deviation(rs, rf), float(oracle))


def test_sharpe_vs_oracle() -> None:
    rs = _fund()
    rf = rf_investment().returns
    r, f = align(rs, rf)
    oracle = empyrical.sharpe_ratio(r, risk_free=f, period="monthly")
    assert _rel_close(sharpe(rs, rf), float(oracle))


def test_sortino_vs_oracle() -> None:
    rs = _fund()
    rf = rf_investment().returns
    r, f = align(rs, rf)
    oracle = empyrical.sortino_ratio(r, required_return=f, period="monthly")
    assert _rel_close(sortino(rs, rf), float(oracle))


# ---------------------------------------------------------------------------
# rf longer than fund — align uses only the overlap; oracle sees the same slice
# ---------------------------------------------------------------------------


def test_sharpe_vs_oracle_rf_longer_than_fund() -> None:
    # Fund spans 30 months; rf spans 36. align → 30-month overlap; feed empyrical
    # the same 30-month slices so the two agree on identical inputs.
    fund = returns_series(_FUND_VALUES[:30])
    rf = rf_investment().returns  # 36 months, same start
    r, f = align(fund, rf)
    assert len(r) == 30
    oracle = empyrical.sharpe_ratio(r, risk_free=f, period="monthly")
    assert _rel_close(sharpe(fund, rf), float(oracle))


def test_all_negative_sortino_vs_oracle() -> None:
    # All-negative months: Sortino must stay finite and negative and match.
    neg = returns_series([-0.02, -0.01, -0.03, -0.015, -0.005])
    rf = rf_investment().returns
    r, f = align(neg, rf)
    oracle = empyrical.sortino_ratio(r, required_return=f, period="monthly")
    own = sortino(neg, rf)
    assert own < 0
    assert _rel_close(own, float(oracle))


def test_all_negative_calmar_vs_oracle() -> None:
    neg = returns_series([-0.02, -0.01, -0.03, -0.015, -0.005])
    oracle = empyrical.calmar_ratio(neg.values, period="monthly")
    assert _rel_close(calmar(neg), float(oracle))
