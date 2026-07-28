"""D2 presentation tests — ratio formatting, footnotes, t-stat suppression, rf.

Rendered-block unit tests over the F2 renderer's presentation layer
(``report/flexipage/render``), driven by hand-built minimal artifacts rather
than the full F1 data pipeline (fast, and the presentation behaviour is what's
under test). Covers:

* D2a — ratio-class metrics (Sharpe, Information Ratio) render as plain
  numbers, never percentages.
* D2b — the percentile-convention footnote, referenced once from the index
  page's Rank column header.
* D2c — a thin-sample (``n_months < 24``) window suppresses its alpha t-stat
  (em dash, value never in the HTML) with the suppression footnote; a
  ``n_months >= 24`` window renders the t-stat.
* D2d — the risk-free disclosure footer (series name + a level per window).

Text is unescaped via ``html.parser`` (stdlib) so a footnote containing ``<``
is matched as the reader sees it, not as the raw ``&lt;`` entity.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from foliolens.report.flexipage.render import render_site
from foliolens.report.flexipage.render.strings import (
    PERCENTILE_FOOTNOTE,
    T_STAT_SUPPRESSION_FOOTNOTE,
)


class _TextCollector(HTMLParser):
    """Rendered (entity-unescaped) text, minus ``<style>``/``<script>`` bodies."""

    def __init__(self) -> None:
        super().__init__()
        self._skip = False
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("style", "script"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "script"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.chunks.append(data)


def _rendered_text(html: str) -> str:
    tc = _TextCollector()
    tc.feed(html)
    return "".join(tc.chunks)


def _fund(
    amfi_code: str,
    *,
    alpha: dict[str, Any] | None = None,
    windows: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A render-complete fund entry with a full metric set (ratios + pct)."""
    metrics = {
        "return_1Y": 0.15, "return_3Y": 0.12, "return_5Y": 0.10,
        "excess_return_1Y": 0.02, "excess_return_3Y": 0.01, "excess_return_5Y": 0.0,
        "volatility_1Y": 0.18, "volatility_3Y": 0.17, "volatility_5Y": 0.16,
        "sharpe_1Y": 1.10, "sharpe_3Y": 1.20, "sharpe_5Y": 1.05,
        "sortino_1Y": 1.40, "sortino_3Y": 1.50, "sortino_5Y": 1.30,
        "calmar_1Y": 0.90, "calmar_3Y": 0.80, "calmar_5Y": 0.70,
        "tracking_error_1Y": 0.03, "tracking_error_3Y": 0.03, "tracking_error_5Y": 0.03,
        "information_ratio_1Y": 0.60, "information_ratio_3Y": 0.80, "information_ratio_5Y": 0.50,
        "beta_1Y": 0.95, "beta_3Y": 0.95, "beta_5Y": 0.95,
        "max_drawdown_SI": -0.20,
        "benchmark_return_1Y": 0.13, "benchmark_return_3Y": 0.11, "benchmark_return_5Y": 0.10,
        "rf_1Y": 0.061, "rf_3Y": 0.0625, "rf_5Y": 0.060,
    }
    return {
        "amfi_code": amfi_code,
        "scheme_name": f"{amfi_code} Fund - Direct Plan - Growth",
        "fund_house": "Test Fund House",
        "benchmark": {"stated": None, "tier": None, "yardstick": "NIFTY500TRI"},
        "metrics": metrics,
        "calendar_years": {"2023": 0.20, "2024": 0.10, "2025": 0.05},
        "alpha": alpha if alpha is not None else {},
        "rolling": {},
        "series": {"growth_10k": None, "underwater": []},
        "ranks": {},
        "windows": windows if windows is not None else {},
        "commentary": None,
    }


def _rf_block() -> dict[str, Any]:
    return {
        "series_name": "rf-iima-91d-tbill",
        "frequency": "monthly",
        "last_date": "2026-06-30",
        "levels": {"1Y": 0.061, "3Y": 0.0625, "5Y": 0.060},
    }


def _artifact(funds: list[dict[str, Any]], *, aggregates: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "flexipage-3",
        "as_of": "2026-06-30",
        "universe": {
            "category": "flexi_cap",
            "count": len(funds),
            "yardstick": "NIFTY500TRI",
            "aggregates": aggregates if aggregates is not None else {},
            "rf": _rf_block(),
        },
        "funds": funds,
    }


def _render(tmp_path: Path, artifact: dict[str, Any]) -> Path:
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(artifact))
    summary = render_site(metrics_path, tmp_path / "site")
    return summary.out_dir


