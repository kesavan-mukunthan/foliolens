"""Analytics — pure free functions over the materialised ``ReturnSeries``.

Mirrors the return engine: metrics are free functions, never methods on the
data classes or on ``ReturnSource`` (see ``spec-analytics §0`` and
``ARCHITECTURE.md`` → *Analytics*). Inputs are float64 ``ReturnSeries``; no
Decimal enters this layer. rf/benchmark are passed as return *series*, never as
a scalar rate. Two-series metrics route through ``series_ops.align`` — never an
ad-hoc join.

§2 (pure core, no benchmark): ``series_ops.align`` / ``series_ops.between`` and
the metrics ``period_return_abs``, ``volatility``, ``downside_deviation``,
``sharpe``, ``sortino``, ``calmar``.

§3 (daily-basis family): ``max_drawdown`` / ``drawdown`` (+ the ``Drawdown``
episode), ``var_historical``, ``cvar`` — pure over ``ReturnSeries`` /
``ValueIndex`` — with the ``*_of`` daily adapters that read ``investment.source``.
Drawdown is the one family that reads daily NAV, not the monthly series.

§4 (rolling + distribution): ``rolling_return`` / ``rolling_returns`` (monthly
step, 1Y/3Y/5Y windows, reusing ``period_return_abs``) and the distribution
stats ``pct_positive``, ``best_period``, ``worst_period``, ``skew``,
``kurtosis`` — all pure over ``ReturnSeries``.

§5 (adapters + artifact): the ``*_of(investment, …)`` peers that read
``investment.returns`` and delegate to the pure functions (``adapters``), and the
versioned metrics artifact ``MetricsResult`` / ``build_metrics`` (``artifact``).
"""
from __future__ import annotations

from .adapters import (
    best_period_of,
    calmar_of,
    downside_deviation_of,
    kurtosis_of,
    pct_positive_of,
    period_return_abs_of,
    rolling_return_of,
    rolling_returns_of,
    sharpe_of,
    skew_of,
    sortino_of,
    volatility_of,
    worst_period_of,
)
from .artifact import SCHEMA_VERSION, MetricsResult, SeriesPoint, build_metrics
from .distribution import best_period, kurtosis, pct_positive, skew, worst_period
from .drawdown import (
    Drawdown,
    cvar,
    cvar_of,
    drawdown,
    drawdown_of,
    max_drawdown,
    max_drawdown_of,
    var_historical,
    var_historical_of,
)
from .metrics import (
    calmar,
    downside_deviation,
    period_return_abs,
    sharpe,
    sortino,
    volatility,
)
from .rolling import ROLLING_WINDOWS, rolling_return, rolling_returns
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
    "Drawdown",
    "max_drawdown",
    "drawdown",
    "var_historical",
    "cvar",
    "max_drawdown_of",
    "drawdown_of",
    "var_historical_of",
    "cvar_of",
    "ROLLING_WINDOWS",
    "rolling_return",
    "rolling_returns",
    "pct_positive",
    "best_period",
    "worst_period",
    "skew",
    "kurtosis",
    # §5 adapters (read .returns, delegate to the pure functions)
    "period_return_abs_of",
    "volatility_of",
    "downside_deviation_of",
    "sharpe_of",
    "sortino_of",
    "calmar_of",
    "rolling_return_of",
    "rolling_returns_of",
    "pct_positive_of",
    "best_period_of",
    "worst_period_of",
    "skew_of",
    "kurtosis_of",
    # §5 metrics artifact
    "SCHEMA_VERSION",
    "MetricsResult",
    "SeriesPoint",
    "build_metrics",
]
