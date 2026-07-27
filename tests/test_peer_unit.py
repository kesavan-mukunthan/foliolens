"""Hand-computed invariant tests for §7 peer / cross-sectional machinery.

No library oracle for the ranking *rule* itself (percentile = fraction at or
below, nulls excluded); these pin it against figures worked out by hand on a
5-fund fixture that deliberately includes an all-null fund and a partial-history
fund — the two edge shapes §7 names. Aggregate correctness against numpy lives
in ``test_peer_oracle.py``.

Fixture (percentile_ranks / category_aggregate):
    A=0.10  B=0.20  C=0.30  D=0.05  E=None   (N = 4 non-null)
"""
from __future__ import annotations

import numpy as np
import pytest

from foliolens.analytics.peer import (
    category_aggregate,
    percentile_ranks,
    rank_history,
)
from foliolens.model.value_objects import ReturnSeries
from foliolens.returns.frequency import Frequency
from fixtures import month_end_dates, returns_series

_ABS = 1e-12

_VALUES: dict[str, float | None] = {"A": 0.10, "B": 0.20, "C": 0.30, "D": 0.05, "E": None}


# ---------------------------------------------------------------------------
# percentile_ranks — hand-computed, higher_is_better both ways
# ---------------------------------------------------------------------------


def test_percentile_ranks_higher_is_better() -> None:
    # N = 4 (E excluded). Fraction at or below, ×100:
    #   D=0.05 → 1/4=25, A=0.10 → 2/4=50, B=0.20 → 3/4=75, C=0.30 → 4/4=100.
    got = percentile_ranks(_VALUES, higher_is_better=True)
    assert got["D"] == pytest.approx(25.0, abs=_ABS)
    assert got["A"] == pytest.approx(50.0, abs=_ABS)
    assert got["B"] == pytest.approx(75.0, abs=_ABS)
    assert got["C"] == pytest.approx(100.0, abs=_ABS)
    assert got["E"] is None


def test_percentile_ranks_lower_is_better_inverts() -> None:
    # Fraction at or above, ×100 — the lowest value now tops the ranking:
    #   D=0.05 → 100, A=0.10 → 75, B=0.20 → 50, C=0.30 → 25.
    got = percentile_ranks(_VALUES, higher_is_better=False)
    assert got["D"] == pytest.approx(100.0, abs=_ABS)
    assert got["A"] == pytest.approx(75.0, abs=_ABS)
    assert got["B"] == pytest.approx(50.0, abs=_ABS)
    assert got["C"] == pytest.approx(25.0, abs=_ABS)
    assert got["E"] is None


def test_percentile_ranks_preserves_every_input_key() -> None:
    got = percentile_ranks(_VALUES, higher_is_better=True)
    assert set(got) == set(_VALUES)


def test_null_excluded_from_universe_count() -> None:
    # Adding a second null must NOT change any surviving fund's rank: nulls are
    # out of the denominator entirely (never imputed as a mid-scale value).
    with_extra_null = {**_VALUES, "F": None}
    base = percentile_ranks(_VALUES, higher_is_better=True)
    got = percentile_ranks(with_extra_null, higher_is_better=True)
    for fid in ("A", "B", "C", "D"):
        assert got[fid] == pytest.approx(base[fid], abs=_ABS)
    assert got["E"] is None and got["F"] is None


def test_nan_treated_as_null() -> None:
    # A NaN metric (e.g. Calmar with no drawdown) is missing, not a real figure:
    # excluded like None, and it does not perturb its peers' counts.
    vals: dict[str, float | None] = {"A": 0.10, "B": 0.20, "N": float("nan")}
    got = percentile_ranks(vals, higher_is_better=True)
    assert got["N"] is None
    assert got["A"] == pytest.approx(50.0, abs=_ABS)  # N = 2, not 3
    assert got["B"] == pytest.approx(100.0, abs=_ABS)


def test_all_null_cohort_all_none() -> None:
    got = percentile_ranks({"A": None, "B": None}, higher_is_better=True)
    assert got == {"A": None, "B": None}


def test_empty_cohort_empty_result() -> None:
    assert percentile_ranks({}, higher_is_better=True) == {}


def test_single_non_null_fund_ranks_100() -> None:
    got = percentile_ranks({"A": 0.42, "B": None}, higher_is_better=True)
    assert got["A"] == pytest.approx(100.0, abs=_ABS)
    assert got["B"] is None


def test_ties_share_a_rank() -> None:
    # Two funds at the same value are both "at or below" each other → same rank.
    vals: dict[str, float | None] = {"X": 0.10, "Y": 0.10, "Z": 0.30}
    got = percentile_ranks(vals, higher_is_better=True)
    assert got["X"] == pytest.approx(got["Y"], abs=_ABS)
    # N = 3: X,Y each count {X,Y} → 2/3; Z counts all → 3/3.
    assert got["X"] == pytest.approx(200.0 / 3.0, abs=_ABS)
    assert got["Z"] == pytest.approx(100.0, abs=_ABS)


# ---------------------------------------------------------------------------
# percentile_ranks — valid distribution
# ---------------------------------------------------------------------------


