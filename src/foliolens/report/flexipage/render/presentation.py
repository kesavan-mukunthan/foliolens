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

#: (metric key prefix, display label, is-a-return-like-percentage, is-excess-
#: return) for each row of the per-fund metrics table (``spec-flexicap-page
#: §2``). Excess return sits immediately after its own return row (amendment
#: 6's column pairing) — never the word "yardstick" (amendment 5).
_METRIC_ROWS: tuple[tuple[str, str, bool, bool], ...] = (
    ("return", "Return", True, False),
    ("excess_return", "Excess Return vs Category Benchmark", True, True),
    ("volatility", "Volatility", True, False),
    ("sharpe", "Sharpe", False, False),
    ("sortino", "Sortino", False, False),
    ("calmar", "Calmar", False, False),
    ("tracking_error", "Tracking Error", True, False),
    ("information_ratio", "Information Ratio", False, False),
    ("beta", "Beta", False, False),
)

#: Row/column label for the derived benchmark-return figure, shown between
#: each window's Return and Excess Return (Return, Benchmark, Excess).
BENCHMARK_RETURN_LABEL = "Benchmark Return"

#: Metric-name prefixes whose figures are dimensionless *ratios* — rendered as
#: a plain 2 dp number, never a percentage. Sharpe/Sortino/Calmar (return per
#: unit of risk), Information Ratio (active return per unit of tracking error),
#: and Beta (regression slope) are all unitless; multiplying them by 100 and
#: appending "%" (as a naive return-style formatter does) is a category error —
#: a Sharpe of 1.20 is not "120%". Everything else rendered in a metric table
#: is a percentage-class figure (returns, volatility, downside deviation, alpha,
#: tracking error, drawdown). This is the single source of truth the per-fund
#: metric rows (:data:`_METRIC_ROWS`) and the index-page aggregate rows
#: (:func:`build_aggregate_rows`) both classify against.
_RATIO_METRIC_PREFIXES: tuple[str, ...] = (
    "sharpe",
    "sortino",
    "calmar",
    "information_ratio",
    "beta",
)


def is_ratio_metric(metric_key: str) -> bool:
    """Whether ``metric_key`` (with or without a ``_1Y``/``_3Y``/``_5Y`` window
    suffix) names a dimensionless ratio — rendered as a plain number, not a
    percentage. See :data:`_RATIO_METRIC_PREFIXES`.
    """
    return any(
        metric_key == prefix or metric_key.startswith(f"{prefix}_")
        for prefix in _RATIO_METRIC_PREFIXES
    )


def _benchmark_return(metrics: dict[str, Any], window: str) -> float | None:
    """The category benchmark's own trailing return for ``window``.

    Not a new computation: ``excess_return_{window}`` is already ``return_
    {window} − benchmark_return`` (``assembly.py``'s ``_excess_return_
    scalar``), so the benchmark figure is recovered by the same subtraction
    in reverse, over two numbers already stored in the artifact. Identical
    for every fund at a given window (one category yardstick, one ``as_of``
    — ``spec-flexicap-page §1``); ``None`` whenever either input is (never a
    fabricated figure).
    """
    ret = metrics.get(f"return_{window}")
    excess = metrics.get(f"excess_return_{window}")
    if ret is None or excess is None:
        return None
    return float(ret) - float(excess)


#: |t-stat| below this greys the alpha figure out (``spec-flexicap-page §2``).
ALPHA_T_STAT_GREY_THRESHOLD = 2.0

#: The single mid-horizon window used for the index page's ranked table's
#: standalone (non-paired) columns (vol/Sharpe/rank) — 3Y is the window with
#: full rank-history coverage in the F1 artifact and sits between the 1Y/5Y
#: extremes.
INDEX_TABLE_WINDOW = "3Y"

#: Metric-windows shown in the index page's category-aggregates block,
#: paired return/excess like the ranked table's own columns (amendment 3/6).
INDEX_AGGREGATE_KEYS: tuple[str, ...] = (
    "return_1Y",
    "excess_return_1Y",
    "return_3Y",
    "excess_return_3Y",
    "return_5Y",
    "excess_return_5Y",
    "volatility_3Y",
    "sharpe_3Y",
)

#: Human-readable names for benchmark index codes — "category benchmark
#: (Nifty 500 TRI)", never the internal identifier's own word "yardstick"
#: in rendered output (spec-flexicap-page §1/§4/§7-F2 amendment 5). Unknown
#: codes fall back to the raw code rather than inventing a name.
_BENCHMARK_DISPLAY_NAMES: dict[str, str] = {
    "NIFTY500TRI": "Nifty 500 TRI",
}


def benchmark_display_name(code: str) -> str:
    """A human-readable name for a benchmark index code, or the code itself."""
    return _BENCHMARK_DISPLAY_NAMES.get(code, code)


