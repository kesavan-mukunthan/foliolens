"""F1 per-fund panel assembly — composes spec-analytics functions into one entry.

Computes nothing spec-analytics does not already own (``spec-flexicap-page §8``:
"call, don't reimplement"). Every figure here is either read verbatim off the
§5 metrics artifact (``build_metrics``), the return engine's figure of record
(``returns/engine.period_return``), or a §6/§7 pure function applied to a
trailing slice of the already-materialised monthly series. The only "new" logic
is the composition: which window to slice, which two series to hand to which
existing function, and how to shape the result as JSON.

Two phases, mirroring the natural dependency:

1. :func:`build_fund_panel` — one fund at a time, no cohort knowledge. Produces
   a :class:`FundPanel` carrying the flat metrics map, the calendar-year
   returns, the alpha objects (value + t-stat + window, never a naked point
   estimate — ``CLAUDE.md``), the rolling panels, and the benchmark identity
   block (with the tier-fallback annotation when the stated tier-1 index has
   not landed, ``spec-flexicap-page §1``).
2. :func:`assemble_universe` — the §7 cross-section over every panel at once:
   percentile ranks (+ history, where a rolling panel backs the metric-window),
   category aggregates, and the final ``metrics.json`` shape (``§3``).

Nulls are explicit everywhere (insufficient history, a metric that could not
be computed, or a value that came out non-finite) — never a fabricated figure,
never a raised error propagating out of one fund into the whole build.

The per-fund ``series`` block (:func:`_growth_of_10k`, :func:`_underwater_series`)
is a distinct, chart-only sibling of ``rolling``: month-end grain, visual-grade
float, never a figure of record (the headline max-drawdown metric stays the
daily-basis ``max_drawdown_SI`` already in ``metrics``). Both are derived
straight through the existing ``returns/convert.to_index`` seam — no new
spec-analytics metric convention, only a different base level and a longer
(unwindowed) slice than the rolling panels use.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import numpy as np

from foliolens.analytics import (
    SeriesPoint,
    build_metrics,
    category_aggregate,
    percentile_ranks,
    rank_history,
)
from foliolens.analytics import relative as relative_metrics
from foliolens.analytics.drawdown import underwater
from foliolens.analytics.metrics import period_return_abs
from foliolens.analytics.relative import RELATIVE_ROLLING_WINDOWS, rolling_excess_return
from foliolens.analytics.series_ops import align_dated, between
from foliolens.benchmark_map import TIER1
from foliolens.model.investments import Investment
from foliolens.model.sources import ReturnSource
from foliolens.model.value_objects import ReturnSeries
from foliolens.returns.convert import to_index
from foliolens.returns.engine import period_return
from foliolens.returns.frequency import Frequency

#: Artifact schema version for this page's durable output (``spec-flexicap-page §3``).
SCHEMA_VERSION = "flexipage-1"

#: Calendar years rendered per fund (``spec-flexicap-page §2``).
CALENDAR_YEARS: tuple[int, ...] = (2023, 2024, 2025)

#: Trailing figure-of-record periods, fed to ``build_metrics`` verbatim
#: (``spec-analytics §5``: the artifact references them, never recomputes).
_TRAILING_PERIODS: tuple[str, ...] = ("1Y", "3Y", "5Y", "SI")

#: Windows for the vs-yardstick relative set (excess/TE/IR/beta/alpha) — the
#: spec's default "Windows 1Y/3Y/5Y unless stated" (§2).
_RELATIVE_WINDOWS: dict[str, int] = {"1Y": 12, "3Y": 36, "5Y": 60}

#: Cross-sectional metric-windows ranked + aggregated, and whether higher is
#: better. Confined to metric-windows spec-analytics already computes (via
#: ``build_metrics`` or this module's relative-window composition) — no new
#: metric is invented to fill out the ranking table. Rolling volatility/Sharpe
#: (named in spec-flexicap-page §2's rolling-panel bullet) have no pure
#: function yet in spec-analytics §4/§6, so they are out of scope for F1
#: (the executor guard: "no new metric computations — assembly only").
RANK_SPECS: dict[str, bool] = {
    "return_1Y": True,
    "return_3Y": True,
    "return_5Y": True,
    "volatility_1Y": False,
    "volatility_3Y": False,
    "volatility_5Y": False,
    "sharpe_1Y": True,
    "sharpe_3Y": True,
    "sharpe_5Y": True,
    "sortino_1Y": True,
    "sortino_3Y": True,
    "sortino_5Y": True,
    "calmar_1Y": True,
    "calmar_3Y": True,
    "calmar_5Y": True,
    "max_drawdown_SI": True,  # less negative is better
    "excess_return_1Y": True,
    "excess_return_3Y": True,
    "excess_return_5Y": True,
    "tracking_error_1Y": False,
    "tracking_error_3Y": False,
    "tracking_error_5Y": False,
    "information_ratio_1Y": True,
    "information_ratio_3Y": True,
    "information_ratio_5Y": True,
    "alpha_1Y": True,
    "alpha_3Y": True,
    "alpha_5Y": True,
}

#: The rolling panel (already computed onto the fund panel) that backs each
#: rankable metric-window's rank *history*. Metric-windows absent here still
#: get a latest percentile rank; their history is an explicit empty list — no
#: rolling series exists for them (never fabricated).
_RANK_HISTORY_PANEL: dict[str, str] = {
    "return_1Y": "rolling_return_1Y",
    "return_3Y": "rolling_return_3Y",
    "return_5Y": "rolling_return_5Y",
    "excess_return_1Y": "rolling_excess_return_1Y",
    "excess_return_3Y": "rolling_excess_return_3Y",
    "sharpe_1Y": "rolling_sharpe_1Y",
    "sharpe_3Y": "rolling_sharpe_3Y",
}

#: Base level for the "growth of ₹10,000" chart series (spec-flexicap-page
#: §4 chart wiring) — a display convention, distinct from the analytics
#: layer's own ``Decimal("100")`` return-series base.
_GROWTH_OF_10K_BASE = Decimal("10000")


def _safe_float(value: float) -> float | None:
    """A finite float, or ``None`` (mirrors ``artifact._null_safe``'s NaN/Inf rule)."""
    return value if math.isfinite(value) else None


def _trailing(rs: ReturnSeries, months: int) -> ReturnSeries | None:
    """The last ``months`` points of ``rs``; ``None`` if the fund is too young."""
    if len(rs) < months:
        return None
    lo = len(rs) - months
    return ReturnSeries(
        dates=rs.dates[lo:], values=rs.values[lo:], frequency=rs.frequency, base=rs.base
    )


def _engine_return(source: ReturnSource, period: str, as_of: date) -> float | None:
    """One trailing figure of record via the return engine; ``None`` if undefined."""
    try:
        result = period_return(source, period, as_of)
    except ValueError:
        return None
    return _safe_float(float(result.value))


def figures_of_record(source: ReturnSource, as_of: date) -> dict[str, float | None]:
    """Trailing 1Y/3Y/5Y/SI CAGRs from the return engine, fed to ``build_metrics``
    verbatim (``spec-analytics §5``'s ``figures_of_record`` parameter) — never
    recomputed by the analytics layer.
    """
    return {
        f"return_{p}": _engine_return(source, p, as_of) for p in _TRAILING_PERIODS
    }


def calendar_year_returns(
    rs: ReturnSeries, years: tuple[int, ...] = CALENDAR_YEARS
) -> dict[str, float | None]:
    """Absolute compounded return per calendar year (``between`` + ``period_return_abs``,
    ``spec-flexicap-page §2``). A year outside the fund's history yields ``None``.
    """
    out: dict[str, float | None] = {}
    for year in years:
        window = between(rs, date(year, 1, 1), date(year, 12, 31))
        if len(window) < 1:
            out[str(year)] = None
            continue
        try:
            value = period_return_abs(window, window.dates[0], window.dates[-1])
        except ValueError:
            out[str(year)] = None
            continue
        out[str(year)] = _safe_float(value)
    return out


def _relative_scalar(
    fn: object,
    fund_rs: ReturnSeries,
    yardstick_rs: ReturnSeries,
    months: int,
) -> float | None:
    """Apply a §6 two-series pure function to the fund's trailing ``months`` slice."""
    sliced = _trailing(fund_rs, months)
    if sliced is None:
        return None
    try:
        value = fn(sliced, yardstick_rs)  # type: ignore[operator]
    except ValueError:
        return None
    return _safe_float(value)


def _alpha_for_window(
    fund_rs: ReturnSeries,
    yardstick_rs: ReturnSeries,
    rf_rs: ReturnSeries,
    months: int,
) -> dict[str, object] | None:
    """Jensen's alpha over the fund's trailing ``months`` slice, with t-stat + window.

    Never a naked point estimate (``CLAUDE.md``): value, t-stat, n and the
    estimation window travel together, or the whole object is ``None``.
    """
    sliced = _trailing(fund_rs, months)
    if sliced is None:
        return None
    try:
        result = relative_metrics.jensens_alpha(sliced, yardstick_rs, rf_rs)
    except ValueError:
        return None
    if not (math.isfinite(result.alpha) and math.isfinite(result.t_stat)):
        return None
    return {
        "value": result.alpha,
        "t_stat": result.t_stat,
        "n": result.n,
        "window_start": result.start.isoformat(),
        "window_end": result.end.isoformat(),
    }


def benchmark_block(
    stated_code: str | None,
    stated_tier: str | None,
    yardstick_code: str,
    *,
    tier1_landed: bool,
) -> dict[str, str | None]:
    """The benchmark identity block, with the F1 tier-fallback annotation.

    ``spec-flexicap-page §1``: when the stated tier-1 index series has not
    landed (BSE500TRI, as of this milestone), the stated-benchmark
    reconciliation leg is skipped (that leg lives entirely in the local,
    uncommitted reconciliation step — never in this artifact) and the tier is
    recorded as the literal ``"alternate-pending-tier1"`` rather than silently
    substituting the alternate as if it were the fund's real stated tier.
    Yardstick metrics (vs ``yardstick_code``) are unaffected either way.
    """
    tier = stated_tier
    if stated_tier == TIER1 and not tier1_landed:
        tier = "alternate-pending-tier1"
    return {"stated": stated_code, "tier": tier, "yardstick": yardstick_code}


def _growth_of_10k(
    fund_rs: ReturnSeries, yardstick_rs: ReturnSeries
) -> dict[str, list[dict[str, object]]] | None:
    """Month-end growth of ₹10,000, fund vs category yardstick, over their
    common month-end history (chart-only series, ``spec-flexicap-page §4``).

    Both legs rebase to the *same* ₹10,000 start so the chart reads as a
    genuine side-by-side comparison, not two independently-based curves.
    ``None`` when the fund and yardstick share no common month-end date
    (never a fabricated single-point chart).
    """
    dates, fund_vals, yardstick_vals = align_dated(fund_rs, yardstick_rs)
    if not dates:
        return None
    fund_idx = to_index(
        ReturnSeries(
            dates=dates, values=fund_vals, frequency=fund_rs.frequency, base=_GROWTH_OF_10K_BASE
        )
    )
    yardstick_idx = to_index(
        ReturnSeries(
            dates=dates,
            values=yardstick_vals,
            frequency=yardstick_rs.frequency,
            base=_GROWTH_OF_10K_BASE,
        )
    )
    return {
        "fund": [
            {"date": d.isoformat(), "value": float(v)}
            for d, v in zip(fund_idx.dates, fund_idx.levels)
        ],
        "yardstick": [
            {"date": d.isoformat(), "value": float(v)}
            for d, v in zip(yardstick_idx.dates, yardstick_idx.levels)
        ],
    }


def _underwater_series(fund_rs: ReturnSeries) -> list[dict[str, object]]:
    """Month-end drawdown-from-peak over the fund's full monthly history
    (chart-only series, ``spec-flexicap-page §4``) — the headline
    ``max_drawdown_SI`` figure stays the daily-basis metric already in
    ``metrics``; this is a coarser, monthly-grain companion for the chart.
    """
    uw = underwater(to_index(fund_rs))
    return [
        {"date": d.isoformat(), "value": float(v)}
        for d, v in zip(uw.dates, uw.values)
    ]


@dataclass(frozen=True)
class FundPanel:
    """One fund's F1 entry, before cross-sectional ranking is layered on."""

    amfi_code: str
    scheme_name: str
    fund_house: str
    benchmark: dict[str, str | None]
    metrics: dict[str, float | None]
    calendar_years: dict[str, float | None]
    alpha: dict[str, dict[str, object] | None]
    rolling: dict[str, tuple[SeriesPoint, ...]]
    series: dict[str, object]


def build_fund_panel(
    *,
    amfi_code: str,
    scheme_name: str,
    fund_house: str,
    fund: Investment,
    rf: Investment,
    yardstick: Investment,
    stated_code: str | None,
    stated_tier: str | None,
    yardstick_code: str,
    tier1_landed: bool,
    as_of: date,
) -> FundPanel:
    """Assemble one fund's panel: the §5 artifact extended with flexipage fields.

    ``fund.returns`` is read once here (and once more inside ``build_metrics``,
    which is the artifact's own single-read contract); every figure beyond that
    delegates to an existing pure function over a trailing slice — no arithmetic
    is invented in this function.
    """
    fof = figures_of_record(fund.source, as_of)
    mr = build_metrics(
        fund,
        rf,
        metadata={"scheme_name": scheme_name, "fund_house": fund_house},
        figures_of_record=fof,
        as_of=as_of,
    )
    metrics = dict(mr.metrics)
    rolling = dict(mr.series)

    fund_rs = fund.returns
    yardstick_rs = yardstick.returns
    rf_rs = rf.returns

    for label, months in RELATIVE_ROLLING_WINDOWS.items():
        panel = rolling_excess_return(fund_rs, yardstick_rs, months)
        rolling[f"rolling_excess_return_{label}"] = tuple(
            SeriesPoint(date=d, value=float(v))
            for d, v in zip(panel.dates, panel.values)
        )
        sharpe_panel = relative_metrics.rolling_sharpe(fund_rs, rf_rs, months)
        rolling[f"rolling_sharpe_{label}"] = tuple(
            SeriesPoint(date=d, value=float(v))
            for d, v in zip(sharpe_panel.dates, sharpe_panel.values)
        )

    series: dict[str, object] = {
        "growth_10k": _growth_of_10k(fund_rs, yardstick_rs),
        "underwater": _underwater_series(fund_rs),
    }

    alpha: dict[str, dict[str, object] | None] = {}
    for label, months in _RELATIVE_WINDOWS.items():
        metrics[f"excess_return_{label}"] = _excess_return_scalar(
            fund.source, yardstick.source, label, as_of
        )
        metrics[f"tracking_error_{label}"] = _relative_scalar(
            relative_metrics.tracking_error, fund_rs, yardstick_rs, months
        )
        metrics[f"information_ratio_{label}"] = _relative_scalar(
            relative_metrics.information_ratio, fund_rs, yardstick_rs, months
        )
        metrics[f"beta_{label}"] = _relative_scalar(
            relative_metrics.beta, fund_rs, yardstick_rs, months
        )
        alpha[f"alpha_{label}"] = _alpha_for_window(fund_rs, yardstick_rs, rf_rs, months)

    return FundPanel(
        amfi_code=amfi_code,
        scheme_name=scheme_name,
        fund_house=fund_house,
        benchmark=benchmark_block(
            stated_code, stated_tier, yardstick_code, tier1_landed=tier1_landed
        ),
        metrics=metrics,
        calendar_years=calendar_year_returns(fund_rs),
        alpha=alpha,
        rolling=rolling,
        series=series,
    )


def _excess_return_scalar(
    fund_source: ReturnSource, yardstick_source: ReturnSource, period: str, as_of: date
) -> float | None:
    """Trailing excess return: the fund's figure of record minus the yardstick's.

    Both anchor to the same ``as_of`` and ``period``, so both resolve the same
    SEBI absolute/CAGR method off the same ``start_anchor`` date — the
    subtraction is well-defined (``spec-flexicap-page §2``: "excess return"
    vs category yardstick).
    """
    fund_value = _engine_return(fund_source, period, as_of)
    yardstick_value = _engine_return(yardstick_source, period, as_of)
    if fund_value is None or yardstick_value is None:
        return None
    return fund_value - yardstick_value


def _metric_value(panel: FundPanel, key: str) -> float | None:
    """The cross-sectional value for one metric-window: flat metric or alpha.value."""
    if key.startswith("alpha_"):
        entry = panel.alpha.get(key)
        return entry["value"] if entry else None  # type: ignore[return-value]
    return panel.metrics.get(key)


def _panel_to_return_series(panel: FundPanel, panel_key: str) -> ReturnSeries:
    points = panel.rolling.get(panel_key, ())
    return ReturnSeries(
        dates=tuple(p.date for p in points),
        values=np.array([p.value for p in points], dtype=np.float64),
        frequency=Frequency.MONTHLY,
    )


def _to_display_pct(pct: float, n_ranked: int) -> float:
    """Flip ``peer.py``'s higher-is-better percentile to the rendered convention.

    ``display_pct = 100 + 100/n_ranked − pct`` — lower is better, 1 ≈ top of
    cohort (``spec-flexicap-page §2/§3``). ``analytics/peer.py`` is never
    touched (spec-analytics §7 owns that direction); this is a presentation-
    facing transform applied once, here, before the artifact is written.
    Clamped to ``[0, 100]``: the algebra guarantees that range exactly, but
    float subtraction can overshoot it by an epsilon at the boundary.
    """
    display = 100.0 + 100.0 / n_ranked - pct
    return min(100.0, max(0.0, display))


def assemble_universe(
    panels: list[FundPanel], *, as_of: date, category: str, yardstick_code: str
) -> dict[str, object]:
    """The §7 cross-section over every panel, plus the full ``metrics.json`` shape.

    Ranks and aggregates are computed once, over the whole cohort, per
    :data:`RANK_SPECS` metric-window — the caller-supplied cohort spec-analytics
    §7 deliberately stays blind to (it never knows this is "flexicap"). Every
    written ``pct`` (latest and history) is then flipped to the display
    convention (:func:`_to_display_pct`) — lower is better, 1 ≈ top of cohort.
    """
    ranks: dict[str, dict[str, float | None]] = {}
    histories: dict[str, dict[str, ReturnSeries]] = {}
    aggregates: dict[str, dict[str, float | int | None]] = {}

    for key, higher_is_better in RANK_SPECS.items():
        cohort_values = {p.amfi_code: _metric_value(p, key) for p in panels}
        raw_ranks = percentile_ranks(cohort_values, higher_is_better=higher_is_better)
        agg = category_aggregate(cohort_values)
        aggregates[key] = {"median": agg.median, "q1": agg.q1, "q3": agg.q3}
        n_ranked = agg.count
        ranks[key] = {
            fid: (_to_display_pct(pct, n_ranked) if pct is not None else None)
            for fid, pct in raw_ranks.items()
        }

        panel_key = _RANK_HISTORY_PANEL.get(key)
        if panel_key is not None:
            cohort_panels = {
                p.amfi_code: _panel_to_return_series(p, panel_key) for p in panels
            }
            raw_history = rank_history(cohort_panels, higher_is_better=higher_is_better)
            # Same lower-is-better flip, but ``n_ranked`` is per-date here: the
            # cohort ``rank_history`` ranked against at date ``d`` is exactly
            # the funds whose returned series carries a point at ``d`` (its
            # own docstring's "per-date inner selection") — counting that
            # directly mirrors the exact denominator used inside it.
            date_counts: dict[date, int] = {}
            for rs in raw_history.values():
                for d in rs.dates:
                    date_counts[d] = date_counts.get(d, 0) + 1
            histories[key] = {
                fid: ReturnSeries(
                    dates=rs.dates,
                    values=np.array(
                        [
                            _to_display_pct(v, date_counts[d])
                            for d, v in zip(rs.dates, rs.values)
                        ],
                        dtype=np.float64,
                    ),
                    frequency=rs.frequency,
                    base=rs.base,
                )
                for fid, rs in raw_history.items()
            }
        else:
            histories[key] = {}

    funds_out = []
    for p in panels:
        fund_ranks: dict[str, dict[str, object]] = {}
        for key in RANK_SPECS:
            pct = ranks[key].get(p.amfi_code)
            hist_series = histories[key].get(p.amfi_code)
            history = (
                [
                    {"date": d.isoformat(), "pct": float(v)}
                    for d, v in zip(hist_series.dates, hist_series.values)
                ]
                if hist_series is not None
                else []
            )
            fund_ranks[key] = {"pct": pct, "history": history}

        funds_out.append(
            {
                "amfi_code": p.amfi_code,
                "scheme_name": p.scheme_name,
                "fund_house": p.fund_house,
                "benchmark": p.benchmark,
                "metrics": p.metrics,
                "calendar_years": p.calendar_years,
                "alpha": p.alpha,
                "rolling": {
                    name: [pt.to_dict() for pt in pts]
                    for name, pts in p.rolling.items()
                },
                "series": p.series,
                "ranks": fund_ranks,
                "commentary": None,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of.isoformat(),
        "universe": {
            "category": category,
            "count": len(panels),
            "yardstick": yardstick_code,
            "aggregates": aggregates,
        },
        "funds": funds_out,
    }
