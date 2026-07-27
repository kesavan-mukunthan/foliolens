"""Pre-rendered SVG charts (matplotlib, no Plotly — ``spec-flexicap-page §4``).

Every chart reads a series straight off the parsed ``metrics.json`` fund
entry; none is computed here. A chart whose backing series is absent or empty
returns ``None`` and the template omits it entirely — never an empty axes
frame (spec-flexicap-page §7-F2's "skip a chart cleanly" rule applies equally
to a young fund's empty rolling panel and to a fund/yardstick pair with no
common month-end date).
"""
from __future__ import annotations

import io
from collections.abc import Callable
from datetime import date
from typing import Any

import matplotlib

from .presentation import benchmark_display_name

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402 - backend must be set first

_FIGSIZE = (6.4, 3.2)
_DPI = 100


def _svg(fig: Any) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _dates_values(points: list[dict[str, Any]]) -> tuple[list[date], list[float]]:
    dates = [date.fromisoformat(p["date"]) for p in points]
    values = [float(p["value"]) for p in points]
    return dates, values


def growth_of_10k_chart(fund: dict[str, Any]) -> str | None:
    block = fund.get("series", {}).get("growth_10k")
    if not block:
        return None
    fund_series = block.get("fund")
    yardstick_series = block.get("yardstick")
    if not fund_series or not yardstick_series:
        return None
    fig, ax = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)
    fd, fv = _dates_values(fund_series)
    yd, yv = _dates_values(yardstick_series)
    ax.plot(fd, fv, label=fund["scheme_name"], color="steelblue")  # type: ignore[arg-type]
    ax.plot(
        yd,  # type: ignore[arg-type]
        yv,
        label=benchmark_display_name(fund["benchmark"]["yardstick"]),
        color="grey",
        linestyle="--",
    )
    ax.set_title("Growth of ₹10,000")
    ax.set_ylabel("₹")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    return _svg(fig)


def drawdown_chart(fund: dict[str, Any]) -> str | None:
    series = fund.get("series", {}).get("underwater")
    if not series:
        return None
    fig, ax = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)
    d, v = _dates_values(series)
    pct = [x * 100 for x in v]
    ax.fill_between(d, pct, 0, color="firebrick", alpha=0.4)  # type: ignore[arg-type]
    ax.plot(d, pct, color="firebrick", linewidth=1)  # type: ignore[arg-type]
    ax.set_title("Drawdown")
    ax.set_ylabel("%")
    # Month-end grain (chart-density series) — distinct from the headline
    # max-drawdown figure, which stays the daily-basis metric; the axis is
    # capped at 0 so float noise at the peak never reads as a gain.
    ax.set_ylim(top=0)
    ax.annotate(
        "month-end basis",
        xy=(0.01, 0.02),
        xycoords="axes fraction",
        fontsize=7,
        color="dimgray",
    )
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    return _svg(fig)


def rolling_excess_return_chart(fund: dict[str, Any]) -> str | None:
    series = fund.get("rolling", {}).get("rolling_excess_return_3Y")
    if not series:
        return None
    fig, ax = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)
    d, v = _dates_values(series)
    pct = [x * 100 for x in v]
    ax.axhline(0, color="black", linewidth=0.8)
    ax.plot(d, pct, color="steelblue")  # type: ignore[arg-type]
    ax.set_title("Rolling 3Y Excess Return vs Category Benchmark")
    ax.set_ylabel("%")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    return _svg(fig)


def rolling_sharpe_rank_band_chart(fund: dict[str, Any]) -> str | None:
    history = fund.get("ranks", {}).get("sharpe_3Y", {}).get("history")
    if not history:
        return None
    fig, ax = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)
    d = [date.fromisoformat(p["date"]) for p in history]
    pct = [float(p["pct"]) for p in history]
    ax.axhspan(25, 75, color="steelblue", alpha=0.15, label="Category IQR (25th-75th pct)")
    ax.plot(d, pct, color="steelblue", marker="o", markersize=2)  # type: ignore[arg-type]
    # Display convention is lower-is-better (spec-flexicap-page §2/§3,
    # amendment 1): inverting the axis puts the best rank (1 ≈ top of cohort)
    # visually at the top of the chart, matching "up = better" everywhere else.
    ax.set_ylim(100, 0)
    ax.set_title("Rolling 3Y Sharpe — Percentile Rank")
    ax.set_ylabel("Percentile rank (lower = better)")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    return _svg(fig)


CHART_BUILDERS: dict[str, Callable[[dict[str, Any]], str | None]] = {
    "growth_10k": growth_of_10k_chart,
    "drawdown": drawdown_chart,
    "rolling_excess_return": rolling_excess_return_chart,
    "rolling_sharpe_rank": rolling_sharpe_rank_band_chart,
}


def build_charts(fund: dict[str, Any]) -> dict[str, str | None]:
    """Every chart for one fund page, keyed by :data:`CHART_BUILDERS` name."""
    return {name: fn(fund) for name, fn in CHART_BUILDERS.items()}