def category_benchmark_label(code: str) -> str:
    """'category benchmark (Nifty 500 TRI)' — the only rendered phrasing."""
    return f"category benchmark ({benchmark_display_name(code)})"


@dataclass(frozen=True)
class MetricRow:
    label: str
    is_pct: bool
    is_excess: bool
    values: dict[str, float | None]


@dataclass(frozen=True)
class AlphaCell:
    value: float
    t_stat: float
    greyed: bool


def build_metrics_rows(metrics: dict[str, Any]) -> list[MetricRow]:
    """The per-fund metrics table body: one row per :data:`_METRIC_ROWS` entry,
    with the derived benchmark-return row spliced in right after Return (so
    the order reads Return, Benchmark, Excess Return).
    """
    rows: list[MetricRow] = []
    for key, label, is_pct, is_excess in _METRIC_ROWS:
        rows.append(
            MetricRow(
                label=label,
                is_pct=is_pct,
                is_excess=is_excess,
                values={w: metrics.get(f"{key}_{w}") for w in WINDOWS},
            )
        )
        if key == "return":
            rows.append(
                MetricRow(
                    label=BENCHMARK_RETURN_LABEL,
                    is_pct=True,
                    is_excess=False,
                    values={w: _benchmark_return(metrics, w) for w in WINDOWS},
                )
            )
    return rows


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


def excess_class(value: float | None) -> str:
    """CSS class for an excess-return cell (amendment 4) — colour only ever
    applied to excess-return columns, never return/vol/Sharpe/rank cells.
    Null or exactly zero gets no class (the template's default colour).
    Defined as a class here, not an inline style, so a later print
    stylesheet (F3) can simply not override colour rather than having to
    strip an inline attribute.
    """
    if value is None or value == 0:
        return ""
    return "excess-pos" if value > 0 else "excess-neg"


@dataclass(frozen=True)
class IndexRow:
    amfi_code: str
    scheme_name: str
    fund_house: str
    return_1y: float | None
    benchmark_return_1y: float | None
    excess_return_1y: float | None
    return_3y: float | None
    benchmark_return_3y: float | None
    excess_return_3y: float | None
    return_5y: float | None
    benchmark_return_5y: float | None
    excess_return_5y: float | None
    volatility: float | None
    sharpe: float | None
    rank_pct: float | None


def _index_sort_key(row: IndexRow) -> tuple[bool, float]:
    """Default order (amendment 2): ascending display rank (best first, since
    the artifact's ``pct`` is already lower-is-better — amendment 1), nulls
    sorted last rather than participating in the numeric comparison.
    """
    return (row.rank_pct is None, row.rank_pct if row.rank_pct is not None else 0.0)


def build_index_rows(funds: list[dict[str, Any]]) -> list[IndexRow]:
    """The ranked table's rows (``spec-flexicap-page §4``), pre-sorted to the
    default order (amendment 2) — the sortable-table JS re-sorts from here.
    """
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
                benchmark_return_1y=_benchmark_return(m, "1Y"),
                excess_return_1y=m.get("excess_return_1Y"),
                return_3y=m.get("return_3Y"),
                benchmark_return_3y=_benchmark_return(m, "3Y"),
                excess_return_3y=m.get("excess_return_3Y"),
                return_5y=m.get("return_5Y"),
                benchmark_return_5y=_benchmark_return(m, "5Y"),
                excess_return_5y=m.get("excess_return_5Y"),
                volatility=m.get(f"volatility_{INDEX_TABLE_WINDOW}"),
                sharpe=m.get(f"sharpe_{INDEX_TABLE_WINDOW}"),
                rank_pct=rank_entry.get("pct"),
            )
        )
    return sorted(rows, key=_index_sort_key)


@dataclass(frozen=True)
class AggregateRow:
    key: str
    label: str
    is_pct: bool
    median: float | None
    q1: float | None
    q3: float | None


def build_aggregate_rows(aggregates: dict[str, Any]) -> list[AggregateRow]:
    """Category median/q1/q3 for the curated :data:`INDEX_AGGREGATE_KEYS` subset.

    ``is_pct`` is ``False`` for a dimensionless ratio (Sharpe, and any other
    :func:`is_ratio_metric` key) so the template renders it as a plain 2 dp
    number, not a percentage — the aggregate table previously applied ``|pct``
    uniformly, printing a Sharpe median as e.g. "120.00%" (the D2a defect).
    """
    rows = []
    for key in INDEX_AGGREGATE_KEYS:
        agg = aggregates.get(key, {})
        rows.append(
            AggregateRow(
                key=key,
                label=key.replace("_", " "),
                is_pct=not is_ratio_metric(key),
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
