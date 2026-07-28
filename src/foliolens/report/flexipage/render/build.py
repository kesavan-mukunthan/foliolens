"""F2 renderer orchestration — parsed ``metrics.json`` -> static HTML site.

Entry point: ``uv run python -m foliolens.report.flexipage.render --metrics PATH --out DIR``

Reads the artifact and writes pages; every figure comes from
:mod:`.presentation` (shaping) and :mod:`.charts` (pre-rendered SVG), both of
which only read fields already present in ``metrics.json`` — no parquet, no
network, no recomputation (``spec-flexicap-page §8``).
"""
from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import charts, presentation
from .pdf import render_pdfs
from .strings import (
    DISCLAIMER,
    PERCENTILE_FOOTNOTE,
    SURVIVORSHIP_FOOTNOTE,
    T_STAT_SUPPRESSION_FOOTNOTE,
    TIER_FALLBACK_LABEL,
)

_HERE = Path(__file__).parent
_TEMPLATES_DIR = _HERE / "templates"
_STATIC_DIR = _HERE / "static"


def _pct(value: float | None, digits: int = 2) -> str:
    """A decimal fraction as a percentage string, or an em dash when null."""
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _pct100(value: float | None, digits: int = 1) -> str:
    """A value already on a 0-100 scale (e.g. a percentile rank) as a string."""
    return "—" if value is None else f"{value:.{digits}f}%"


def _num(value: float | None, digits: int = 2) -> str:
    """A plain (non-percentage) figure, or an em dash when null."""
    return "—" if value is None else f"{value:.{digits}f}"


def _dataval(value: float | str | None) -> str | float:
    """The raw sort key for a table cell's ``data-value`` attribute."""
    return "" if value is None else value


def _make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["pct"] = _pct
    env.filters["pct100"] = _pct100
    env.filters["num"] = _num
    env.filters["dataval"] = _dataval
    env.filters["excess_class"] = presentation.excess_class
    return env


@dataclass(frozen=True)
class RenderSummary:
    """Everything a caller needs after a render: page count, size, chart gaps."""

    out_dir: Path
    page_count: int
    total_size_bytes: int
    funds_with_all_charts_skipped: tuple[str, ...]


def render_site(metrics_path: Path, out_dir: Path) -> RenderSummary:
    """Render ``index.html`` + one ``funds/<amfi_code>.html`` per fund into ``out_dir``."""
    data: dict[str, Any] = json.loads(metrics_path.read_text(encoding="utf-8"))
    funds: list[dict[str, Any]] = data["funds"]

    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir = out_dir / "data"
    data_dir.mkdir(exist_ok=True)
    shutil.copy(metrics_path, data_dir / "metrics.json")

    static_out = out_dir / "static"
    static_out.mkdir(exist_ok=True)
    shutil.copy(_STATIC_DIR / "sort.js", static_out / "sort.js")

    env = _make_env()
    common_ctx = {
        "as_of": data["as_of"],
        "nav_funds": presentation.nav_entries(funds),
        "footnote": SURVIVORSHIP_FOOTNOTE,
        "disclaimer": DISCLAIMER,
    }

    index_html = env.get_template("index.html").render(
        **common_ctx,
        root_prefix="",
        current_amfi_code=None,
        universe=data["universe"],
        category_benchmark_label=presentation.category_benchmark_label(
            data["universe"]["yardstick"]
        ),
        aggregate_rows=presentation.build_aggregate_rows(data["universe"]["aggregates"]),
        index_rows=presentation.build_index_rows(funds),
        percentile_footnote=PERCENTILE_FOOTNOTE,
    )
    (out_dir / "index.html").write_text(index_html, encoding="utf-8")

    funds_dir = out_dir / "funds"
    funds_dir.mkdir(exist_ok=True)
    fund_tmpl = env.get_template("fund.html")
    calendar_years = sorted(funds[0]["calendar_years"].keys()) if funds else []

    all_skipped: list[str] = []
    for fund in funds:
        fund_charts = charts.build_charts(fund)
        if not any(fund_charts.values()):
            all_skipped.append(fund["amfi_code"])
        alpha_row = presentation.build_alpha_row(fund["alpha"], fund.get("windows", {}))
        html = fund_tmpl.render(
            **common_ctx,
            root_prefix="../",
            current_amfi_code=fund["amfi_code"],
            fund=fund,
            category_benchmark_display=presentation.benchmark_display_name(
                fund["benchmark"]["yardstick"]
            ),
            windows=presentation.WINDOWS,
            calendar_years=calendar_years,
            metrics_rows=presentation.build_metrics_rows(fund["metrics"]),
            alpha_row=alpha_row,
            alpha_suppressed=any(c.suppressed for c in alpha_row.values() if c is not None),
            t_stat_suppression_footnote=T_STAT_SUPPRESSION_FOOTNOTE,
            charts=fund_charts,
            tier_fallback_label=TIER_FALLBACK_LABEL,
        )
        (funds_dir / f"{fund['amfi_code']}.html").write_text(html, encoding="utf-8")

    total_size_bytes = sum(p.stat().st_size for p in out_dir.rglob("*") if p.is_file())
    return RenderSummary(
        out_dir=out_dir,
        page_count=1 + len(funds),
        total_size_bytes=total_size_bytes,
        funds_with_all_charts_skipped=tuple(all_skipped),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="F2 renderer: metrics.json -> static HTML site"
    )
    parser.add_argument("--metrics", required=True, type=Path, metavar="PATH")
    parser.add_argument("--out", required=True, type=Path, metavar="DIR")
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="also render a print-CSS PDF per fund page + index.pdf (F3)",
    )
    args = parser.parse_args(argv)

    summary = render_site(args.metrics, args.out)
    print(f"wrote {summary.page_count} pages to {summary.out_dir}")
    print(f"total size: {summary.total_size_bytes} bytes")
    if summary.funds_with_all_charts_skipped:
        print(
            f"{len(summary.funds_with_all_charts_skipped)} funds with all charts "
            f"skipped: {', '.join(summary.funds_with_all_charts_skipped)}"
        )

    if args.pdf:
        pdf_summary = render_pdfs(args.out)
        print(f"wrote {pdf_summary.pdf_count} PDFs to {args.out}")
        print(f"PDF total size: {pdf_summary.total_size_bytes} bytes")


if __name__ == "__main__":
    main()
