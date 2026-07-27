"""§7 peer / cross-sectional machinery — pure functions over a cohort.

Cross-sectional ranking is deliberately blind to *what* the cohort is: these
functions take a plain ``{fund_id: value}`` map (or ``{fund_id: ReturnSeries}``
panel) and rank/aggregate over it. Category membership, benchmark identity, and
the scheme master live entirely in the caller — the cohort is supplied, never
inferred here (``spec-analytics §7``). This keeps peer ranks a computation over
whatever universe the caller assembles, with no coupling to how it was chosen.

Conventions (fixed here, per the §7 task):

- **Percentile = fraction of peers at or below**, scaled 0–100, so *higher is
  better* for a return-like metric (the top fund reaches 100). The direction is
  an explicit ``higher_is_better`` flag, never hard-coded per metric — a
  lower-is-better metric (expense drag, volatility) passes ``False`` and the
  comparison flips to "at or above" so the best (lowest) fund still reaches 100.
- **Nulls are excluded, never imputed.** A ``None`` (or ``NaN``) value drops the
  fund from both the numerator *and* the universe count ``N``; that fund's own
  rank is ``None``. A fund is never given a placeholder mid-scale rank — an
  absent metric is absent, not "average".

The three surfaces:

- :func:`percentile_ranks` — one cross-section: ``{fund_id: value|None}`` →
  ``{fund_id: percentile|None}``.
- :func:`category_aggregate` — median / q1 / q3 / count over the non-null values
  (numpy's linear-interpolation quantiles; the caller scopes the category).
- :func:`rank_history` — percentile ranks *per date* across funds' rolling
  panels. At each date the cohort is exactly the funds carrying a point there,
  so a young fund is naturally excluded from the early dates its short panel
  never reached — an empty panel contributes nothing at all.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import TypeGuard

import numpy as np

from foliolens.model.value_objects import ReturnSeries


def _is_present(value: float | None) -> TypeGuard[float]:
    """A value counts toward the universe iff it is neither ``None`` nor ``NaN``.

    ``NaN`` is treated as absent for the same reason ``None`` is: a metric that
    could not be computed (e.g. Calmar on a never-drawn-down series) is *missing*,
    not a real figure to rank against. Excluding it keeps the "never imputed"
    rule intact — it neither earns a rank nor perturbs its peers' counts.
    """
    return value is not None and not math.isnan(value)


def percentile_ranks(
    values: Mapping[str, float | None],
    *,
    higher_is_better: bool,
) -> dict[str, float | None]:
    """Cross-sectional percentile rank of each fund within the supplied cohort.

    The rank of a fund is the fraction of the (non-null) cohort at or below it —
    ``|{peers ≤ this}| / N × 100`` when ``higher_is_better`` — so the best fund
    reaches exactly 100 and ties share a rank. With ``higher_is_better=False``
    the comparison flips to "at or above", so the lowest value tops the ranking
    (the natural direction for a cost/risk metric).

    ``N`` is the count of non-null values only. Funds with a ``None``/``NaN``
    value are excluded from ``N`` and from every count, and receive ``None`` for
    their own rank (``spec-analytics §7``: nulls excluded from both numerator and
    universe, never imputed). The returned mapping preserves every input key —
    absent funds map to ``None`` — so the caller can index it by fund id
    unconditionally.

    An all-null (or empty) cohort yields ``None`` for every fund. A single
    non-null fund ranks 100 (it is at or below itself, over a universe of one).
    """
    ranks: dict[str, float | None] = {fid: None for fid in values}
    present = {fid: float(v) for fid, v in values.items() if _is_present(v)}
    n = len(present)
    if n == 0:
        return ranks
    peer_values = np.fromiter(present.values(), dtype=np.float64, count=n)
    for fid, v in present.items():
        if higher_is_better:
            count = int(np.count_nonzero(peer_values <= v))
        else:
            count = int(np.count_nonzero(peer_values >= v))
        ranks[fid] = count / n * 100.0
    return ranks


@dataclass(frozen=True)
class CategoryAggregate:
    """Cross-sectional summary of one cohort's metric values over its non-nulls.

    ``count`` is the number of funds that contributed a real (non-null) value;
    ``median``/``q1``/``q3`` are numpy's linear-interpolation quantiles over
    exactly those values, or ``None`` when the cohort is empty (no value to
    summarise). Quantiles are a figure *about* a category, not a figure of record
    — float64 throughout, in line with the analytics path of scale.
    """

    count: int
    median: float | None
    q1: float | None
    q3: float | None


def category_aggregate(values: Mapping[str, float | None]) -> CategoryAggregate:
    """Median / q1 / q3 / count over the non-null values of a cohort.

    Nulls (``None``/``NaN``) are dropped before aggregation — the same
    exclusion rule as :func:`percentile_ranks`, so ``count`` here equals that
    function's ``N``. Quantiles use numpy's default linear interpolation
    (``np.median`` / ``np.percentile`` at 25/50/75), the reference the tests
    reconcile against. An empty cohort returns ``count=0`` with ``None``
    quantiles rather than raising, so a category with no data is representable.
    """
    present = [float(v) for v in values.values() if _is_present(v)]
    n = len(present)
    if n == 0:
        return CategoryAggregate(count=0, median=None, q1=None, q3=None)
    arr = np.asarray(present, dtype=np.float64)
    return CategoryAggregate(
        count=n,
        median=float(np.median(arr)),
        q1=float(np.percentile(arr, 25)),
        q3=float(np.percentile(arr, 75)),
    )


def rank_history(
    panels: Mapping[str, ReturnSeries],
    *,
    higher_is_better: bool,
) -> dict[str, ReturnSeries]:
    """Percentile-rank each fund against its peers, independently at every date.

    Given each fund's rolling panel (a ``ReturnSeries`` of a metric over time),
    this walks the union of all panel dates and, at each date, ranks the cohort
    of funds that carry a point *there* — a per-date inner selection on panel
    dates. The result is one rank ``ReturnSeries`` per fund: its percentile
    (0–100) at each of its own panel dates, computed against whoever else was
    present on that date.

    Because the cohort is rebuilt per date from the funds actually present, a
    young fund whose panel starts late simply does not appear in the earlier
    dates' rankings — it is excluded from those early rank dates, not imputed
    into them (``spec-analytics §7``). A fund with an empty panel contributes no
    dates and gets an empty rank series back. ``higher_is_better`` is forwarded
    to :func:`percentile_ranks` unchanged, fixing the direction for every date.

    Each output series preserves its fund's panel ``base``; dates are strictly
    ascending (the union is sorted, and every fund's points follow that order).
    """
    per_fund: dict[str, dict[date, float]] = {}
    all_dates: set[date] = set()
    for fid, panel in panels.items():
        by_date = {d: float(v) for d, v in zip(panel.dates, panel.values)}
        per_fund[fid] = by_date
        all_dates.update(by_date)

    collected: dict[str, list[tuple[date, float]]] = {fid: [] for fid in panels}
    for d in sorted(all_dates):
        cross_section: dict[str, float | None] = {
            fid: by_date[d] for fid, by_date in per_fund.items() if d in by_date
        }
        for fid, rank in percentile_ranks(
            cross_section, higher_is_better=higher_is_better
        ).items():
            if rank is not None:
                collected[fid].append((d, rank))

    out: dict[str, ReturnSeries] = {}
    for fid, points in collected.items():
        dates = tuple(d for d, _ in points)
        vals = np.array([r for _, r in points], dtype=np.float64)
        out[fid] = ReturnSeries(
            dates=dates, values=vals, frequency=panels[fid].frequency, base=panels[fid].base
        )
    return out
