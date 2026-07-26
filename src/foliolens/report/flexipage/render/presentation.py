"""Pure shaping of one parsed ``metrics.json`` into template-ready structures.

No computation: every value here is read verbatim off the artifact
(``spec-flexicap-page §8``: "rendered figures come from metrics.json only").
This module only decides *which* keys go in *which* table row/column — the
kind of presentation-layer composition ``CLAUDE.md`` reserves for rendering,
never the analytics layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Trailing windows shown across every per-fund metrics table.
WINDOWS: tuple[str, ...] = ("1Y", "3Y", "5Y")

#: (metric key prefix, display label, is-a-return-like-percentage) for each
#: row of the per-fund metrics table (``spec-flexicap-page §2``).
_METRIC_ROWS: tuple[tuple[str, str, bool], ...] = (
    ("return", "Return", True),
    ("volatility", "Volatility", True),
    ("sharpe", "Sharpe", False),
    ("sortino", "Sortino", False),
    ("calmar", "Calmar", False),
    ("excess_return", "Excess Return vs Yardstick", True),
    ("tracking_error", "Tracking Error", True),
    ("information_ratio", "Information Ratio", False),
    ("beta", "Beta", False),
)

#: |t-stat| below this greys the alpha figure out (``spec-flexicap-page §2``).
ALPHA_T_STAT_GREY_THRESHOLD = 2.0

#: The single mid-horizon window used for the index page's ranked table
#: columns (vol/Sharpe/excess/rank) — 3Y is the window with full rank-history
#: coverage in the F1 artifact and sits between the 1Y/5Y extremes.
INDEX_TABLE_WINDOW = "3Y"

#: Metric-windows shown in the index page's category-aggregates block —
#: mirrors the ranked table's own columns for a consistent read.
INDEX_AGGREGATE_KEYS: tuple[str, ...] = (
    "return_1Y",
    "return_3Y",
    "return_5Y",
    "volatility_3Y",
    "sharpe_3Y",
    "excess_return_3Y",
)


@dataclass(frozen=True)
class MetricRow:
    label: str
    is_pct: bool
    values: dict[str, float | None]


@dataclass(frozen=True)
class AlphaCell:
    value: float
    t_stat: float
    greyed: bool


def build_metrics_rows(metrics: dict[str, Any]) -> list[MetricRow]:
    """The per-fund metrics table body, one row per :data:`_METRIC_ROWS` entry."""
    return [
        MetricRow(
            label=label,
            is_pct=is_pct,
            values={w: metrics.get(f"{key}_{w}") for w in WINDOWS},
        )
        for key, label, is_pct in _METRIC_ROWS
    ]


def build_alpha_row(alpha: dict[str, Any]) -> dict[str, AlphaCell | None]:
    """Jensen's alpha per window, greyed when ``|t_stat| < 2`` (never a naked point estimate)."""
    row: dict[str, AlphaCell | None] = {}
    for w in WINDOWS:
        entry = alpha.get(f"alpha_{w}")
        if entry is None:
            row[w] = None
            continue
        t_stat = float(entry["t_stat"])
        row[w] = AlphaCell(
            value=float(entry["value"]),
            t_stat=t_stat,
            greyed=abs(t_stat) < ALPHA_T_STAT_GREY_THRESHOLD,
        )
    return row


@dataclass(frozen=True)
class IndexRow:
    amfi_code: str
    scheme_name: str
    fund_house: str
    return_1y: float | None
    return_3y: float | None
    return_5y: float | None
    volatility: float | None
    sharpe: float | None
    excess_return: float | None
    rank_pct: float | None


def build_index_rows(funds: list[dict[str, Any]]) -> list[IndexRow]:
    """One ranked-table row per fund (``spec-flexicap-page §4``)."""
    rows = []
    for f in funds:
        m = f["metrics"]
        rank_entry = f["ranks"].get(f"return_{INDEX_TABLE_WINDOW}", {})
        rows.append(
            IndexRow(
                amfi_code=f["amfi_code"],
                scheme_name=f["scheme_name"],
                fund_house=f["fund_house"],
                return_1y=m.get("return_1Y"),
                return_3y=m.get("return_3Y"),
                return_5y=m.get("return_5Y"),
                volatility=m.get(f"volatility_{INDEX_TABLE_WINDOW}"),
                sharpe=m.get(f"sharpe_{INDEX_TABLE_WINDOW}"),
                excess_return=m.get(f"excess_return_{INDEX_TABLE_WINDOW}"),
                rank_pct=rank_entry.get("pct"),
            )
        )
    return rows


@dataclass(frozen=True)
class AggregateRow:
    key: str
    label: str
    median: float | None
    q1: float | None
    q3: float | None


def build_aggregate_rows(aggregates: dict[str, Any]) -> list[AggregateRow]:
    """Category median/q1/q3 for the curated :data:`INDEX_AGGREGATE_KEYS` subset."""
    rows = []
    for key in INDEX_AGGREGATE_KEYS:
        agg = aggregates.get(key, {})
        rows.append(
            AggregateRow(
                key=key,
                label=key.replace("_", " "),
                median=agg.get("median"),
                q1=agg.get("q1"),
                q3=agg.get("q3"),
            )
        )
    return rows


def nav_entries(funds: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The ``{amfi_code, scheme_name}`` pairs powering every page's fund dropdown."""
    return [
        {"amfi_code": f["amfi_code"], "scheme_name": f["scheme_name"]} for f in funds
    ]
