"""Own-vs-oracle acceptance for §6 benchmark-relative metrics.

Oracle = empyrical-reloaded (alpha, beta, excess_sharpe, up/down capture) with
periodicity declared **monthly**, plus ``scipy.stats.linregress`` as an
independent OLS oracle for the Jensen's-alpha t-stat (statsmodels is not in the
locked toolchain, so the t-stat is pinned to a hand-computable OLS fixture — the
intercept / intercept-stderr of the excess-on-excess regression). Tolerance is
the spec-analytics gate: own↔oracle relative ≤ 1e-6 on frozen synthetic fixture
``ReturnSeries``. No real index levels enter here (analytics decoupling rule +
IIM-A/TRI redistribution discipline).

The rf fixture is a **constant** monthly rate, which is what lets empyrical's
scalar-rf ``alpha`` coincide with the excess-on-excess OLS: with constant rf the
raw beta empyrical uses equals the excess-regression slope, so one β serves both.
"""
from __future__ import annotations

import empyrical
import numpy as np
from scipy import stats

from foliolens.analytics import relative as R
from foliolens.analytics.series_ops import align
from foliolens.model.value_objects import ReturnSeries
from fixtures import returns_series, rf_investment

_REL = 1e-6

# Deterministic 36-month fixtures. Benchmark is strongly (not perfectly)
# correlated with the fund — a real regression (β ≈ 1.22, R² ≈ 0.96) with genuine
# up- and down-market months so the capture ratios are non-trivial.
_FUND_VALUES = [((i % 5) - 1) / 100.0 for i in range(36)]
_BENCH_VALUES = [((i % 5) - 1) / 100.0 * 0.8 + ((i % 4) - 1.5) / 500.0 for i in range(36)]

# The rf fixture's constant monthly rate (6% p.a.), as a scalar for empyrical.
_RF_MONTHLY = (1.06) ** (1 / 12) - 1


def _fund() -> ReturnSeries:
    return returns_series(_FUND_VALUES)


def _bench() -> ReturnSeries:
    return returns_series(_BENCH_VALUES)


def _rel_close(own: float, oracle: float) -> bool:
    return abs(own - oracle) <= _REL * abs(oracle)


# ---------------------------------------------------------------------------
# Beta — empyrical.beta (raw, rf-independent)
# ---------------------------------------------------------------------------


def test_beta_vs_oracle() -> None:
    fund, bench = _fund(), _bench()
    r, rb = align(fund, bench)
    assert _rel_close(R.beta(fund, bench), float(empyrical.beta(r, rb)))


# ---------------------------------------------------------------------------
# Jensen's alpha — empyrical.alpha (annualised); t-stat vs scipy OLS
# ---------------------------------------------------------------------------


def test_alpha_vs_oracle() -> None:
    fund, bench = _fund(), _bench()
    rf = rf_investment().returns
    r, rb = align(fund, bench)
    oracle = empyrical.alpha(r, rb, risk_free=_RF_MONTHLY, period="monthly")
    assert _rel_close(R.jensens_alpha(fund, bench, rf).alpha, float(oracle))


def test_alpha_tstat_vs_ols_oracle() -> None:
    # OLS of excess fund on excess benchmark; t-stat = intercept / intercept_stderr.
    fund, bench = _fund(), _bench()
    rf = rf_investment().returns
    r, rb = align(fund, bench)
    y = r - _RF_MONTHLY
    x = rb - _RF_MONTHLY
    lr = stats.linregress(x, y)
    result = R.jensens_alpha(fund, bench, rf)
    # Periodic intercept and its t-stat both match the independent OLS fit.
    assert _rel_close(result.alpha_periodic, float(lr.intercept))
    assert _rel_close(result.t_stat, float(lr.intercept / lr.intercept_stderr))
    assert result.n == 36


def test_alpha_tstat_closed_form() -> None:
    # Fully hand-computed OLS SE (no scipy) — the fixture the spec names.
    fund, bench = _fund(), _bench()
    rf = rf_investment().returns
    r, rb = align(fund, bench)
    y = r - _RF_MONTHLY
    x = rb - _RF_MONTHLY
    n = len(x)
    x_mean, y_mean = float(np.mean(x)), float(np.mean(y))
    sxx = float(np.sum((x - x_mean) ** 2))
    slope = float(np.sum((x - x_mean) * (y - y_mean)) / sxx)
    intercept = y_mean - slope * x_mean
    resid = y - (intercept + slope * x)
    s = np.sqrt(float(np.sum(resid**2)) / (n - 2))
    se = s * np.sqrt(1.0 / n + x_mean**2 / sxx)
    assert _rel_close(R.jensens_alpha(fund, bench, rf).t_stat, intercept / se)


# ---------------------------------------------------------------------------
# Information ratio — empyrical.excess_sharpe × √12 (annualised)
# ---------------------------------------------------------------------------


def test_information_ratio_vs_oracle() -> None:
    fund, bench = _fund(), _bench()
    r, rb = align(fund, bench)
    oracle = float(empyrical.excess_sharpe(r, rb)) * np.sqrt(12)
    assert _rel_close(R.information_ratio(fund, bench), oracle)


def test_tracking_error_matches_active_volatility() -> None:
    # TE is §2 volatility over the excess series (its own oracle-pinned definition).
    from foliolens.analytics.metrics import volatility

    fund, bench = _fund(), _bench()
    excess = R.excess_return(fund, bench)
    assert _rel_close(R.tracking_error(fund, bench), volatility(excess))


# ---------------------------------------------------------------------------
# Up / down capture — empyrical.up_capture / down_capture (monthly)
# ---------------------------------------------------------------------------


def test_up_capture_vs_oracle() -> None:
    fund, bench = _fund(), _bench()
    r, rb = align(fund, bench)
    oracle = empyrical.up_capture(r, rb, period="monthly")
    assert _rel_close(R.up_capture(fund, bench), float(oracle))


def test_down_capture_vs_oracle() -> None:
    fund, bench = _fund(), _bench()
    r, rb = align(fund, bench)
    oracle = empyrical.down_capture(r, rb, period="monthly")
    assert _rel_close(R.down_capture(fund, bench), float(oracle))


# ---------------------------------------------------------------------------
# R² — squared Pearson correlation (composition oracle)
# ---------------------------------------------------------------------------


def test_r_squared_vs_correlation_oracle() -> None:
    fund, bench = _fund(), _bench()
    r, rb = align(fund, bench)
    oracle = float(np.corrcoef(r, rb)[0, 1]) ** 2
    assert _rel_close(R.r_squared(fund, bench), oracle)


# ---------------------------------------------------------------------------
# rf longer than the fund — align uses only the overlap; oracle sees the slice
# ---------------------------------------------------------------------------


def test_beta_vs_oracle_benchmark_longer_than_fund() -> None:
    # Fund spans 30 months; benchmark spans 36. align → 30-month overlap; feed
    # empyrical the same 30-month slices so the two agree on identical inputs.
    fund = returns_series(_FUND_VALUES[:30])
    bench = _bench()  # 36 months, same start
    r, rb = align(fund, bench)
    assert len(r) == 30
    assert _rel_close(R.beta(fund, bench), float(empyrical.beta(r, rb)))