def _cell_texts(row_html: str) -> list[str]:
    """Rendered text of every ``<td>`` in a table-row fragment."""
    return [_rendered_text(td) for td in re.findall(r"<td[^>]*>.*?</td>", row_html, re.S)]


# ---------------------------------------------------------------------------
# D2a — ratio-class metrics render as plain numbers, never percentages.
# ---------------------------------------------------------------------------


def test_sharpe_aggregate_cell_has_no_percent(tmp_path: Path) -> None:
    """The index Category Aggregates Sharpe row (the original defect) renders
    a plain 2 dp number — no ``%`` — while a percentage-class aggregate keeps
    its ``%``.
    """
    artifact = _artifact(
        [_fund("AAAA01")],
        aggregates={
            "sharpe_3Y": {"median": 1.20, "q1": 1.00, "q3": 1.40},
            "return_3Y": {"median": 0.10, "q1": 0.05, "q3": 0.15},
        },
    )
    out = _render(tmp_path, artifact)
    index_html = (out / "index.html").read_text(encoding="utf-8")

    sharpe_row = re.search(r"<tr>\s*<td>sharpe 3Y</td>.*?</tr>", index_html, re.S)
    assert sharpe_row is not None
    assert "%" not in sharpe_row.group(0)
    assert "1.20" in sharpe_row.group(0)  # plain ratio, not 120.00%

    return_row = re.search(r"<tr>\s*<td>return 3Y</td>.*?</tr>", index_html, re.S)
    assert return_row is not None
    assert "%" in return_row.group(0)  # percentage-class keeps its %


def test_sharpe_and_ir_metric_cells_have_no_percent(tmp_path: Path) -> None:
    """In the per-fund metrics table, the Sharpe and Information Ratio rows are
    dimensionless — their cells carry no ``%`` — while Volatility (a
    percentage-class row) does.
    """
    out = _render(tmp_path, _artifact([_fund("AAAA01")]))
    fund_html = (out / "funds" / "AAAA01.html").read_text(encoding="utf-8")

    for label in ("Sharpe", "Information Ratio"):
        row = re.search(rf"<td>{re.escape(label)}</td>.*?</tr>", fund_html, re.S)
        assert row is not None, f"missing {label} row"
        value_cells = _cell_texts(row.group(0))[1:]  # drop the label cell
        assert value_cells, f"{label} row has no value cells"
        assert all("%" not in c for c in value_cells), f"{label} cell shows a %"

    vol_row = re.search(r"<td>Volatility</td>.*?</tr>", fund_html, re.S)
    assert vol_row is not None
    assert "%" in vol_row.group(0)


# ---------------------------------------------------------------------------
# D2b — percentile convention footnote, referenced from the Rank header.
# ---------------------------------------------------------------------------


def test_percentile_footnote_present_and_referenced(tmp_path: Path) -> None:
    out = _render(tmp_path, _artifact([_fund("AAAA01")]))
    index_html = (out / "index.html").read_text(encoding="utf-8")
    text = _rendered_text(index_html)

    assert PERCENTILE_FOOTNOTE in text
    # exactly one note per page (not restated per metric)
    assert text.count(PERCENTILE_FOOTNOTE) == 1
    # referenced from the Rank column header
    assert re.search(r"Rank \(3Y %ile\)<sup[^>]*>", index_html) is not None


def test_percentile_footnote_absent_from_fund_pages(tmp_path: Path) -> None:
    """The percentile note belongs to the ranked (index) page only — fund pages
    render no percentile column, so they carry no such footnote.
    """
    out = _render(tmp_path, _artifact([_fund("AAAA01")]))
    fund_text = _rendered_text((out / "funds" / "AAAA01.html").read_text(encoding="utf-8"))
    assert PERCENTILE_FOOTNOTE not in fund_text


# ---------------------------------------------------------------------------
# D2c — thin-sample t-stat suppression.
# ---------------------------------------------------------------------------


_ALPHA = {
    "alpha_1Y": {"value": 0.02, "t_stat": 1.10, "n": 14,
                 "window_start": "2025-05-31", "window_end": "2026-06-30"},
    "alpha_3Y": {"value": 0.03, "t_stat": 2.50, "n": 36,
                 "window_start": "2023-07-31", "window_end": "2026-06-30"},
    "alpha_5Y": {"value": 0.01, "t_stat": 0.50, "n": 60,
                 "window_start": "2021-07-31", "window_end": "2026-06-30"},
}


def _windows(n_1y: int, n_3y: int, n_5y: int) -> dict[str, Any]:
    def block(n: int) -> dict[str, Any]:
        return {"n_months": n, "n_overlap_rf": n, "n_overlap_benchmark": n, "refused": {}}
    return {"1Y": block(n_1y), "3Y": block(n_3y), "5Y": block(n_5y)}


