"""§4 rolling returns — monthly step, 1/3/5y windows, over ``ReturnSeries``.

Pure and periodicity-agnostic over the monthly analytical series, mirroring
§2/§3. Each window's compounded return is produced by :func:`period_return_abs`
(§2) over a ``between`` slice — the compounding logic (``Π(1+r) − 1``) is never
reimplemented here, only annualised on top per the SEBI ≥1y rule (``CLAUDE.md``
→ *Analytics conventions*: ``(1+R)^(12/n) − 1``).

Acceptance (``spec-analytics §4``): a window longer than available history emits
no point — an empty young-fund panel is correct, never padded, never a partial
window.
"""
from __future__ import annotations

from datetime import date

import numpy as np

from foliolens.model.value_objects import ReturnSeries

from .metrics import period_return_abs

_MONTHS_PER_YEAR = 12.0

#: Rolling window labels → window length in months. Mirrors the anchored-period
#: labels used by the return engine (``returns/engine.py``'s ``_ANCHOR_YEARS``).
ROLLING_WINDOWS: dict[str, int] = {"1Y": 12, "3Y": 36, "5Y": 60}


def rolling_return(rs: ReturnSeries, window_months: int) -> ReturnSeries:
    """Rolling annualised return, monthly step, over a fixed-length window.

    For each window end date, compounds the ``window_months`` returns ending
    there (via :func:`period_return_abs`) and annualises geometrically —
    ``(1+R)^(12/window_months) − 1``, the same convention as trailing CAGRs.
    A window of exactly 12 months reduces to the absolute return, as it must
    (SEBI: a 1-year period is the boundary between absolute and CAGR).

    Emits one point per window end, stamped at that window's *last* date (a
    month-end by construction). When ``len(rs) < window_months`` — the young-fund
    case — returns an **empty** ``ReturnSeries``: never a padded or partial
    window (``spec-analytics §4`` acceptance).
    """
    if window_months < 1:
        raise ValueError(f"window_months must be >= 1, got {window_months}")
    n = len(rs)
    if n < window_months:
        return ReturnSeries(
            dates=(), values=np.array([], dtype=np.float64), frequency=rs.frequency, base=rs.base
        )
    dates: list[date] = []
    values: list[float] = []
    for end_i in range(window_months - 1, n):
        start_i = end_i - window_months + 1
        compounded = period_return_abs(rs, rs.dates[start_i], rs.dates[end_i])
        annualised = (1.0 + compounded) ** (_MONTHS_PER_YEAR / window_months) - 1.0
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
