"""The single Decimal→float seam on the return-series path.

This module is the *only* place where Decimal converts to float on the series
path. NAV lives in Decimal (path of record); analytical return series and value
indices live in float64 (path of scale). Cast-at-birth: each ratio is computed
in Decimal, then cast once to float — float never flows back into a figure of
record.
"""
from __future__ import annotations

from decimal import Decimal

import numpy as np

from foliolens.model.value_objects import NavSeries, ReturnSeries, ValueIndex


def simple_return(start: Decimal, end: Decimal) -> float:
    """Single-period simple return ``end/start - 1``, cast once to float.

    Raises ValueError if ``start`` is not strictly positive.
    """
    if start <= 0:
        raise ValueError(f"start NAV must be > 0, got {start}")
    return float(end / start - 1)


def to_returns(nav: NavSeries) -> ReturnSeries:
    """Simple returns between consecutive points of ``nav`` as passed.

    No resampling happens here. The canonical monthly analytical panel is
    ``to_returns(nav.month_end())`` — resample first, then convert. Period-end
    dates are ``nav.data[1:]``; the base anchor is Decimal("100").

    Cast-at-birth: each ratio is computed in Decimal and cast once to float.
    Raises ValueError if fewer than 2 points or any NAV <= 0.
    """
    if len(nav) < 2:
        raise ValueError(f"need >= 2 NAV points to compute returns, got {len(nav)}")
    # simple_return validates each pair's start; the terminal NAV is only ever an
    # end, so guard it explicitly to reject a non-positive final NAV.
    if nav.data[-1][1] <= 0:
        raise ValueError(
            f"NAV must be > 0, got {nav.data[-1][1]} on {nav.data[-1][0]}"
        )
    dates = tuple(d for d, _ in nav.data[1:])
    values = np.array(
        [
            simple_return(prev_nav, cur_nav)
            for (_, prev_nav), (_, cur_nav) in zip(nav.data, nav.data[1:])
        ],
        dtype=np.float64,
    )
    return ReturnSeries(dates=dates, values=values, base=Decimal("100"))


def to_index(r: ReturnSeries) -> ValueIndex:
    """Reconstruct the value index: ``base·Π(1+r)`` (the dual of NavSeries).

    Levels rebase to ``r.base`` — only the base survives; absolute NAV levels do
    not. Round-trips return *ratios*, never NAV levels.
    """
    levels = float(r.base) * np.cumprod(1.0 + r.values)
    return ValueIndex(dates=r.dates, levels=levels)
