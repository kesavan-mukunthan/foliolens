"""Own-vs-oracle acceptance for §4 distribution statistics — skew / kurtosis.

Oracle = ``pandas.Series.skew()`` / ``.kurt()`` and, independently,
``scipy.stats.skew(bias=False)`` / ``scipy.stats.kurtosis(fisher=True,
bias=False)`` — two separate library implementations of the same
bias-corrected sample estimators. Tolerance matches the analytics convention:
own↔oracle relative ≤ 1e-6. ``pct_positive``/``best_period``/``worst_period``
have no library oracle (they are closed-form reductions) — covered as
invariant tests in ``test_distribution_unit.py``.
"""
from __future__ import annotations

import pandas as pd
from scipy import stats

from foliolens.analytics.distribution import kurtosis, skew
from fixtures import returns_series

_REL = 1e-6

# Deterministic 24-month fixture with real asymmetry (a few larger negative
# months) so skew/kurtosis are non-trivial, not (near-)zero on a symmetric set.
_FUND_VALUES = [
    0.02, -0.01, 0.03, -0.04, 0.01, 0.015, -0.02, 0.025,
    -0.06, 0.03, 0.01, -0.015, 0.02, 0.005, -0.03, 0.04,
    0.01, -0.02, 0.03, -0.01, 0.015, -0.05, 0.02, 0.01,
]


def _rel_close(own: float, oracle: float) -> bool:
    return abs(own - oracle) <= _REL * abs(oracle)


def test_skew_vs_pandas_oracle() -> None:
    rs = returns_series(_FUND_VALUES)
    oracle = pd.Series(_FUND_VALUES).skew()
    assert _rel_close(skew(rs), float(oracle))


def test_skew_vs_scipy_oracle() -> None:
    rs = returns_series(_FUND_VALUES)
    oracle = stats.skew(_FUND_VALUES, bias=False)
    assert _rel_close(skew(rs), float(oracle))


def test_kurtosis_vs_pandas_oracle() -> None:
    rs = returns_series(_FUND_VALUES)
    oracle = pd.Series(_FUND_VALUES).kurt()
    assert _rel_close(kurtosis(rs), float(oracle))


def test_kurtosis_vs_scipy_oracle() -> None:
    rs = returns_series(_FUND_VALUES)
    oracle = stats.kurtosis(_FUND_VALUES, fisher=True, bias=False)
    assert _rel_close(kurtosis(rs), float(oracle))
