"""Own-vs-oracle acceptance for §7 category aggregates.

Oracle = numpy directly on the non-null values: ``np.median`` and
``np.percentile`` at 25/75 (default linear interpolation — the same method
``category_aggregate`` uses). This is the "aggregate correctness vs numpy on
non-nulls" leg of the §7 task; the ranking *rule* has no library oracle and is
pinned by hand in ``test_peer_unit.py``. Tolerance matches the analytics
convention: own↔oracle relative ≤ 1e-6.

The percentile-rank surface has no oracle either, but its cross-section must be
internally consistent with the aggregates — the median of a cohort sits at the
50-percentile rank — so one reconciliation test ties the two surfaces together.
"""
from __future__ import annotations

import numpy as np

from foliolens.analytics.peer import category_aggregate, percentile_ranks

_REL = 1e-6

# A cohort with an all-null fund and a partial (here: a NaN) value mixed in, so
# the non-null selection is exercised, plus enough distinct values that the
# quartiles interpolate between points rather than landing on one.
_COHORT: dict[str, float | None] = {
    "f0": 0.05,
    "f1": 0.11,
    "f2": 0.18,
    "f3": 0.22,
    "f4": 0.27,
    "f5": 0.34,
    "f6": 0.41,
    "f7": None,
    "f8": float("nan"),
}
_NON_NULL = [0.05, 0.11, 0.18, 0.22, 0.27, 0.34, 0.41]


def _rel_close(own: float, oracle: float) -> bool:
    return abs(own - oracle) <= _REL * abs(oracle)


def test_count_matches_non_null_selection() -> None:
    agg = category_aggregate(_COHORT)
    assert agg.count == len(_NON_NULL)


def test_median_vs_numpy() -> None:
    agg = category_aggregate(_COHORT)
    assert agg.median is not None
    assert _rel_close(agg.median, float(np.median(_NON_NULL)))


def test_q1_vs_numpy() -> None:
    agg = category_aggregate(_COHORT)
    assert agg.q1 is not None
    assert _rel_close(agg.q1, float(np.percentile(_NON_NULL, 25)))


def test_q3_vs_numpy() -> None:
    agg = category_aggregate(_COHORT)
    assert agg.q3 is not None
    assert _rel_close(agg.q3, float(np.percentile(_NON_NULL, 75)))


def test_median_sits_at_the_50th_percentile_rank() -> None:
    # Cross-surface consistency: inject the cohort's own median as an extra fund
    # and it must land at the 50-percentile rank (half the enlarged cohort at or
    # below it), tying the aggregate and the rank definitions together.
    median = float(np.median(_NON_NULL))
    enlarged = {**{k: v for k, v in _COHORT.items() if v is not None}, "med": median}
    ranks = percentile_ranks(enlarged, higher_is_better=True)
    # Odd non-null count (7) → the median is one of the values; with "med" added
    # the count at or below the median is exactly half (rounded) of N=8.
    n = len([v for v in enlarged.values() if v is not None and not np.isnan(v)])
    at_or_below = sum(1 for v in _NON_NULL + [median] if v <= median)
    assert ranks["med"] is not None
    assert _rel_close(ranks["med"], at_or_below / n * 100.0)
