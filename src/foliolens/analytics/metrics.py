"""§2 pure-core metrics over ``ReturnSeries`` (no benchmark).

All functions are pure and periodicity-agnostic over the monthly analytical
series; they never see NAV. Annualisation follows the analytics convention in
``CLAUDE.md``: return annualises geometrically ``(1+R)^(12/n) − 1``; volatility
and downside deviation annualise by ``√12``. Definitions are pinned to the
``ffn`` / ``empyrical`` monthly oracle (``period='monthly'`` → annualisation
factor 12) so own↔oracle holds at ≤ 1e-6.

Risk-free / MAR inputs are return *series*, never scalar rates; two-series
metrics align through :func:`series_ops.align`.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import numpy.typing as npt

from foliolens.model.value_objects import ReturnSeries

from ..returns.frequency import Frequency
from .series_ops import align, between, require_frequency


def period_return_abs(rs: ReturnSeries, start: date, end: date) -> float:
    """Absolute (non-annualised) compounded return over ``[start, end]``.

    The SEBI ``< 1 year`` basis: 1M/3M/6M/YTD are the same operation over
    different windows — compound the simple monthly returns in the window,
    ``Π(1+r) − 1``. The window is selected via :func:`between` (no inline
    slicing). Fails loud on an empty window rather than reporting a silent 0%.
    """
    window = between(rs, start, end)
    if len(window) < 1:
        raise ValueError(f"no returns in window [{start}, {end}]")
    return float(np.prod(1.0 + window.values) - 1.0)


def volatility(rs: ReturnSeries) -> float:
    """Annualised volatility: sample std (ddof=1) of monthly returns × √12.

    Matches ``empyrical.annual_volatility(..., period='monthly')``.
    """
    require_frequency(rs, Frequency.MONTHLY)
    if len(rs) < 2:
        raise ValueError(f"volatility needs >= 2 returns, got {len(rs)}")
    return float(np.std(rs.values, ddof=1) * np.sqrt(rs.frequency.periods_per_year))


def _downside_deviation(
    excess: npt.NDArray[np.float64], periods_per_year: int
) -> float:
    """Annualised downside deviation of an already-aligned excess-return array.

    ``√( mean( min(excess, 0)² ) ) × √periods_per_year`` — the denominator is
    the *full* sample count N (not the count of negatives), per the
    Sortino/Sunrise definition and ``empyrical.downside_risk``.
    """
    downside = np.clip(excess, -np.inf, 0.0)
    return float(np.sqrt(np.mean(np.square(downside))) * np.sqrt(periods_per_year))


def downside_deviation(rs: ReturnSeries, mar: ReturnSeries) -> float:
    """Annualised downside deviation of ``rs`` below the MAR series.

    MAR is a return series (the rf Investment's returns for Sortino, MAR = rf) —
    never a scalar. Aligned to ``rs`` on dates via :func:`align`; only the
    overlap contributes.
    """
    require_frequency(rs, Frequency.MONTHLY)
    r, m = align(rs, mar)
    if len(r) < 1:
        raise ValueError("downside_deviation needs >= 1 overlapping return")
    return _downside_deviation(r - m, rs.frequency.periods_per_year)


def sharpe(rs: ReturnSeries, rf: ReturnSeries) -> float:
    """Annualised Sharpe ratio using an rf *series* (never a scalar rate).

    ``mean(r − rf) / std(r − rf, ddof=1) × √12`` over the aligned overlap.
    Matches ``empyrical.sharpe_ratio(..., period='monthly')`` when rf is passed
    as the same per-period series.
    """
    require_frequency(rs, Frequency.MONTHLY)
    r, f = align(rs, rf)
    if len(r) < 2:
        raise ValueError(f"sharpe needs >= 2 overlapping returns, got {len(r)}")
    excess = r - f
    return float(
        np.mean(excess) / np.std(excess, ddof=1) * np.sqrt(rs.frequency.periods_per_year)
    )


def sortino(rs: ReturnSeries, rf: ReturnSeries) -> float:
    """Annualised Sortino ratio, MAR = rf (an rf *series*, never a scalar).

    ``(mean(r − rf) × 12) / downside_deviation`` over the aligned overlap.
    Matches ``empyrical.sortino_ratio(..., period='monthly')``. Undefined when
    the series never underperforms the MAR (zero downside deviation) — fails
    loud with the same "undefined" signal as the other zero-denominator ratios
    (``information_ratio``'s zero-TE, ``treynor``'s zero-beta), rather than
    surfacing a raw ``ZeroDivisionError`` to the caller.
    """
    require_frequency(rs, Frequency.MONTHLY)
    r, f = align(rs, rf)
    if len(r) < 2:
        raise ValueError(f"sortino needs >= 2 overlapping returns, got {len(r)}")
    excess = r - f
    downside = _downside_deviation(excess, rs.frequency.periods_per_year)
    if downside == 0.0:
        raise ValueError("sortino undefined: downside deviation is zero")
    numerator = float(np.mean(excess)) * rs.frequency.periods_per_year
    return numerator / downside


def calmar(rs: ReturnSeries) -> float:
    """Calmar ratio: annualised return / |max drawdown|, both over ``rs``.

    Drawdown here is the *return-series* drawdown (a peak is seeded before the
    first period, per ``empyrical.max_drawdown``), NOT the daily-NAV drawdown of
    §3 — §2 functions never touch NAV, and the oracle (``empyrical.calmar_ratio``)
    is defined over the return series. Returns NaN when the series never draws
    down (no finite ratio exists), matching the oracle.
    """
    require_frequency(rs, Frequency.MONTHLY)
    if len(rs) < 1:
        raise ValueError("calmar needs >= 1 return")
    values = rs.values
    # Seed a peak level of 1.0 before the first period so a first-period decline
    # is measured from the start (drawdown is scale-invariant, so 1.0 vs 100).
    levels = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    running_max = np.fmax.accumulate(levels)
    max_dd = float(np.min((levels - running_max) / running_max))
    if max_dd >= 0.0:
        return float("nan")
    n = len(values)
    total_growth = float(np.prod(1.0 + values))
    annualised_return = float(total_growth ** (rs.frequency.periods_per_year / n)) - 1.0
    return annualised_return / abs(max_dd)
