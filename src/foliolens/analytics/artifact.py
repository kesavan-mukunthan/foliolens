"""§5 metrics artifact — the durable, versioned per-fund output contract.

``MetricsResult`` is the value object the analytics layer emits for one
investment: ``{metadata, metrics, series}`` under a ``schema_version``. It is the
seam the disposable renderer (``spec-flexicap-page``) and, later, spec-api
consume — shaped as the eventual API payload, not a rendering.

Shape (the *generic* contract; ``spec-flexicap-page §3`` is the first consumer):

* ``metrics`` — a **flat** ``{metric_window: value|null}`` map. ``value`` is a
  float exactly as computed (no re-rounding — the presentation layer rounds);
  ``null`` (Python ``None``) is explicit for **insufficient history** — a window
  longer than the fund's life, or a statistic needing more points than exist.
  Nulls are never invented figures and never errors: a young fund yields nulls,
  not exceptions.
* ``series`` — rolling panels, one per ``panel_name``, each a list of
  ``{date, value}`` points stamped at the window-end month-end (ISO-8601 dates).
* ``metadata`` — fund identity + ``as_of``; opaque to this layer.

Serialisation is a pure ``to_dict`` / ``from_dict`` round-trip over JSON-native
types (str / float / None / list / dict), deterministic across runs — the same
stored inputs re-serialise identically (``spec-analytics §5`` acceptance).

The metric arithmetic stays in the pure functions of ``metrics`` /
``distribution`` / ``rolling`` and the §3 daily adapters; this builder reads
``investment.returns`` **once**, slices it for the trailing windows, and
orchestrates — it invents no arithmetic.

This is the **generic** metrics contract. Flexipage-specific fields (ranks,
commentary, yardstick labels, category aggregates) are **not** built here —
``spec-flexicap-page`` F1 composes those on top; this layer never forces a
downstream recomputation of what it already carries.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from foliolens.model.investments import Investment
from foliolens.model.value_objects import ReturnSeries

from .distribution import best_period, kurtosis, pct_positive, skew, worst_period
from .drawdown import cvar_of, max_drawdown_of, var_historical_of
from .metrics import (
    calmar,
    downside_deviation,
    period_return_abs,
    sharpe,
    sortino,
    volatility,
)
from .rolling import rolling_returns
from .series_ops import between

#: Artifact schema version — bump on any breaking shape change to ``to_dict``.
SCHEMA_VERSION = "analytics-1"

#: Trailing / rolling window labels → length in months. ``SI`` (since inception)
#: is the whole available series and carries no fixed month count.
_WINDOW_MONTHS: dict[str, int] = {"1Y": 12, "3Y": 36, "5Y": 60}

#: Sub-year period-return windows (SEBI ``< 1 year`` → absolute), in months.
#: ``YTD`` is handled separately (calendar-year-to-date, not a fixed length).
_PERIOD_MONTHS: dict[str, int] = {"1M": 1, "3M": 3, "6M": 6}


@dataclass(frozen=True)
class SeriesPoint:
    """One dated point in a rolling panel: an ISO-8601 date and a float value."""

    date: date
    value: float

    def to_dict(self) -> dict[str, Any]:
        return {"date": self.date.isoformat(), "value": self.value}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> SeriesPoint:
        return cls(date=date.fromisoformat(d["date"]), value=float(d["value"]))


@dataclass(frozen=True)
class MetricsResult:
    """Versioned per-fund metrics artifact: ``{metadata, metrics, series}``.

    A pure value object — no computation, only carriage and (de)serialisation.
    Equality is structural over the three maps, so a ``from_dict(to_dict(x))``
    round-trip reconstructs an equal object (the round-trip acceptance).
    """

    schema_version: str
    metadata: Mapping[str, Any]
    metrics: Mapping[str, float | None]
    series: Mapping[str, tuple[SeriesPoint, ...]]

    def to_dict(self) -> dict[str, Any]:
        """JSON-native nested dict; deterministic (insertion-ordered) across runs."""
        return {
            "schema_version": self.schema_version,
            "metadata": dict(self.metadata),
            "metrics": dict(self.metrics),
            "series": {
                name: [p.to_dict() for p in points]
                for name, points in self.series.items()
            },
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> MetricsResult:
        return cls(
            schema_version=d["schema_version"],
            metadata=dict(d["metadata"]),
            metrics=dict(d["metrics"]),
            series={
                name: tuple(SeriesPoint.from_dict(p) for p in points)
                for name, points in d["series"].items()
            },
        )


def _null_safe(fn: Callable[[], float]) -> float | None:
    """Run a metric, mapping insufficient-history / absent-source / non-finite → ``None``.

    Insufficient history surfaces as ``ValueError`` from the pure functions;
    a missing daily NAV source (``SeriesInvestment``) surfaces as
    ``NotImplementedError``. Both mean "no value to report" → explicit ``null``,
    never a raised error (``spec-analytics §5`` null-propagation). A non-finite
    result (e.g. Calmar with no drawdown → NaN) is also reported as ``null`` so
    the artifact stays valid JSON without relying on ``allow_nan``.
    """
    try:
        value = fn()
    except (ValueError, NotImplementedError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _trailing(rs: ReturnSeries, months: int) -> ReturnSeries | None:
    """The last ``months`` points of ``rs`` as a ``ReturnSeries``; ``None`` if too short.

    The window-shorter-than-history rule (``spec-analytics §4``): a fund with
    fewer than ``months`` monthly points has no trailing ``months``-window figure,
    so the caller emits ``null`` rather than a partial window.
    """
    if len(rs) < months:
        return None
    lo = len(rs) - months
    return ReturnSeries(dates=rs.dates[lo:], values=rs.values[lo:], base=rs.base)


def build_metrics(
    investment: Investment,
    rf: Investment,
    *,
    metadata: Mapping[str, Any] | None = None,
    figures_of_record: Mapping[str, float | None] | None = None,
    as_of: date | None = None,
    schema_version: str = SCHEMA_VERSION,
) -> MetricsResult:
    """Assemble the ``MetricsResult`` for one investment from the metric functions.

    Orchestration only — every figure comes from a pure function over the
    materialised monthly series (read once as ``investment.returns``) or from the
    §3 daily adapters over ``investment.source``. Windowed risk metrics take the
    trailing ``window_months`` slice and fall to ``null`` when history is shorter
    than the window. Daily-basis metrics (drawdown / VaR / CVaR) are ``null``
    when the investment carries no NAV source. rf is an Investment; its
    ``.returns`` feed the two-series metrics.

    Trailing 1Y/3Y/5Y/SI CAGRs are the return engine's **figures of record** —
    this layer never recomputes them. The caller that holds the engine output
    passes them in via ``figures_of_record`` (e.g. ``{"return_1Y": 0.18, …}``)
    and they are merged into the flat metrics map verbatim: the artifact
    *references* them, so a downstream consumer never re-derives them.
    """
    rs = investment.returns
    rf_rs = rf.returns
    if as_of is None and len(rs):
        as_of = rs.dates[-1]

    meta: dict[str, Any] = {"id": investment.id}
    if as_of is not None:
        meta["as_of"] = as_of.isoformat()
    if metadata is not None:
        meta.update(metadata)

    metrics_map: dict[str, float | None] = {}

    # Sub-year period returns (absolute, compounded over the monthly series).
    for label, months in _PERIOD_MONTHS.items():
        metrics_map[f"return_{label}"] = _on(
            _trailing(rs, months),
            lambda s: period_return_abs(s, s.dates[0], s.dates[-1]),
        )
    metrics_map["return_YTD"] = _ytd_return(rs, as_of)

    # Windowed risk / risk-adjusted metrics: trailing 1Y/3Y/5Y + since-inception.
    windows: dict[str, ReturnSeries | None] = {
        label: _trailing(rs, months) for label, months in _WINDOW_MONTHS.items()
    }
    windows["SI"] = rs if len(rs) else None
    for label, w in windows.items():
        metrics_map[f"volatility_{label}"] = _on(w, lambda s: volatility(s))
        metrics_map[f"downside_deviation_{label}"] = _on(
            w, lambda s: downside_deviation(s, rf_rs)
        )
        metrics_map[f"sharpe_{label}"] = _on(w, lambda s: sharpe(s, rf_rs))
        metrics_map[f"sortino_{label}"] = _on(w, lambda s: sortino(s, rf_rs))
        metrics_map[f"calmar_{label}"] = _on(w, lambda s: calmar(s))

    # Since-inception distribution statistics.
    metrics_map["pct_positive_SI"] = _on(windows["SI"], lambda s: pct_positive(s))
    metrics_map["best_period_SI"] = _on(windows["SI"], lambda s: best_period(s))
    metrics_map["worst_period_SI"] = _on(windows["SI"], lambda s: worst_period(s))
    metrics_map["skew_SI"] = _on(windows["SI"], lambda s: skew(s))
    metrics_map["kurtosis_SI"] = _on(windows["SI"], lambda s: kurtosis(s))

    # Daily-basis family (reads investment.source; null when there is no source).
    metrics_map["max_drawdown_SI"] = _null_safe(lambda: max_drawdown_of(investment))
    metrics_map["var95_SI"] = _null_safe(lambda: var_historical_of(investment))
    metrics_map["cvar95_SI"] = _null_safe(lambda: cvar_of(investment))

    # Referenced figures of record (trailing CAGRs from the return engine),
    # merged verbatim — never recomputed here (see docstring).
    if figures_of_record is not None:
        metrics_map.update(figures_of_record)

    # Rolling panels — stamped at each window-end month-end (ISO-8601).
    series: dict[str, tuple[SeriesPoint, ...]] = {}
    for label, panel in rolling_returns(rs).items():
        series[f"rolling_return_{label}"] = tuple(
            SeriesPoint(date=d, value=float(v))
            for d, v in zip(panel.dates, panel.values)
        )

    return MetricsResult(
        schema_version=schema_version,
        metadata=meta,
        metrics=metrics_map,
        series=series,
    )


def _on(
    window: ReturnSeries | None, fn: Callable[[ReturnSeries], float]
) -> float | None:
    """Apply a metric to a trailing-window slice; ``None`` when the slice is absent."""
    if window is None:
        return None
    return _null_safe(lambda: fn(window))


def _ytd_return(rs: ReturnSeries, as_of: date | None) -> float | None:
    """Absolute compounded return from the first month-end of ``as_of``'s year."""
    if as_of is None:
        return None
    window = between(rs, date(as_of.year, 1, 1), as_of)
    if len(window) < 1:
        return None
    return _null_safe(
        lambda: period_return_abs(window, window.dates[0], window.dates[-1])
    )
