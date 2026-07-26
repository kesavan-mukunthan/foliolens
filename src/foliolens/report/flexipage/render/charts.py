"""Pre-rendered SVG charts (matplotlib, no Plotly — ``spec-flexicap-page §4``).

Every chart reads a series straight off the parsed ``metrics.json`` fund
entry; none is computed here. A chart whose backing series is absent or empty
returns ``None`` and the template omits it entirely — never an empty axes
frame (spec-flexicap-page §7-F2's "skip a chart cleanly" rule applies equally
to a young fund's empty rolling panel and to a panel the current F1 artifact
does not emit at all).
"""
from __future__ import annotations

import io
from collections.abc import Callable
from datetime import date
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402 - backend must be set first

_FIGSIZE = (6.4, 3.2)
_DPI = 100

#: Forward-compatible rolling-panel keys for the two NAV-based charts. The
#: current F1 artifact (report/flexipage/assembly.py) does not emit these —
#: `rolling` is an open map (schemas/flexipage-1.schema.json), so both charts
#: are wired up and will activate with zero F2 changes the day F1 adds them;
#: until then they skip cleanly for every fund.
NAV_GROWTH_FUND_KEY = "growth_10k_fund"
NAV_GROWTH_YARDSTICK_KEY = "growth_10k_yardstick"
DRAWDOWN_KEY = "drawdown"


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
    rolling = fund.get("rolling", {})
    fund_series = rolling.get(NAV_GROWTH_FUND_KEY)
    yardstick_series = rolling.get(NAV_GROWTH_YARDSTICK_KEY)
    if not fund_series or not yardstick_series:
        return None
    fig, ax = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)
    fd, fv = _dates_values(fund_series)
    yd, yv = _dates_values(yardstick_series)
    ax.plot(fd, fv, label=fund["scheme_name"], color="steelblue")  # type: ignore[arg-type]
    ax.plot(yd, yv, label=fund["benchmark"]["yardstick"], color="grey", linestyle="--")  # type: ignore[arg-type]
    ax.set_title("Growth of ₹10,000")
    ax.set_ylabel("₹")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    return _svg(fig)


def drawdown_chart(fund: dict[str, Any]) -> str | None:
    series = fund.get("rolling", {}).get(DRAWDOWN_KEY)
    if not series:
        return None
    fig, ax = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)
    d, v = _dates_values(series)
    pct = [x * 100 for x in v]
    ax.fill_between(d, pct, 0, color="firebrick", alpha=0.4)  # type: ignore[arg-type]
    ax.plot(d, pct, color="firebrick", linewidth=1)  # type: ignore[arg-type]
    ax.set_title("Drawdown")
    ax.set_ylabel("%")
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
    ax.set_title("Rolling 3Y Excess Return vs Yardstick")
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
    ax.set_ylim(0, 100)
    ax.set_title("Rolling 3Y Sharpe — Percentile Rank")
    ax.set_ylabel("Percentile")
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
