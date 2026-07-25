"""Closed-form / edge-case tests for §4 distribution statistics.

``pct_positive`` / ``best_period`` / ``worst_period`` are hand-computed;
``skew`` / ``kurtosis`` closed-form values are cross-checked against the
oracle in ``test_distribution_oracle.py`` — here we pin the edge cases
(minimum sample size, empty series).
"""
from __future__ import annotations

import pytest

from foliolens.analytics.distribution import (
    best_period,
    kurtosis,
    pct_positive,
    skew,
    worst_period,
)
from fixtures import returns_series

_ABS = 1e-12


# ---------------------------------------------------------------------------
# pct_positive / best_period / worst_period — hand-computed
# ---------------------------------------------------------------------------


def test_pct_positive_closed_form() -> None:
    # [0.02, -0.01, 0.03, 0.00, -0.02]: strictly positive → 0.02, 0.03 → 2/5
    rs = returns_series([0.02, -0.01, 0.03, 0.00, -0.02])
    assert pct_positive(rs) == pytest.approx(0.4, abs=_ABS)


def test_pct_positive_zero_does_not_count() -> None:
    rs = returns_series([0.00, 0.00, 0.01])
    assert pct_positive(rs) == pytest.approx(1.0 / 3.0, abs=_ABS)


def test_pct_positive_all_negative() -> None:
    rs = returns_series([-0.01, -0.02, -0.03])
    assert pct_positive(rs) == pytest.approx(0.0, abs=_ABS)


def test_best_worst_period() -> None:
    rs = returns_series([0.02, -0.01, 0.05, -0.03, 0.01])
    assert best_period(rs) == pytest.approx(0.05, abs=_ABS)
    assert worst_period(rs) == pytest.approx(-0.03, abs=_ABS)


def test_best_worst_single_period() -> None:
    rs = returns_series([0.04])
    assert best_period(rs) == pytest.approx(0.04, abs=_ABS)
    assert worst_period(rs) == pytest.approx(0.04, abs=_ABS)


# ---------------------------------------------------------------------------
# Empty-series edges — fail loud, matching the §2/§3 pattern
# ---------------------------------------------------------------------------


def test_pct_positive_empty_raises() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        pct_positive(returns_series([]))


def test_best_period_empty_raises() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        best_period(returns_series([]))


def test_worst_period_empty_raises() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        worst_period(returns_series([]))


# ---------------------------------------------------------------------------
# skew / kurtosis — minimum sample size edges
# ---------------------------------------------------------------------------


def test_skew_needs_at_least_three() -> None:
    with pytest.raises(ValueError, match=">= 3"):
        skew(returns_series([0.01, 0.02]))


def test_skew_exactly_three_is_defined() -> None:
    got = skew(returns_series([0.01, 0.02, -0.03]))
    assert got == got  # not NaN


def test_kurtosis_needs_at_least_four() -> None:
    with pytest.raises(ValueError, match=">= 4"):
        kurtosis(returns_series([0.01, 0.02, -0.03]))


def test_kurtosis_exactly_four_is_defined() -> None:
    got = kurtosis(returns_series([0.01, 0.02, -0.03, 0.015]))
    assert got == got  # not NaN


def test_symmetric_series_skew_near_zero() -> None:
    # Symmetric about the mean → skew should be (near) zero.
    rs = returns_series([-0.02, -0.01, 0.0, 0.01, 0.02])
    assert skew(rs) == pytest.approx(0.0, abs=1e-9)
