"""§4 rolling returns — monthly step, 1/3/5y windows, over ``ReturnSeries``.

Pure over the monthly analytical series (fixed per ``spec-analytics``: asserts
``Frequency.MONTHLY`` at entry), mirroring §2/§3. Each window's compounded
return is produced by :func:`period_return_abs`
(§2) over a ``between`` slice — the compounding logic (``Π(1+r) − 1``) is never
reimplemented here, only annualised on top per the SEBI ≥1y rule (``CLAUDE.md``
→ *Analytics conventions*: ``(1+R)^(12/n) − 1``).

Each rolling window is a **calendar-date** slice ending at its anchor month —
the entries dated within ``(anchor − W years, anchor]`` — not the last
``window_months`` observations. On a panel with a data hole the two differ: a
last-N window anchored just after the hole reaches back across it and stretches
past ``W`` calendar years, whereas the date slice covers the true span and
computes over whatever survives inside it (never padded, never stretched to
reach a count).

Acceptance (``spec-analytics §4``): a window longer than available history emits
no point — an empty young-fund panel is correct, never padded, never a partial
window.
"""
from __future__ import annotations

import bisect
from datetime import date

import numpy as np

from foliolens.model.value_objects import ReturnSeries

from ..returns.engine import _subtract_years
from ..returns.frequency import Frequency
from .metrics import period_return_abs
from .series_ops import require_frequency

#: Rolling window labels → window length in months. Mirrors the anchored-period
#: labels used by the return engine (``returns/engine.py``'s ``_ANCHOR_YEARS``).
ROLLING_WINDOWS: dict[str, int] = {"1Y": 12, "3Y": 36, "5Y": 60}


def _year_month(d: date) -> tuple[int, int]:
    """(year, month) — the month-granular key a whole-year window is sliced on."""
    return (d.year, d.month)


def rolling_return(rs: ReturnSeries, window_months: int) -> ReturnSeries:
    """Rolling annualised return, monthly step, over a fixed-length window.

    For each window end date, compounds the returns in the calendar span
    ``(anchor − W years, anchor]`` (``W = window_months / 12``) via
    :func:`period_return_abs` and annualises geometrically —
    ``(1+R)^(12/window_months) − 1``, the same convention as trailing CAGRs.
    A window of exactly 12 months reduces to the absolute return, as it must
    (SEBI: a 1-year period is the boundary between absolute and CAGR).

    The span is sliced by **date**, not by observation count: on a contiguous
    panel it is exactly the last ``window_months`` returns (unchanged), but on a
    panel with a data hole it holds only the months that survive inside the year
    — it never reaches back across the hole to consume ``window_months``
    observations spanning more than ``W`` calendar years.

    Emits one point per anchor from the ``window_months``-th onward, stamped at
    that window's *last* date (a month-end by construction). When
    ``len(rs) < window_months`` — the young-fund case — returns an **empty**
    ``ReturnSeries``: never a padded or partial window (``spec-analytics §4``
    acceptance).
    """
    require_frequency(rs, Frequency.MONTHLY)
    if window_months < 1:
        raise ValueError(f"window_months must be >= 1, got {window_months}")
    n = len(rs)
    if n < window_months:
        return ReturnSeries(
            dates=(), values=np.array([], dtype=np.float64), frequency=rs.frequency, base=rs.base
        )
    whole_years, part = divmod(window_months, 12)
    dates: list[date] = []
    values: list[float] = []
    for end_i in range(window_months - 1, n):
        if part == 0:
            # Whole-year window → slice by calendar date via the engine's
            # Feb-29-clamped anchor arithmetic (no new date arithmetic here).
            # Compared at month granularity so the boundary month is excluded
            # whole: _subtract_years clamps Feb-29 → Feb-28, and a raw date
            # compare would otherwise leak a leap-Feb entry (13 months). Keyed on
            # (year, month) the contiguous window is exactly the last
            # window_months entries — coinciding with pandas' rolling oracle.
            lo_bound = _subtract_years(rs.dates[end_i], whole_years)
            start_i = bisect.bisect_right(
                rs.dates, _year_month(lo_bound), key=_year_month
            )
        else:
            # Sub-year window (no whole-year boundary to date-slice against, and
            # month arithmetic is out of scope) → the last window_months entries.
            start_i = end_i - window_months + 1
        compounded = period_return_abs(rs, rs.dates[start_i], rs.dates[end_i])
        annualised = (1.0 + compounded) ** (rs.frequency.periods_per_year / window_months) - 1.0
        dates.append(rs.dates[end_i])
        values.append(annualised)
    return ReturnSeries(
        dates=tuple(dates),
        values=np.array(values, dtype=np.float64),
        frequency=rs.frequency,
        base=rs.base,
    )


def rolling_returns(rs: ReturnSeries) -> dict[str, ReturnSeries]:
    """Rolling annualised returns for all three standard windows (1Y/3Y/5Y).

    Convenience bundle over :func:`rolling_return` and :data:`ROLLING_WINDOWS`
    — one ``ReturnSeries`` per label, each independently empty if history is
    too short for that window (a young fund may have a populated 1Y panel and
    empty 3Y/5Y panels).
    """
    return {
        label: rolling_return(rs, months) for label, months in ROLLING_WINDOWS.items()
    }
