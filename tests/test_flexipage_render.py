"""F2 render smoke tests — synthetic 3-fund mini-universe.

Extends F1's fixture (``tests/test_flexipage_runner.py``): the same
data/scheme-master/benchmark-map/index/rf setup, run through the F1 batch
runner to a real ``metrics.json``, then through the F2 renderer. Covers the
F2 acceptance surface (``specs/spec-flexicap-page.md §7-F2``): a page per
fund, index row count == universe count, all internal links resolve, no
"NaN"/"None" in rendered text, footnote + disclaimer on every page, the
tier-fallback label for the flagged fund, and the sort-JS file's presence.

Text is parsed with ``html.parser`` (stdlib only — ``tests/TESTS.md``: no new
test dependencies beyond what's needed).
"""
from __future__ import annotations

import csv
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pytest

from foliolens.ingest.index_normalise import IndexRecord
from foliolens.ingest.land import land, land_index
from foliolens.ingest.mftool_client import NavRecord
from foliolens.ingest.scheme_master import SchemeMasterRecord, land_scheme_master
from foliolens.report.flexipage.render import RenderSummary, render_site
from foliolens.report.flexipage.render.strings import (
    DISCLAIMER,
    SURVIVORSHIP_FOOTNOTE,
    TIER_FALLBACK_LABEL,
)
from foliolens.report.flexipage.runner import run

_START = date(2018, 6, 30)
_MATURE_DAYS = 8 * 365  # ~8 years daily -> 96 monthly points; full 5Y panels
_YOUNG_START = date(2025, 11, 1)
_YOUNG_DAYS = 250  # ~8 months -> nulls for every 1Y/3Y/5Y window


def _daily_series(
    start: date, n_days: int, *, seed: int, drift: float = 0.0003, vol: float = 0.01
) -> list[tuple[date, Decimal]]:
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n_days)
    levels = 100.0 * np.cumprod(1.0 + rets)
    return [
        (start + timedelta(days=i), Decimal(str(round(float(lv), 6))))
        for i, lv in enumerate(levels)
    ]


def _write_benchmark_map(path: Path, rows: list[tuple[str, str, str]]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["amfi_code", "benchmark_code", "tier"])
        for r in rows:
            w.writerow(r)