def _alpha_row_html(fund_html: str) -> str:
    m = re.search(r"<td>Alpha \(t-stat\)</td>.*?</tr>", fund_html, re.S)
    assert m is not None
    return m.group(0)


def test_thin_window_suppresses_tstat_with_footnote(tmp_path: Path) -> None:
    """A window with ``n_months = 14`` (< 24) renders its alpha cell as an em
    dash — neither the alpha value nor the t-stat appears anywhere in the HTML
    — and the suppression footnote is on the page.
    """
    fund = _fund("AAAA01", alpha=_ALPHA, windows=_windows(14, 36, 60))
    out = _render(tmp_path, _artifact([fund]))
    fund_html = (out / "funds" / "AAAA01.html").read_text(encoding="utf-8")

    cells = _cell_texts(_alpha_row_html(fund_html))[1:]  # 1Y, 3Y, 5Y
    # the suppressed 1Y cell is an em dash only — no alpha value, no t-stat
    assert cells[0].strip().startswith("—")
    assert "t=" not in cells[0]
    assert "%" not in cells[0]
    # the 1Y t-stat's rendered form never reaches the HTML (nor any attribute):
    # its alpha cell is the only place that value would be formatted "(t=1.10)".
    assert "(t=1.10)" not in fund_html

    assert T_STAT_SUPPRESSION_FOOTNOTE in _rendered_text(fund_html)


def test_thick_window_renders_tstat(tmp_path: Path) -> None:
    """A window with ``n_months = 36`` (>= 24) renders its alpha and t-stat."""
    fund = _fund("AAAA01", alpha=_ALPHA, windows=_windows(14, 36, 60))
    out = _render(tmp_path, _artifact([fund]))
    fund_html = (out / "funds" / "AAAA01.html").read_text(encoding="utf-8")

    cells = _cell_texts(_alpha_row_html(fund_html))[1:]
    assert "t=2.50" in cells[1]  # 3Y t-stat shown
    assert "3.00%" in cells[1]   # 3Y alpha value shown


def test_no_alpha_suppression_footnote_when_all_windows_thick(tmp_path: Path) -> None:
    """When every window clears the 24-month bar, no cell is suppressed and the
    suppression footnote does not appear.
    """
    fund = _fund("AAAA01", alpha=_ALPHA, windows=_windows(24, 36, 60))
    out = _render(tmp_path, _artifact([fund]))
    fund_html = (out / "funds" / "AAAA01.html").read_text(encoding="utf-8")

    assert T_STAT_SUPPRESSION_FOOTNOTE not in _rendered_text(fund_html)
    cells = _cell_texts(_alpha_row_html(fund_html))[1:]
    assert "t=1.10" in cells[0]  # 1Y now shown (n_months=24)


# ---------------------------------------------------------------------------
# D2d — risk-free disclosure footer.
# ---------------------------------------------------------------------------


def test_rf_footer_has_series_name_and_level_per_window(tmp_path: Path) -> None:
    """Every rendered page's footer states the rf series name and an annualised
    rf level for each rendered window (1Y/3Y/5Y).
    """
    out = _render(tmp_path, _artifact([_fund("AAAA01")]))
    for page in (out / "index.html", out / "funds" / "AAAA01.html"):
        text = _rendered_text(page.read_text(encoding="utf-8"))
        assert "rf-iima-91d-tbill" in text
        assert "monthly" in text
        assert "2026-06-30" in text
        # a level per window: 0.061 -> 6.10%, 0.0625 -> 6.25%, 0.060 -> 6.00%
        for level in ("6.10%", "6.25%", "6.00%"):
            assert level in text, f"{page.name}: missing rf level {level}"


def test_rf_footer_absent_for_pre_v3_artifact(tmp_path: Path) -> None:
    """A pre-flexipage-3 artifact (no ``universe.rf``) renders no rf footer
    block rather than crashing or printing ``None``.
    """
    fund = _fund("AAAA01")
    artifact = {
        "schema_version": "flexipage-2",
        "as_of": "2026-06-30",
        "universe": {
            "category": "flexi_cap",
            "count": 1,
            "yardstick": "NIFTY500TRI",
            "aggregates": {},
        },
        "funds": [fund],
    }
    out = _render(tmp_path, artifact)
    for page in (out / "index.html", out / "funds" / "AAAA01.html"):
        html = page.read_text(encoding="utf-8")
        assert "Risk-free basis" not in html
        assert "None" not in _rendered_text(html)
