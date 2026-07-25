"""Own-vs-oracle acceptance for §4 rolling returns — the spec-analytics §4 gate.

Oracle = ``pandas.Series.rolling(window).apply`` — an independent windowing
mechanism (pandas' own sliding-window machinery, not our positional loop)
computing the same annualised-CAGR formula. This cross-checks the *window
placement and date-stamping*, not just the formula, since a windowing bug
(off-by-one, wrong anchor date) would show up as a length or alignment
mismatch against pandas' independently-implemented rolling apply. Tolerance
matches the analytics convention: own↔oracle relative ≤ 1e-6.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from foliolens.analytics.rolling import ROLLING_WINDOWS, rolling_return
from fixtures import returns_series

_REL = 1e-6

# 72 months (6 years) so all three standard windows (1Y/3Y/5Y) produce points.
_FUND_VALUES = [((i % 7) - 2) / 100.0 for i in range(72)]


def _rel_close(own: np.ndarray, oracle: np.ndarray) -> bool:
    return bool(np.all(np.abs(own - oracle) <= _REL * np.abs(oracle)))


def _pandas_rolling_oracle(values: list[float], dates: tuple, window: int) -> pd.Series:
    s = pd.Series(values, index=list(dates))

    def _annualised(window_values: np.ndarray) -> float:
        compounded = np.prod(1.0 + window_values) - 1.0
        return float((1.0 + compounded) ** (12.0 / window) - 1.0)

    return s.rolling(window).apply(_annualised, raw=True).dropna()


def test_rolling_return_1y_vs_pandas_oracle() -> None:
    rs = returns_series(_FUND_VALUES)
    window = ROLLING_WINDOWS["1Y"]
    got = rolling_return(rs, window)
    oracle = _pandas_rolling_oracle(_FUND_VALUES, rs.dates, window)
    assert list(got.dates) == list(oracle.index)
    assert _rel_close(got.values, oracle.to_numpy())


def test_rolling_return_3y_vs_pandas_oracle() -> None:
    rs = returns_series(_FUND_VALUES)
    window = ROLLING_WINDOWS["3Y"]
    got = rolling_return(rs, window)
    oracle = _pandas_rolling_oracle(_FUND_VALUES, rs.dates, window)
    assert list(got.dates) == list(oracle.index)
    assert _rel_close(got.values, oracle.to_numpy())


def test_rolling_return_5y_vs_pandas_oracle() -> None:
    rs = returns_series(_FUND_VALUES)
    window = ROLLING_WINDOWS["5Y"]
    got = rolling_return(rs, window)
    oracle = _pandas_rolling_oracle(_FUND_VALUES, rs.dates, window)
    assert list(got.dates) == list(oracle.index)
    assert _rel_close(got.values, oracle.to_numpy())
