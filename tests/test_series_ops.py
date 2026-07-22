"""Unit tests for analytics.series_ops — align + between.

These are the join/slice primitives every §2 metric composes; closed-form
expectations are computed by hand in comments.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from foliolens.analytics.series_ops import align, between
from foliolens.model.value_objects import ReturnSeries
from fixtures import month_end_dates, returns_series  # tests/ on sys.path


# ---------------------------------------------------------------------------
# align — inner join on dates
# ---------------------------------------------------------------------------


def test_align_identical_dates() -> None:
    # Same 3 month-ends → full overlap, values returned position-for-position.
    a = returns_series([0.01, 0.02, 0.03])
    b = returns_series([0.10, 0.20, 0.30])
    av, bv = align(a, b)
    assert np.allclose(av, [0.01, 0.02, 0.03])
    assert np.allclose(bv, [0.10, 0.20, 0.30])
    assert av.dtype == np.float64 and bv.dtype == np.float64


def test_align_partial_overlap() -> None:
    # a: Jan,Feb,Mar 2023 ; b: Feb,Mar,Apr 2023 → overlap = {Feb, Mar}.
    a = returns_series([0.01, 0.02, 0.03], start_month=1)  # Jan,Feb,Mar
    b = returns_series([0.20, 0.30, 0.40], start_month=2)  # Feb,Mar,Apr
    av, bv = align(a, b)
    # a's Feb=0.02, Mar=0.03 ; b's Feb=0.20, Mar=0.30
    assert np.allclose(av, [0.02, 0.03])
    assert np.allclose(bv, [0.20, 0.30])


def test_align_rf_longer_than_fund() -> None:
    # rf spans 36 months; fund spans 3 → overlap is exactly the fund's 3 months,
    # so a longer rf is a no-op beyond the fund window.
    fund = returns_series([0.05, 0.06, 0.07], start_year=2023, start_month=1)
    rf = returns_series([0.004] * 36, start_year=2023, start_month=1)
    fv, rv = align(fund, rf)
    assert len(fv) == 3
    assert np.allclose(fv, [0.05, 0.06, 0.07])
    assert np.allclose(rv, [0.004, 0.004, 0.004])


def test_align_empty_overlap() -> None:
    # Disjoint date ranges → no common date → empty arrays (never raises here;
    # metrics decide whether empty is an error).
    a = returns_series([0.01, 0.02], start_year=2023, start_month=1)  # Jan,Feb 23
    b = returns_series([0.01, 0.02], start_year=2024, start_month=1)  # Jan,Feb 24
    av, bv = align(a, b)
    assert av.shape == (0,)
    assert bv.shape == (0,)


def test_align_preserves_ascending_order() -> None:
    a = returns_series([0.01, 0.02, 0.03, 0.04])
    b = returns_series([0.05, 0.06, 0.07, 0.08])
    av, _ = align(a, b)
    assert np.array_equal(av, np.array([0.01, 0.02, 0.03, 0.04]))


# ---------------------------------------------------------------------------
# between — inclusive searchsorted slice
# ---------------------------------------------------------------------------


def test_between_inclusive_bounds() -> None:
    # Jan..May 2023; slice [Feb, Apr] → Feb,Mar,Apr (inclusive both ends).
    rs = returns_series([0.01, 0.02, 0.03, 0.04, 0.05])
    dts = month_end_dates(5)
    sliced = between(rs, dts[1], dts[3])
    assert sliced.dates == dts[1:4]
    assert np.allclose(sliced.values, [0.02, 0.03, 0.04])


def test_between_wide_bounds_returns_all() -> None:
    rs = returns_series([0.01, 0.02, 0.03])
    sliced = between(rs, date(2000, 1, 1), date(2100, 1, 1))
    assert len(sliced) == 3
    assert np.allclose(sliced.values, [0.01, 0.02, 0.03])


def test_between_single_point() -> None:
    rs = returns_series([0.01, 0.02, 0.03])
    dts = month_end_dates(3)
    sliced = between(rs, dts[1], dts[1])
    assert sliced.dates == (dts[1],)
    assert np.allclose(sliced.values, [0.02])


def test_between_window_outside_history_is_empty() -> None:
    rs = returns_series([0.01, 0.02, 0.03], start_year=2023)
    sliced = between(rs, date(2030, 1, 1), date(2030, 12, 31))
    assert len(sliced) == 0
    assert isinstance(sliced, ReturnSeries)


def test_between_start_after_end_raises() -> None:
    rs = returns_series([0.01, 0.02, 0.03])
    with pytest.raises(ValueError, match="after end"):
        between(rs, date(2023, 3, 31), date(2023, 1, 31))


def test_between_carries_base() -> None:
    rs = returns_series([0.01, 0.02, 0.03])
    dts = month_end_dates(3)
    assert between(rs, dts[0], dts[2]).base == rs.base