def test_ranks_form_a_valid_distribution() -> None:
    got = percentile_ranks(_VALUES, higher_is_better=True)
    present = [r for r in got.values() if r is not None]
    n = len(present)
    # Every rank is a k/N×100 multiple in (0, 100]; the top fund reaches exactly
    # 100 and, with distinct values, the ranks are the full {1..N}/N ladder.
    assert all(0.0 < r <= 100.0 for r in present)
    assert max(present) == pytest.approx(100.0, abs=_ABS)
    expected_ladder = {(k + 1) / n * 100.0 for k in range(n)}
    assert sorted(present) == pytest.approx(sorted(expected_ladder), abs=_ABS)


# ---------------------------------------------------------------------------
# category_aggregate — count over non-nulls; empty cohort representable
# ---------------------------------------------------------------------------


def test_category_aggregate_count_is_non_nulls() -> None:
    agg = category_aggregate(_VALUES)
    assert agg.count == 4  # E excluded


def test_category_aggregate_empty_cohort() -> None:
    agg = category_aggregate({"A": None, "B": None})
    assert agg.count == 0
    assert agg.median is None and agg.q1 is None and agg.q3 is None


def test_category_aggregate_quartile_ordering() -> None:
    agg = category_aggregate(_VALUES)
    assert agg.q1 is not None and agg.median is not None and agg.q3 is not None
    assert agg.q1 <= agg.median <= agg.q3


# ---------------------------------------------------------------------------
# rank_history — per-date cohort, young-fund exclusion from early dates
# ---------------------------------------------------------------------------


def _panels() -> dict[str, ReturnSeries]:
    """5-fund panels over 5 month-ends.

    A/B/C span all 5 dates; D (young) starts at d3; E is empty (all-null — a
    fund too young for even one panel point).
    """
    dates5 = month_end_dates(5)
    return {
        "A": returns_series([0.01, 0.01, 0.01, 0.01, 0.01]),
        "B": returns_series([0.02, 0.02, 0.02, 0.02, 0.02]),
        "C": returns_series([0.03, 0.03, 0.03, 0.03, 0.03]),
        "D": ReturnSeries(
            dates=dates5[2:], values=np.array([0.005, 0.04, 0.04]), frequency=Frequency.MONTHLY
        ),
        "E": ReturnSeries(dates=(), values=np.array([], dtype=np.float64), frequency=Frequency.MONTHLY),
    }


def test_rank_history_young_fund_excluded_from_early_dates() -> None:
    hist = rank_history(_panels(), higher_is_better=True)
    dates5 = month_end_dates(5)
    # D's short panel only reaches d3–d5; it appears in no earlier ranking.
    assert hist["D"].dates == dates5[2:]
    assert all(d >= dates5[2] for d in hist["D"].dates)


def test_rank_history_full_history_funds_keep_all_dates() -> None:
    hist = rank_history(_panels(), higher_is_better=True)
    dates5 = month_end_dates(5)
    for fid in ("A", "B", "C"):
        assert hist[fid].dates == dates5


def test_rank_history_empty_panel_stays_empty() -> None:
    hist = rank_history(_panels(), higher_is_better=True)
    assert len(hist["E"]) == 0
    assert hist["E"].dates == ()


def test_rank_history_cohort_size_changes_with_participation() -> None:
    # At d1 the cohort is {A,B,C} (N=3): C on top at 100, A at bottom at 1/3.
    # At d3 D joins (N=4) below all three: C=100, and A drops to 2/4 as the
    # denominator grew and D slotted beneath it.
    hist = rank_history(_panels(), higher_is_better=True)
    a_by_date = dict(zip(hist["A"].dates, hist["A"].values))
    dates5 = month_end_dates(5)
    assert a_by_date[dates5[0]] == pytest.approx(100.0 / 3.0, abs=_ABS)  # 1/3
    assert a_by_date[dates5[2]] == pytest.approx(50.0, abs=_ABS)  # 2/4


def test_rank_history_valid_distribution_per_date() -> None:
    hist = rank_history(_panels(), higher_is_better=True)
    dates5 = month_end_dates(5)
    # Reassemble the cross-section of ranks at each date; the present cohort's
    # ranks must top out at 100 and lie in (0, 100].
    for d in dates5:
        ranks_here = [
            float(v)
            for fid in hist
            for dd, v in zip(hist[fid].dates, hist[fid].values)
            if dd == d
        ]
        assert ranks_here  # at least the mature funds are present every date
        assert all(0.0 < r <= 100.0 for r in ranks_here)
        assert max(ranks_here) == pytest.approx(100.0, abs=_ABS)


def test_rank_history_direction_flag_inverts() -> None:
    # C is the highest value each date → 100 when higher_is_better, and the
    # lowest rank when lower_is_better (A, the lowest value, tops that ranking).
    hi = rank_history(_panels(), higher_is_better=True)
    lo = rank_history(_panels(), higher_is_better=False)
    dates5 = month_end_dates(5)
    c_hi = dict(zip(hi["C"].dates, hi["C"].values))
    a_lo = dict(zip(lo["A"].dates, lo["A"].values))
    assert c_hi[dates5[0]] == pytest.approx(100.0, abs=_ABS)
    assert a_lo[dates5[0]] == pytest.approx(100.0, abs=_ABS)


def test_rank_history_base_carries_through() -> None:
    hist = rank_history(_panels(), higher_is_better=True)
    assert hist["A"].base == _panels()["A"].base
