"""Series utilities for the analytics layer.

The one place two return series meet. Every two-series metric routes its
alignment through :func:`align`; no metric re-implements a join inline
(``spec-analytics §2``). ``between`` is the searchsorted window slice used to
build period returns (1M/3M/6M/YTD) without re-deriving from NAV.
"""
from __future__ import annotations

import bisect
from datetime import date

import numpy as np
import numpy.typing as npt

from foliolens.model.value_objects import ReturnSeries

from ..returns.frequency import Frequency


def require_frequency(rs: ReturnSeries, expected: Frequency) -> None:
    """Raise ValueError if ``rs.frequency`` != ``expected``.

    ``spec-analytics``: no cross-frequency series use — a metric that fixes a
    convention (an annualisation factor, a daily-NAV basis) must reject a
    series declaring the wrong one rather than silently misapplying it.
    """
    if rs.frequency != expected:
        raise ValueError(f"frequency mismatch: expected {expected}, got {rs.frequency}")


def align_dated(
    a: ReturnSeries, b: ReturnSeries
) -> tuple[tuple[date, ...], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Inner-join two return series, keeping the common dates.

    Returns ``(dates, a_values, b_values)`` — the shared period-end dates (in
    ascending order) and the float64 values of each series on exactly those
    dates. This is the single join implementation; :func:`align` is the
    date-dropping projection for scalar metrics, and dated two-series results
    (excess-return *series*) build on this so the join lives in one place
    (``spec-analytics §2``: "no metric re-implements a join inline").

    Raises ValueError if ``a`` and ``b`` declare different frequencies — a
    monthly/daily join is never a meaningful date-alignment.
    """
    if a.frequency != b.frequency:
        raise ValueError(f"frequency mismatch: {a.frequency} vs {b.frequency}")
    b_index: dict[date, int] = {d: i for i, d in enumerate(b.dates)}
    dates_out: list[date] = []
    a_out: list[float] = []
    b_out: list[float] = []
    for i, d in enumerate(a.dates):
        j = b_index.get(d)
        if j is not None:
            dates_out.append(d)
            a_out.append(float(a.values[i]))
            b_out.append(float(b.values[j]))
    return (
        tuple(dates_out),
        np.array(a_out, dtype=np.float64),
        np.array(b_out, dtype=np.float64),
    )


def align(
    a: ReturnSeries, b: ReturnSeries
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Inner-join two return series on their period-end dates.

    Returns ``(a_values, b_values)`` — float64 arrays of equal length, one entry
    per date present in *both* series, in ascending date order. Dates in one
    series but not the other are dropped (this is what makes "rf longer than the
    fund" the natural, no-op case: only the overlap is used).

    An empty overlap yields two empty arrays; the caller decides whether that is
    an error (metrics that need ≥2 points fail loud on it). Thin projection of
    :func:`align_dated` — the join itself has one implementation.
    """
    _, a_vals, b_vals = align_dated(a, b)
    return a_vals, b_vals


def trailing_anchored(rs: ReturnSeries, periods: int, as_of: date) -> ReturnSeries | None:
    """The trailing ``periods``-window of ``rs`` ending exactly at ``as_of``.

    ``None`` when ``as_of`` is absent from ``rs.dates`` — the series does not
    reach the shared anchor date (a stale fund lagging the rest of a cohort) —
    or when fewer than ``periods`` points precede it. This is the null path a
    caller must take instead of silently falling back to ``rs``'s own last
    date: a common cross-sectional ``as_of`` only stays comparable across
    funds if every window is measured to the *same* end date, not each
    fund's own.
    """
    try:
        end_i = rs.dates.index(as_of)
    except ValueError:
        return None
    if end_i + 1 < periods:
        return None
    lo = end_i + 1 - periods
    return ReturnSeries(
        dates=rs.dates[lo : end_i + 1],
        values=rs.values[lo : end_i + 1],
        frequency=rs.frequency,
        base=rs.base,
    )


def between(rs: ReturnSeries, start: date, end: date) -> ReturnSeries:
    """Slice ``rs`` to the window ``[start, end]`` inclusive (searchsorted).

    Dates are strictly ascending by construction, so the window is a contiguous
    run located with ``bisect`` (searchsorted semantics: O(log n), no scan). The
    ``base`` anchor carries through unchanged.
    """
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    lo = bisect.bisect_left(rs.dates, start)
    hi = bisect.bisect_right(rs.dates, end)
    return ReturnSeries(
        dates=rs.dates[lo:hi],
        values=rs.values[lo:hi],
        frequency=rs.frequency,
        base=rs.base,
    )