def _write_rf_csv(path: Path, start: date, end: date, *, monthly_pct: float = 0.5) -> None:
    months: list[date] = []
    d = date(start.year, start.month, 1)
    while d <= end:
        months.append(d)
        d = date(d.year + (d.month // 12), (d.month % 12) + 1, 1)
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Date", "SMB", "HML", "WML", "MF", "RF"])
        for m in months:
            w.writerow([m.strftime("%Y-%m"), "0.1", "0.1", "0.1", "0.5", f"{monthly_pct}"])


@pytest.fixture()
def universe(tmp_path: Path) -> dict[str, Path]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    nav_records: list[NavRecord] = []
    for code, seed in (("AAAA01", 1), ("BBBB02", 2)):
        for d, nav in _daily_series(_START, _MATURE_DAYS, seed=seed):
            nav_records.append(NavRecord(amfi_code=code, date=d, nav=nav))
    for d, nav in _daily_series(_YOUNG_START, _YOUNG_DAYS, seed=3):
        nav_records.append(NavRecord(amfi_code="CCCC03", date=d, nav=nav))
    land(nav_records, data_dir)

    scheme_records = [
        SchemeMasterRecord(
            amfi_code="AAAA01",
            scheme_name="Alpha Flexi Cap Fund - Direct Plan - Growth",
            fund_house="Alpha Mutual Fund",
            scheme_category="Equity Scheme - Flexi Cap Fund",
            sebi_category="flexi_cap",
            plan="direct",
            option="growth",
            inception_date=_START,  # Manifest F-INC: surfaces on the fund header
        ),
        SchemeMasterRecord(
            amfi_code="BBBB02",
            scheme_name="Beta Flexi Cap Fund - Direct - Growth",
            fund_house="Beta Mutual Fund",
            scheme_category="Equity Scheme - Flexi Cap Fund",
            sebi_category="flexi_cap",
            plan="direct",
            option="growth",
        ),
        SchemeMasterRecord(
            amfi_code="CCCC03",
            scheme_name="Gamma Flexi Cap Fund - Direct Plan - Growth",
            fund_house="Gamma Mutual Fund",
            scheme_category="Equity Scheme - Flexi Cap Fund",
            sebi_category="flexi_cap",
            plan="direct",
            option="growth",
        ),
    ]
    land_scheme_master(scheme_records, data_dir)

    # Yardstick (NIFTY500TRI) + alternate (NIFTY50TRI) landed; stated tier-1
    # (BSE500TRI) deliberately NOT landed -> exercises the tier-fallback path.
    index_records: list[IndexRecord] = []
    for code, seed in (("NIFTY500TRI", 10), ("NIFTY50TRI", 11)):
        for d, level in _daily_series(_START, _MATURE_DAYS, seed=seed, vol=0.008):
            index_records.append(IndexRecord(index_code=code, date=d, level=level))
    land_index(index_records, data_dir)

    benchmark_map_path = tmp_path / "benchmark_map.csv"
    _write_benchmark_map(
        benchmark_map_path,
        [
            ("AAAA01", "BSE500TRI", "tier1"),
            ("AAAA01", "NIFTY50TRI", "alternate"),
            ("BBBB02", "NIFTY500TRI", "tier1"),
            # CCCC03 deliberately uncurated -> stated benchmark is null.
        ],
    )

    rf_path = tmp_path / "iima_rf.csv"
    _write_rf_csv(rf_path, _START, _START + timedelta(days=_MATURE_DAYS + 60))

    return {
        "data_dir": data_dir,
        "benchmark_map_path": benchmark_map_path,
        "rf_path": rf_path,
    }


@pytest.fixture()
def metrics_path(tmp_path: Path, universe: dict[str, Path]) -> Path:
    out_path = tmp_path / "out" / "metrics.json"
    run(
        universe["data_dir"],
        out_path,
        rf_path=universe["rf_path"],
        benchmark_map_path=universe["benchmark_map_path"],
    )
    return out_path


@pytest.fixture()
def site(tmp_path: Path, metrics_path: Path) -> RenderSummary:
    return render_site(metrics_path, tmp_path / "site")


class _AnchorCollector(HTMLParser):
    """Collects every ``<a href>`` on a page (attribute values, not text)."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


class _TextCollector(HTMLParser):
    """Collects rendered text nodes only — never ``<style>``/``<script>`` bodies
    or attribute values (so CSS's ``fill: none`` never counts as page text).
    """

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


def _all_pages(site: RenderSummary) -> list[Path]:
    return [site.out_dir / "index.html", *sorted((site.out_dir / "funds").glob("*.html"))]


def test_page_exists_per_fund(site: RenderSummary, metrics_path: Path) -> None:
    data = json.loads(metrics_path.read_text())
    for f in data["funds"]:
        assert (site.out_dir / "funds" / f"{f['amfi_code']}.html").exists()


def test_index_row_count_matches_universe(site: RenderSummary, metrics_path: Path) -> None:
    data = json.loads(metrics_path.read_text())
    html = (site.out_dir / "index.html").read_text(encoding="utf-8")
    ac = _AnchorCollector()
    ac.feed(html)
    fund_links = [h for h in ac.hrefs if h.startswith("funds/")]
    assert len(fund_links) == data["universe"]["count"] == len(data["funds"])


def test_internal_links_resolve(site: RenderSummary) -> None:
    for page in _all_pages(site):
        html = page.read_text(encoding="utf-8")
        ac = _AnchorCollector()
        ac.feed(html)
        for href in ac.hrefs:
            if href.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = (page.parent / href).resolve()
            assert target.exists(), f"{page}: broken link {href}"


def test_footnote_and_disclaimer_on_every_page(site: RenderSummary) -> None:
    for page in _all_pages(site):
        text = page.read_text(encoding="utf-8")
        assert SURVIVORSHIP_FOOTNOTE in text
        assert DISCLAIMER in text


def test_no_nan_or_none_in_rendered_text(site: RenderSummary) -> None:
    for page in _all_pages(site):
        text = _rendered_text(page.read_text(encoding="utf-8"))
        assert "NaN" not in text
        assert "None" not in text


def test_tier_fallback_label_present_for_flagged_fund(
    site: RenderSummary, metrics_path: Path
) -> None:
    data = json.loads(metrics_path.read_text())
    flagged = [
        f["amfi_code"]
        for f in data["funds"]
        if f["benchmark"]["tier"] == "alternate-pending-tier1"
    ]
    assert flagged == ["AAAA01"]
    html = (site.out_dir / "funds" / "AAAA01.html").read_text(encoding="utf-8")
    assert TIER_FALLBACK_LABEL in html


def test_no_tier_fallback_label_for_unflagged_funds(site: RenderSummary) -> None:
    for code in ("BBBB02", "CCCC03"):
        html = (site.out_dir / "funds" / f"{code}.html").read_text(encoding="utf-8")
        assert TIER_FALLBACK_LABEL not in html


def test_inception_line_present_when_known(site: RenderSummary) -> None:
    """Manifest F-INC: the fund header shows 'Inception: {date}' for a fund
    whose scheme master carries an inception (AAAA01, == _START)."""
    html = (site.out_dir / "funds" / "AAAA01.html").read_text(encoding="utf-8")
    assert f"Inception: {_START.isoformat()}" in html


def test_inception_line_absent_when_unknown(site: RenderSummary) -> None:
    """A fund with no recorded inception (CCCC03) renders no inception line —
    silent, per the existing absent-field convention (never 'Inception: None')."""
    html = (site.out_dir / "funds" / "CCCC03.html").read_text(encoding="utf-8")
    assert "Inception:" not in html


def test_sort_js_present(site: RenderSummary) -> None:
    sort_js = site.out_dir / "static" / "sort.js"
    assert sort_js.exists()
    assert sort_js.stat().st_size > 0


def test_metrics_json_copied_to_data_dir(site: RenderSummary, metrics_path: Path) -> None:
    copied = site.out_dir / "data" / "metrics.json"
    assert copied.exists()
    assert json.loads(copied.read_text()) == json.loads(metrics_path.read_text())


def test_page_count_and_size_reported(site: RenderSummary, metrics_path: Path) -> None:
    data = json.loads(metrics_path.read_text())
    assert site.page_count == 1 + len(data["funds"])
    assert site.total_size_bytes > 0


def test_young_fund_3y_anchored_charts_skip_cleanly(site: RenderSummary) -> None:
    """CCCC03 (~8 months old) has no 3Y-anchored series, so the rolling
    excess-return and rolling-Sharpe-rank charts skip — never a padded or
    partial window (``spec-flexicap-page §7-F2``). Growth-of-10k and
    underwater need no fixed window, so they render off the fund's short
    available history: partial-history skip is per-chart, not all-or-nothing.
    """
    html = (site.out_dir / "funds" / "CCCC03.html").read_text(encoding="utf-8")
    assert html.count("<svg") == 2
    assert "No charts available" not in html


def test_full_history_fund_renders_all_four_charts(site: RenderSummary) -> None:
    for code in ("AAAA01", "BBBB02"):
        html = (site.out_dir / "funds" / f"{code}.html").read_text(encoding="utf-8")
        assert html.count("<svg") == 4


def test_growth_of_10k_chart_labels_yardstick_nifty500tri(site: RenderSummary) -> None:
    html = (site.out_dir / "funds" / "AAAA01.html").read_text(encoding="utf-8")
    assert "Nifty 500 TRI" in html


def test_underwater_chart_annotated_month_end_basis(site: RenderSummary) -> None:
    html = (site.out_dir / "funds" / "AAAA01.html").read_text(encoding="utf-8")
    assert "month-end basis" in html


def test_no_fund_has_all_four_charts_skipped(site: RenderSummary) -> None:
    """Every successfully-loaded fund reaches ``build_fund_panel`` with a
    non-empty ``fund.returns`` (``to_returns`` would already have raised
    otherwise), so growth-of-10k and underwater always have at least one
    point: no loaded fund can land in ``funds_with_all_charts_skipped``.
    """
    assert site.funds_with_all_charts_skipped == ()


def test_no_series_data_shows_no_charts_available(tmp_path: Path) -> None:
    """A hand-built artifact with no ``series``/``rolling``/``ranks`` data
    (e.g. an older, pre-``series`` artifact) still hits the template's
    all-skipped fallback cleanly — the branch stays exercised even though no
    successfully-loaded real fund can reach it (see the test above).
    """
    fund = _minimal_fund("NOSERIES01", 0.01, 0.01, 0.01)
    artifact = {
        "schema_version": "flexipage-1",
        "as_of": "2026-07-14",
        "universe": {
            "category": "flexi_cap",
            "count": 1,
            "yardstick": "NIFTY500TRI",
            "aggregates": {},
        },
        "funds": [fund],
    }
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(artifact))
    summary = render_site(metrics_path, tmp_path / "site")

    html = (summary.out_dir / "funds" / "NOSERIES01.html").read_text(encoding="utf-8")
    assert "<svg" not in html
    assert "No charts available" in html
    assert summary.funds_with_all_charts_skipped == ("NOSERIES01",)


# ---------------------------------------------------------------------------
# Amendment 5: "yardstick" is an internal identifier only, never rendered.
# ---------------------------------------------------------------------------


def test_no_yardstick_word_in_rendered_text(site: RenderSummary) -> None:
    for page in _all_pages(site):
        text = _rendered_text(page.read_text(encoding="utf-8"))
        assert "yardstick" not in text.lower()


# ---------------------------------------------------------------------------
# Amendment 2: index table's default order — ascending display rank
# (amendment 1's lower-is-better convention), nulls last.
# ---------------------------------------------------------------------------


def test_index_default_sort_ascending_by_rank_nulls_last(site: RenderSummary) -> None:
    html = (site.out_dir / "index.html").read_text(encoding="utf-8")
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.S)
    rank_values = []
    for r in rows:
        if "funds/" not in r:
            continue
        cells = re.findall(r'<td[^>]*data-value="([^"]*)"', r)
        rank_values.append(cells[-1])

    present = [float(v) for v in rank_values if v != ""]
    assert present, "fixture must carry at least one ranked fund"
    assert present == sorted(present)
    assert present[0] == min(present)
    # nulls (the young fund, no 3Y history) trail every non-null row
    assert all(v == "" for v in rank_values[len(present) :])


# ---------------------------------------------------------------------------
# Amendment 4: excess-return colouring — right cells, nowhere else.
# ---------------------------------------------------------------------------


def _minimal_fund(amfi_code: str, excess_1y: float, excess_3y: float, excess_5y: float) -> dict:
    return {
        "amfi_code": amfi_code,
        "scheme_name": f"{amfi_code} Fund - Direct Plan - Growth",
        "fund_house": "Test Fund House",
        "benchmark": {"stated": None, "tier": None, "yardstick": "NIFTY500TRI"},
        "metrics": {
            "return_1Y": 0.15,
            "return_3Y": 0.12,
            "return_5Y": 0.10,
            "excess_return_1Y": excess_1y,
            "excess_return_3Y": excess_3y,
            "excess_return_5Y": excess_5y,
            "volatility_3Y": 0.18,
            "sharpe_3Y": 1.2,
            "max_drawdown_SI": -0.2,
        },
        "calendar_years": {},
        "alpha": {},
        "rolling": {},
        "ranks": {},
        "commentary": None,
    }


def test_excess_return_coloring_on_right_cells_only(tmp_path: Path) -> None:
    artifact = {
        "schema_version": "flexipage-1",
        "as_of": "2026-07-14",
        "universe": {
            "category": "flexi_cap",
            "count": 2,
            "yardstick": "NIFTY500TRI",
            "aggregates": {},
        },
        "funds": [
            _minimal_fund("POS001", 0.02, 0.01, 0.03),
            _minimal_fund("NEG001", -0.02, -0.01, -0.03),
        ],
    }
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(artifact))
    summary = render_site(metrics_path, tmp_path / "site")

    pos_html = (summary.out_dir / "funds" / "POS001.html").read_text(encoding="utf-8")
    neg_html = (summary.out_dir / "funds" / "NEG001.html").read_text(encoding="utf-8")

    pos_excess_row = re.search(r"<td>Excess Return.*?</tr>", pos_html, re.S)
    assert pos_excess_row is not None
    assert pos_excess_row.group(0).count("excess-pos") == 3
    assert "excess-neg" not in pos_excess_row.group(0)

    neg_excess_row = re.search(r"<td>Excess Return.*?</tr>", neg_html, re.S)
    assert neg_excess_row is not None
    assert neg_excess_row.group(0).count("excess-neg") == 3
    assert "excess-pos" not in neg_excess_row.group(0)

    # No cell outside the excess-return row carries an excess-* class on
    # either fund page — colour only ever applied to excess-return columns.
    # (Count the class *attribute* only — the layout stylesheet's own
    # ``.excess-pos``/``.excess-neg`` rule definitions would otherwise
    # double-count as a false positive.)
    for html in (pos_html, neg_html):
        assert (
            html.count('class="excess-pos"') + html.count('class="excess-neg"') == 3
        )

    index_html = (summary.out_dir / "index.html").read_text(encoding="utf-8")
    pos_row = re.search(
        r'<tr>\s*<td[^>]*><a href="funds/POS001\.html".*?</tr>', index_html, re.S
    )
    assert pos_row is not None
    assert pos_row.group(0).count("excess-pos") == 3
    assert "excess-neg" not in pos_row.group(0)

    neg_row = re.search(
        r'<tr>\s*<td[^>]*><a href="funds/NEG001\.html".*?</tr>', index_html, re.S
    )
    assert neg_row is not None
    assert neg_row.group(0).count("excess-neg") == 3
    assert "excess-pos" not in neg_row.group(0)


# ---------------------------------------------------------------------------
# F4 null-tolerance (spec-flexicap-page §7-F4): a missing/failed commentary
# call leaves ``commentary: null`` in the artifact, and F2 hides the block
# entirely rather than rendering "None" or an empty section.
# ---------------------------------------------------------------------------


def test_commentary_block_hidden_when_null(tmp_path: Path) -> None:
    fund = _minimal_fund("NOCOMM01", 0.01, 0.01, 0.01)
    assert fund["commentary"] is None
    artifact = {
        "schema_version": "flexipage-1",
        "as_of": "2026-07-14",
        "universe": {
            "category": "flexi_cap",
            "count": 1,
            "yardstick": "NIFTY500TRI",
            "aggregates": {},
        },
        "funds": [fund],
    }
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(artifact))
    summary = render_site(metrics_path, tmp_path / "site")

    html = (summary.out_dir / "funds" / "NOCOMM01.html").read_text(encoding="utf-8")
    assert "<h2>Commentary</h2>" not in html
    assert "None" not in _rendered_text(html)


def test_deterministic_commentary_block_shown_when_commentary_null(tmp_path: Path) -> None:
    """FL-NL-1: when ``commentary`` is null the deterministic floor renders
    under its own labelled, visually-distinct heading — never the LLM
    "Commentary" heading, so the two are never confused.
    """
    fund = _minimal_fund("DETCOMM01", 0.01, 0.01, 0.01)
    assert fund["commentary"] is None
    artifact = {
        "schema_version": "flexipage-1",
        "as_of": "2026-07-14",
        "universe": {
            "category": "flexi_cap",
            "count": 1,
            "yardstick": "NIFTY500TRI",
            "aggregates": {},
        },
        "funds": [fund],
    }
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(artifact))
    summary = render_site(metrics_path, tmp_path / "site")

    html = (summary.out_dir / "funds" / "DETCOMM01.html").read_text(encoding="utf-8")
    assert "<h2>Generated summary (deterministic)</h2>" in html
    assert 'class="commentary commentary-deterministic"' in html
    assert "<h2>Commentary</h2>" not in html
    assert "None" not in _rendered_text(html)


def test_deterministic_block_absent_when_llm_commentary_present(tmp_path: Path) -> None:
    """When an LLM commentary block exists, the deterministic floor is absent —
    only one commentary block ever renders."""
    fund = _minimal_fund("BOTHCOMM01", 0.01, 0.01, 0.01)
    fund["commentary"] = {
        "text": "The fund tracked its category benchmark closely over the period.",
        "model": "claude-sonnet-4-6",
        "prompt_version": "commentary-v4",
        "generated_at": "2026-07-14T00:00:00+00:00",
    }
    artifact = {
        "schema_version": "flexipage-1",
        "as_of": "2026-07-14",
        "universe": {
            "category": "flexi_cap",
            "count": 1,
            "yardstick": "NIFTY500TRI",
            "aggregates": {},
        },
        "funds": [fund],
    }
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(artifact))
    summary = render_site(metrics_path, tmp_path / "site")

    html = (summary.out_dir / "funds" / "BOTHCOMM01.html").read_text(encoding="utf-8")
    assert "<h2>Commentary</h2>" in html
    assert "Generated summary (deterministic)" not in html
    # The class is defined in the stylesheet on every page; assert the block
    # element itself (which uses it) is absent, not the bare class name.
    assert 'class="commentary commentary-deterministic"' not in html


def test_commentary_block_shown_when_present(tmp_path: Path) -> None:
    fund = _minimal_fund("HASCOMM01", 0.01, 0.01, 0.01)
    fund["commentary"] = {
        "text": "The fund tracked its category benchmark closely over the period.",
        "model": "claude-sonnet-4-6",
        "prompt_version": "commentary-v4",
        "generated_at": "2026-07-14T00:00:00+00:00",
    }
    artifact = {
        "schema_version": "flexipage-1",
        "as_of": "2026-07-14",
        "universe": {
            "category": "flexi_cap",
            "count": 1,
            "yardstick": "NIFTY500TRI",
            "aggregates": {},
        },
        "funds": [fund],
    }
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(artifact))
    summary = render_site(metrics_path, tmp_path / "site")

    html = (summary.out_dir / "funds" / "HASCOMM01.html").read_text(encoding="utf-8")
    assert "<h2>Commentary</h2>" in html
    assert fund["commentary"]["text"] in html
