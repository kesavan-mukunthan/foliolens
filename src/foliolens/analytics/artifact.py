"""§5 metrics artifact — the durable, versioned per-fund output contract.

``MetricsResult`` is the value object the analytics layer emits for one
investment: ``{metadata, metrics, series, refused}`` under a ``schema_version``.
It is the seam the disposable renderer (``spec-flexicap-page``) and, later,
spec-api consume — shaped as the eventual API payload, not a rendering.

Shape (the *generic* contract; ``spec-flexicap-page §3`` is the first consumer):

* ``metrics`` — a **flat** ``{metric_window: value|null}`` map. ``value`` is a
  float exactly as computed (no re-rounding — the presentation layer rounds);
  ``null`` (Python ``None``) is explicit for **insufficient history** — a window
  longer than the fund's life, or a statistic needing more points than exist.
  Nulls are never invented figures and never errors: a young fund yields nulls,
  not exceptions.
* ``series`` — rolling panels, one per ``panel_name``, each a list of
  ``{date, value}`` points stamped at the window-end month-end (ISO-8601 dates).
* ``refused`` — a **flat** ``{metric_window: reason}`` map, one entry for every
  ``metrics`` key that came out ``null`` because its underlying pure function
  raised ``InsufficientHistoryError`` (``analytics/series_ops.py``) — e.g.
  ``"insufficient_history(required=36, available=14)"``. Every other cause of
  ``null`` (the window itself absent because ``as_of`` isn't reached, a
  non-finite result) carries no ``refused`` entry — this map attributes only
  the insufficient-history nulls, never every null in ``metrics``.
* ``metadata`` — fund identity + ``as_of``; opaque to this layer.

Serialisation is a pure ``to_dict`` / ``from_dict`` round-trip over JSON-native
types (str / float / None / list / dict), deterministic across runs — the same
stored inputs re-serialise identically (``spec-analytics §5`` acceptance).

The metric arithmetic stays in the pure functions of ``metrics`` /
``distribution`` / ``rolling`` and the §3 daily adapters; this builder reads
``investment.returns(Frequency.MONTHLY)`` **once**, date-slices it for every
trailing window — the sub-year 1M/3M/6M period returns and the 1Y/3Y/5Y
windows alike (``_trailing``: the calendar span ``(as_of − N months, as_of]``,
not the last ``N`` observations) — and orchestrates — it invents no arithmetic.

This is the **generic** metrics contract. Flexipage-specific fields (ranks,
commentary, yardstick labels, category aggregates) are **not** built here —
``spec-flexicap-page`` F1 composes those on top; this layer never forces a
downstream recomputation of what it already carries.
"""
from __future__ import annotations

import bisect
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from foliolens.model.investments import Investment
from foliolens.model.value_objects import ReturnSeries
from foliolens.returns.frequency import Frequency

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
from .rolling import _subtract_months, rolling_returns
from .series_ops import InsufficientHistoryError, between

#: Artifact schema version — bump on any breaking shape change to ``to_dict``.
#: Bumped to ``analytics-2`` for the ``refused`` field (B3: attributable nulls).
SCHEMA_VERSION = "analytics-2"

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
    refused: Mapping[str, str]

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
            "refused": dict(self.refused),
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
            refused=dict(d.get("refused", {})),
        )


