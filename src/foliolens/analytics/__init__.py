"""Analytics — pure free functions over the materialised ``ReturnSeries``.

Mirrors the return engine: metrics are free functions, never methods on the
data classes or on ``ReturnSource`` (see ``spec-analytics §0`` and
``ARCHITECTURE.md`` → *Analytics*). Inputs are float64 ``ReturnSeries``; no
Decimal enters this layer. rf/benchmark are passed as return *series*, never as
a scalar rate. Two-series metrics route through ``series_ops.align`` — never an
ad-hoc join.

§2 (this module set) is the pure core, no benchmark:
``series_ops.align`` / ``series_ops.between`` and the metrics
``period_return_abs``, ``volatility``, ``downside_deviation``, ``sharpe``,
``sortino``, ``calmar``.
"""
from __future__ import annotations

from .metrics import (
    calmar,
    downside_deviation,
    period_return_abs,
    sharpe,
    sortino,
    volatility,
)
from .series_ops import align, between

__all__ = [
    "align",
    "between",
    "period_return_abs",
    "volatility",
    "downside_deviation",
    "sharpe",
    "sortino",
    "calmar",
]
