"""Pure-function invariant tests for §4 rolling returns.

No published/oracle counterpart for the *windowing* behaviour itself (that's
covered against pandas in ``test_rolling_oracle.py``); these pin the structural
invariants the spec's acceptance rule names directly:

- window count = n_months − window + 1 when history suffices
- each rolling point equals the direct computation on that slice
- date stamps = window-end month-ends
- a window longer than available history emits no point (never padded, never
  a partial window)
"""
from __future__ import annotations

import numpy as np
import pytest

from foliolens.analytics.rolling import ROLLING_WINDOWS, rolling_return, rolling_returns
from fixtures import month_end_dates, returns_series

_ABS = 1e-12


def _fund(n: int) -> object:
    # Deterministic, non-degenerate monthly returns: -0.01, 0.00, 0.01, 0.02, 0.03 repeating.
    values = [((i % 5) - 1) / 100.0 for i in range(n)]
    return returns_series(values)


# ---------------------------------------------------------------------------
# Window longer than history → empty panel (never padded, never partial)
# ---------------------------------------------------------------------------


def test_window_longer_than_history_emits_no_point() -> None:
    rs = _fund(6)
    got = rolling_return(rs, 12)
    assert len(got) == 0
    assert got.dates == ()
    assert got.values.shape == (0,)


def test_window_equal_to_history_emits_exactly_one_point() -> None:
    rs = _fund(12)
    got = rolling_return(rs, 12)
    assert len(got) == 1
    assert got.dates[0] == month_end_dates(12)[-1]


# ---------------------------------------------------------------------------
# Window count = n_months − window + 1 when history suffices
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n,window", [(36, 12), (36, 36), (60, 36), (100, 60)])
def test_window_count(n: int, window: int) -> None:
    rs = _fund(n)
    got = rolling_return(rs, window)
    assert len(got) == n - window + 1


def test_rolling_returns_bundles_all_three_windows_independently() -> None:
    # 40 months: 1Y has 29 points, 3Y has 5 points, 5Y is too short → empty.
    rs = _fund(40)
    panel = rolling_returns(rs)
    assert set(panel) == {"1Y", "3Y", "5Y"}
    assert len(panel["1Y"]) == 40 - 12 + 1
    assert len(panel["3Y"]) == 40 - 36 + 1
    assert len(panel["5Y"]) == 0


def test_rolling_windows_labels() -> None:
    assert ROLLING_WINDOWS == {"1Y": 12, "3Y": 36, "5Y": 60}


# ---------------------------------------------------------------------------
# Each rolling point equals the direct computation on that slice
# ---------------------------------------------------------------------------


def test_each_point_matches_direct_computation_on_its_slice() -> None:
    rs = _fund(48)
    window = 12
    got = rolling_return(rs, window)
    for i, (d, v) in enumerate(zip(got.dates, got.values)):
        start_i = i
        end_i = i + window - 1
        slice_values = rs.values[start_i : end_i + 1]
        compounded = float(np.prod(1.0 + slice_values) - 1.0)
        expected = (1.0 + compounded) ** (12.0 / window) - 1.0
        assert d == rs.dates[end_i]
        assert v == pytest.approx(expected, abs=_ABS)


def test_one_year_window_reduces_to_absolute_return() -> None:
    # 12-month window: annualised CAGR must equal the plain compounded return
    # (SEBI boundary — 1 year is where absolute and CAGR coincide).
    rs = _fund(12)
    got = rolling_return(rs, 12)
    compounded = float(np.prod(1.0 + rs.values) - 1.0)
    assert got.values[0] == pytest.approx(compounded, abs=_ABS)


# ---------------------------------------------------------------------------
# Date stamps = window-end month-ends
# ---------------------------------------------------------------------------


def test_date_stamps_are_window_end_month_ends() -> None:
    rs = _fund(24)
    got = rolling_return(rs, 12)
    expected_dates = month_end_dates(24)[11:]
    assert got.dates == expected_dates


# ---------------------------------------------------------------------------
# Misc invariants
# ---------------------------------------------------------------------------


def test_invalid_window_months_raises() -> None:
    rs = _fund(12)
    with pytest.raises(ValueError, match="window_months"):
        rolling_return(rs, 0)


def test_base_carries_through() -> None:
    rs = _fund(24)
    got = rolling_return(rs, 12)
    assert got.base == rs.base
