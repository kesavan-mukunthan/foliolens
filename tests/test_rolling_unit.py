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

from datetime import date

import numpy as np
import pytest

from foliolens.analytics.rolling import ROLLING_WINDOWS, rolling_return, rolling_returns
from foliolens.model.value_objects import ReturnSeries
from foliolens.returns.engine import _subtract_years
from foliolens.returns.frequency import Frequency
from fixtures import month_end_dates, returns_series

_ABS = 1e-12


def _fund(n: int) -> object:
    # Deterministic, non-degenerate monthly returns: -0.01, 0.00, 0.01, 0.02, 0.03 repeating.
    values = [((i % 5) - 1) / 100.0 for i in range(n)]
    return returns_series(values)


def _gapped_panel() -> ReturnSeries:
    """24 consecutive month-ends (2023-01 .. 2024-12) with two mid-series months
    removed — 2024-06-30 and 2024-07-31 — a genuine data hole *inside* the year
    trailing 2024-12-31. 22 surviving entries; the 1Y window ending 2024-12-31
    spans 12 calendar months but holds only 10 of them."""
    dates = list(month_end_dates(24))  # 2023-01-31 .. 2024-12-31
    values = [((i % 5) - 1) / 100.0 for i in range(24)]
    drop = {17, 18}  # 2024-06-30, 2024-07-31
    keep = [i for i in range(24) if i not in drop]
    return ReturnSeries(
        dates=tuple(dates[i] for i in keep),
        values=np.array([values[i] for i in keep], dtype=np.float64),
        frequency=Frequency.MONTHLY,
    )


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


# ---------------------------------------------------------------------------
# Gapped panel — the window is a calendar-date slice, not last-N observations
# ---------------------------------------------------------------------------


def test_rolling_window_after_gap_is_date_sliced_not_last_n() -> None:
    # A rolling 1Y window anchored just after a mid-year data hole must cover the
    # calendar year (<= 12 months, whatever survives), NOT reach back across the
    # hole to collect a full 12 observations spanning 14 calendar months.
    rs = _gapped_panel()
    got = rolling_return(rs, 12)
    anchor = date(2024, 8, 31)  # first month-end after the 2024-06/07 hole
    assert anchor in got.dates
    val = float(got.values[list(got.dates).index(anchor)])

    lo = _subtract_years(anchor, 1)  # 2023-08-31
    in_window = [
        float(v) for d, v in zip(rs.dates, rs.values) if lo < d <= anchor
    ]
    # 2023-09 .. 2024-08 spans 12 calendar months but the hole leaves only 10.
    assert len(in_window) == 10
    date_sliced = float(np.prod([1.0 + v for v in in_window]) - 1.0)  # 12/12 → absolute
    assert val == pytest.approx(date_sliced, abs=_ABS)

    # The old last-N slice consumes 12 observations reaching back 14 calendar
    # months (2023-07 .. 2024-08). The fix must diverge from that stretched value.
    ei = list(rs.dates).index(anchor)
    last_n = rs.values[ei - 11 : ei + 1]
    assert len(last_n) == 12
    stretched = float(np.prod(1.0 + last_n) - 1.0)
    assert val != pytest.approx(stretched, abs=_ABS)


def test_rolling_gapped_panel_contiguous_slice_unchanged() -> None:
    # An anchor whose trailing year contains no hole is unaffected: date-slicing
    # and last-N coincide (the fix is a no-op away from the gap).
    rs = _gapped_panel()
    got = rolling_return(rs, 12)
    anchor = date(2023, 12, 31)  # trailing year 2023-01 .. 2023-12 is contiguous
    val = float(got.values[list(got.dates).index(anchor)])
    ei = list(rs.dates).index(anchor)
    last_12 = rs.values[ei - 11 : ei + 1]
    contiguous = float(np.prod(1.0 + last_12) - 1.0)
    assert val == pytest.approx(contiguous, abs=_ABS)
