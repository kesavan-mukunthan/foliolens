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

§6 (benchmark-relative): pure functions over the aligned fund/benchmark/rf
series (``relative``) — ``excess_return``, ``tracking_error``,
``information_ratio``, ``beta``, ``correlation``, ``r_squared``,
``jensens_alpha`` (an ``AlphaResult`` carrying the t-stat + window), ``treynor``,
``up_capture`` / ``down_capture``, ``hit_rate``, and the rolling-relative panels
(``rolling_excess_return`` / ``rolling_beta`` / ``rolling_correlation``,
compositions over §4's windowing) — with the ``*_of`` adapters that read the
fund's / benchmark's / rf's ``.returns`` (benchmark & rf as Investments).
"""
from __future__ import annotations

from .adapters import (
    best_period_of,
    beta_of,
    calmar_of,
    correlation_of,
    down_capture_of,
    downside_deviation_of,
    excess_return_of,
    hit_rate_of,
    information_ratio_of,
    jensens_alpha_of,
    kurtosis_of,
    pct_positive_of,
    period_return_abs_of,
    r_squared_of,
    rolling_beta_of,
    rolling_correlation_of,
    rolling_excess_return_of,
    rolling_return_of,
    rolling_returns_of,
    sharpe_of,
    skew_of,
    sortino_of,
    tracking_error_of,
    treynor_of,
    up_capture_of,
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
from .relative import (
    RELATIVE_ROLLING_WINDOWS,
    AlphaResult,
    beta,
    correlation,
    down_capture,
    excess_return,
    hit_rate,
    information_ratio,
    jensens_alpha,
    r_squared,
    rolling_beta,
    rolling_betas,
    rolling_correlation,
    rolling_correlations,
    rolling_excess_return,
    tracking_error,
    treynor,
    up_capture,
)
from .rolling import ROLLING_WINDOWS, rolling_return, rolling_returns
from .series_ops import align, align_dated, between

__all__ = [
    "align",
    "align_dated",
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
    # §6 benchmark-relative pure functions
    "excess_return",
    "tracking_error",
    "information_ratio",
    "beta",
    "correlation",
    "r_squared",
    "AlphaResult",
    "jensens_alpha",
    "treynor",
    "up_capture",
    "down_capture",
    "hit_rate",
    "RELATIVE_ROLLING_WINDOWS",
    "rolling_excess_return",
    "rolling_beta",
    "rolling_correlation",
    "rolling_betas",
    "rolling_correlations",
    # §6 benchmark-relative adapters
    "excess_return_of",
    "tracking_error_of",
    "information_ratio_of",
    "beta_of",
    "correlation_of",
    "r_squared_of",
    "jensens_alpha_of",
    "treynor_of",
    "up_capture_of",
    "down_capture_of",
    "hit_rate_of",
    "rolling_excess_return_of",
    "rolling_beta_of",
    "rolling_correlation_of",
]