def _null_safe(
    fn: Callable[[], float],
    *,
    metric: str | None = None,
    refused: dict[str, str] | None = None,
) -> float | None:
    """Run a metric, mapping ``InsufficientHistoryError`` → ``None`` — nothing else.

    Only insufficient history is a valid null path (``spec-analytics §5``
    null-propagation): a bare ``ValueError`` (frequency mismatch, a
    degenerate zero-variance input) or a ``NotImplementedError`` (no NAV
    source) is a genuine failure and propagates uncaught, never silently
    swallowed — a null in the output must always trace to a stated
    insufficient-history reason. A non-finite result (e.g. Calmar with no
    drawdown → NaN) is also reported as ``null`` so the artifact stays valid
    JSON without relying on ``allow_nan``.

    When ``metric``/``refused`` are supplied, the shortfall is recorded as
    ``refused[metric] = "insufficient_history(required=…, available=…)"`` —
    the flexipage layer's per-window ``refused`` disclosure reads this map.
    """
    try:
        value = fn()
    except InsufficientHistoryError as exc:
        if metric is not None and refused is not None:
            refused[metric] = (
                f"insufficient_history(required={exc.required}, available={exc.available})"
            )
        return None
    if not math.isfinite(value):
        return None
    return value


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
    materialised monthly series (read once as ``investment.returns(Frequency.MONTHLY)``) or from the
    §3 daily adapters over ``investment.source``. The sub-year 1M/3M/6M period
    returns and the windowed 1Y/3Y/5Y risk metrics take the trailing
    **calendar-date** slice (``_trailing``: the panel entries dated within
    ``(as_of − N months, as_of]``, whatever survives — not the last ``N``
    observations) and fall to ``null`` when history is shorter than the
    window. Daily-basis metrics (drawdown / VaR / CVaR) are ``null``
    when the investment carries no NAV source. rf is an Investment; its
    ``.returns(Frequency.MONTHLY)`` feed the two-series metrics.

    Trailing 1Y/3Y/5Y/SI CAGRs are the return engine's **figures of record** —
    this layer never recomputes them. The caller that holds the engine output
    passes them in via ``figures_of_record`` (e.g. ``{"return_1Y": 0.18, …}``)
    and they are merged into the flat metrics map verbatim: the artifact
    *references* them, so a downstream consumer never re-derives them.

    Common anchoring (``spec-analytics``): every fixed-window metric (the
    sub-year period returns, YTD, and the 1Y/3Y/5Y windows) is measured
    ending exactly at ``as_of`` — never at ``investment``'s own last month.
    When the caller passes no ``as_of``, it defaults to this investment's own
    last date (single-fund use, unchanged from before); when a caller (a
    cross-sectional run) passes an explicit shared ``as_of`` that this
    investment's panel does not reach, every fixed-window metric emits
    ``null`` via the existing null path rather than silently falling back to
    a different, incomparable end date. ``SI`` (since-inception) is the one
    exception — it is deliberately *not* anchored, since it reports the
    investment's own full history, not a fixed cross-sectional window.
    """
    rs = investment.returns(Frequency.MONTHLY)
    rf_rs = rf.returns(Frequency.MONTHLY)
    if as_of is None and len(rs):
        as_of = rs.dates[-1]
    # Narrowed to a concrete date only when it is actually in rs.dates — the
    # None case (absent as_of, or an as_of this panel never reaches) is the
    # single gate every fixed-window metric below routes its null through.
    anchor: date | None = as_of if as_of is not None and as_of in rs.dates else None

    meta: dict[str, Any] = {"id": investment.id}
    if as_of is not None:
        meta["as_of"] = as_of.isoformat()
    if metadata is not None:
        meta.update(metadata)

    metrics_map: dict[str, float | None] = {}
    refused: dict[str, str] = {}

    # Sub-year period returns (absolute, compounded over the monthly series).
    # Calendar-date slices (see ``_trailing``): on a gapped panel the N-month
    # window holds only the months surviving inside (as_of − N months, as_of],
    # never the last N observations stretched across a data hole.
    for label, months in _PERIOD_MONTHS.items():
        metrics_map[f"return_{label}"] = _on(
            _trailing(rs, anchor, months) if anchor is not None else None,
            lambda s: period_return_abs(s, s.dates[0], s.dates[-1]),
            metric=f"return_{label}",
            refused=refused,
        )
    metrics_map["return_YTD"] = (
        _ytd_return(rs, anchor, refused=refused) if anchor is not None else None
    )

    # Windowed risk / risk-adjusted metrics: trailing 1Y/3Y/5Y (anchored) +
    # since-inception (never anchored, see docstring). The 1Y/3Y/5Y windows are
    # calendar-date slices (see ``_trailing``): on a gapped panel they cover the
    # true W-year span rather than the last 12×W observations, so a metric and
    # the rf/benchmark legs it reconciles against describe the same period.
    windows: dict[str, ReturnSeries | None] = {
        label: (_trailing(rs, anchor, months) if anchor is not None else None)
        for label, months in _WINDOW_MONTHS.items()
    }
    windows["SI"] = rs if len(rs) else None
    for label, w in windows.items():
        metrics_map[f"volatility_{label}"] = _on(
            w, lambda s: volatility(s), metric=f"volatility_{label}", refused=refused
        )
        metrics_map[f"downside_deviation_{label}"] = _on(
            w,
            lambda s: downside_deviation(s, rf_rs),
            metric=f"downside_deviation_{label}",
            refused=refused,
        )
        metrics_map[f"sharpe_{label}"] = _on(
            w, lambda s: sharpe(s, rf_rs), metric=f"sharpe_{label}", refused=refused
        )
        metrics_map[f"sortino_{label}"] = _on(
            w, lambda s: sortino(s, rf_rs), metric=f"sortino_{label}", refused=refused
        )
        metrics_map[f"calmar_{label}"] = _on(
            w, lambda s: calmar(s), metric=f"calmar_{label}", refused=refused
        )

    # Since-inception distribution statistics.
    metrics_map["pct_positive_SI"] = _on(
        windows["SI"], lambda s: pct_positive(s), metric="pct_positive_SI", refused=refused
    )
    metrics_map["best_period_SI"] = _on(
        windows["SI"], lambda s: best_period(s), metric="best_period_SI", refused=refused
    )
    metrics_map["worst_period_SI"] = _on(
        windows["SI"], lambda s: worst_period(s), metric="worst_period_SI", refused=refused
    )
    metrics_map["skew_SI"] = _on(
        windows["SI"], lambda s: skew(s), metric="skew_SI", refused=refused
    )
    metrics_map["kurtosis_SI"] = _on(
        windows["SI"], lambda s: kurtosis(s), metric="kurtosis_SI", refused=refused
    )

    # Daily-basis family (reads investment.source; null when there is no source).
    metrics_map["max_drawdown_SI"] = _null_safe(
        lambda: max_drawdown_of(investment), metric="max_drawdown_SI", refused=refused
    )
    metrics_map["var95_SI"] = _null_safe(
        lambda: var_historical_of(investment), metric="var95_SI", refused=refused
    )
    metrics_map["cvar95_SI"] = _null_safe(
        lambda: cvar_of(investment), metric="cvar95_SI", refused=refused
    )

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
        refused=refused,
    )


def _year_month(d: date) -> tuple[int, int]:
    """(year, month) — the month-granular key a trailing window is sliced on."""
    return (d.year, d.month)


def _trailing(rs: ReturnSeries, as_of: date, months: int) -> ReturnSeries | None:
    """The trailing ``months``-window of ``rs`` ending at ``as_of``, sliced by
    **calendar date** — the panel entries with ``date > as_of − months`` and
    ``date ≤ as_of``.

    This is a date slice, not a last-``months``-observations slice: on a panel
    with a data hole inside the window, last-N would reach back across the hole
    and stretch the window past ``months`` calendar months, so its metric — and
    the rf / benchmark legs it reconciles against — would cover different
    periods. The date slice covers exactly the calendar window; its length is
    whatever survives (honestly fewer than ``months`` for a gapped fund), and the
    downstream metric's own minimum-observation guard decides on that truthful
    count (a window too sparse to compute refuses, disclosed via ``refused``).

    Serves both the whole-year 1Y/3Y/5Y windows and the sub-year 1M/3M/6M period
    returns — one slicer, one lower-bound convention.

    Returns ``None`` on the young-fund path — ``as_of`` absent from ``rs.dates``
    (the panel does not reach the shared anchor), or fewer than ``months`` total
    observations precede it (history shorter than the nominal window). This is
    the unchanged null contract; the lower bound is computed with the shared
    :func:`~foliolens.analytics.rolling._subtract_months` (day-clamped, mirroring
    the engine's Feb-29 handling), never new date arithmetic here.
    """
    try:
        end_i = rs.dates.index(as_of)
    except ValueError:
        return None
    if end_i + 1 < months:
        return None
    lo_bound = _subtract_months(as_of, months)
    # Compare at month granularity so the boundary *month* is excluded whole: a
    # month-end panel dates Feb on the 28th or 29th and the day-clamp can land a
    # month before the panel's true month-end, so a raw date compare would leak
    # that boundary-month entry into the window. Keyed on (year, month), the
    # contiguous window is exactly the last ``months`` entries.
    lo = bisect.bisect_right(rs.dates, _year_month(lo_bound), key=_year_month)
    return ReturnSeries(
        dates=rs.dates[lo : end_i + 1],
        values=rs.values[lo : end_i + 1],
        frequency=rs.frequency,
        base=rs.base,
    )


def _on(
    window: ReturnSeries | None,
    fn: Callable[[ReturnSeries], float],
    *,
    metric: str,
    refused: dict[str, str],
) -> float | None:
    """Apply a metric to a trailing-window slice; ``None`` when the slice is absent."""
    if window is None:
        return None
    return _null_safe(lambda: fn(window), metric=metric, refused=refused)


def _ytd_return(
    rs: ReturnSeries, as_of: date | None, *, refused: dict[str, str]
) -> float | None:
    """Absolute compounded return from the first month-end of ``as_of``'s year."""
    if as_of is None:
        return None
    window = between(rs, date(as_of.year, 1, 1), as_of)
    if len(window) < 1:
        return None
    return _null_safe(
        lambda: period_return_abs(window, window.dates[0], window.dates[-1]),
        metric="return_YTD",
        refused=refused,
    )
