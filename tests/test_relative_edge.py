"""Edge-case behaviour for §6 benchmark-relative metrics.

Covers the required edges: alignment on mismatched date ranges (partial overlap
and empty overlap), the degenerate zero-tracking-error case (fund ≡ benchmark),
insufficient history (fails loud, never a silent figure), and the undefined
capture / beta cases (flat or one-signed benchmark).
"""
from __future__ import annotations

import numpy as np
import pytest

from foliolens.analytics import relative as R
from foliolens.analytics.series_ops import align
from foliolens.model.value_objects import ReturnSeries
from fixtures import returns_series


# ---------------------------------------------------------------------------
# Alignment — mismatched date ranges use only the overlap
# ---------------------------------------------------------------------------


def test_beta_uses_only_overlap_on_partial_range() -> None:
    # Fund 2023-01..2024-12 (24m); benchmark 2024-01..2025-12 (24m).
    # Overlap = the 12 months of 2024 — beta must equal beta over that slice.
    fund = returns_series([((i % 5) - 1) / 100.0 for i in range(24)], start_year=2023)
    bench = returns_series([((i % 5) - 1) / 90.0 for i in range(24)], start_year=2024)
    r, rb = align(fund, bench)
    assert len(r) == 12
    # Manual beta over the overlap == the metric's beta.
    rb_res = rb - np.mean(rb)
    manual = float(np.mean(rb_res * r) / np.mean(rb_res * rb_res))
    assert R.beta(fund, bench) == pytest.approx(manual, abs=1e-12)


def test_excess_return_dates_are_the_overlap() -> None:
    fund = returns_series([0.01, 0.02, 0.03, 0.04], start_year=2023)
    bench = returns_series([0.00, 0.01, 0.02, 0.03], start_year=2023, start_month=3)
    excess = R.excess_return(fund, bench)
    # Fund months: 2023-01..04; bench: 2023-03..06 → overlap 2023-03, 2023-04.
    assert len(excess) == 2
    assert excess.dates[0].month == 3 and excess.dates[-1].month == 4
    # Excess values are r − rb on those two shared months.
    assert excess.values[0] == pytest.approx(0.03 - 0.00, abs=1e-12)
    assert excess.values[1] == pytest.approx(0.04 - 0.01, abs=1e-12)


def _disjoint_pair() -> tuple[ReturnSeries, ReturnSeries]:
    fund = returns_series([0.01, 0.02, 0.03], start_year=2023)
    bench = returns_series([0.00, 0.01, 0.02], start_year=2025)
    return fund, bench


def test_beta_empty_overlap_raises() -> None:
    fund, bench = _disjoint_pair()
    with pytest.raises(ValueError, match="overlapping"):
        R.beta(fund, bench)


def test_excess_return_empty_overlap_raises() -> None:
    fund, bench = _disjoint_pair()
    with pytest.raises(ValueError, match="overlapping"):
        R.excess_return(fund, bench)


def test_information_ratio_empty_overlap_raises() -> None:
    fund, bench = _disjoint_pair()
    with pytest.raises(ValueError, match="overlapping"):
        R.information_ratio(fund, bench)


# ---------------------------------------------------------------------------
# Degenerate zero-tracking-error — fund ≡ benchmark
# ---------------------------------------------------------------------------


def test_tracking_error_zero_when_fund_equals_benchmark() -> None:
    # Identical series → zero active risk. TE is well-defined (0.0), not an error.
    fund = returns_series([0.01, 0.02, -0.01, 0.03])
    assert R.tracking_error(fund, fund) == pytest.approx(0.0, abs=1e-15)


def test_information_ratio_zero_te_fails_loud() -> None:
    # 0/0 active return over zero tracking error has no defined ratio → fail loud.
    fund = returns_series([0.01, 0.02, -0.01, 0.03])
    with pytest.raises(ValueError, match="tracking error is zero"):
        R.information_ratio(fund, fund)


def test_beta_of_fund_against_itself_is_one() -> None:
    fund = returns_series([0.01, 0.02, -0.01, 0.03])
    assert R.beta(fund, fund) == pytest.approx(1.0, abs=1e-12)


def test_hit_rate_zero_when_fund_equals_benchmark() -> None:
    # A tie is not a beat → the fund never strictly beats itself.
    fund = returns_series([0.01, 0.02, -0.01, 0.03])
    assert R.hit_rate(fund, fund) == 0.0


# ---------------------------------------------------------------------------
# Undefined against a flat / one-signed benchmark
# ---------------------------------------------------------------------------


def test_beta_flat_benchmark_raises() -> None:
    fund = returns_series([0.01, 0.02, -0.01, 0.03])
    flat = returns_series([0.005, 0.005, 0.005, 0.005])
    with pytest.raises(ValueError, match="variance is zero"):
        R.beta(fund, flat)


def test_up_capture_no_positive_months_raises() -> None:
    fund = returns_series([0.01, 0.02, 0.03])
    all_down = returns_series([-0.01, -0.02, -0.03])
    with pytest.raises(ValueError, match="no positive months"):
        R.up_capture(fund, all_down)


def test_down_capture_no_negative_months_raises() -> None:
    fund = returns_series([0.01, 0.02, 0.03])
    all_up = returns_series([0.01, 0.02, 0.03])
    with pytest.raises(ValueError, match="no negative months"):
        R.down_capture(fund, all_up)


# ---------------------------------------------------------------------------
# Insufficient history — the pure functions fail loud, never a silent figure
# ---------------------------------------------------------------------------


def test_beta_single_overlap_raises() -> None:
    with pytest.raises(ValueError, match=">= 2"):
        R.beta(returns_series([0.01]), returns_series([0.02]))


def test_jensens_alpha_two_points_raises() -> None:
    # Alpha's OLS standard error needs n − 2 ≥ 1, i.e. n ≥ 3.
    fund = returns_series([0.01, 0.02])
    bench = returns_series([0.00, 0.01])
    rf = returns_series([0.001, 0.001])
    with pytest.raises(ValueError, match=">= 3"):
        R.jensens_alpha(fund, bench, rf)


def test_correlation_zero_variance_raises() -> None:
    fund = returns_series([0.01, 0.01, 0.01])
    bench = returns_series([0.01, 0.02, 0.03])
    with pytest.raises(ValueError, match="zero variance"):
        R.correlation(fund, bench)
