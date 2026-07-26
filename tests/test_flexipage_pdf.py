"""F3 PDF render tests — same synthetic 3-fund mini-universe as F2's own
``tests/test_flexipage_render.py``, run one stage further through the F3 PDF
generator (``specs/spec-flexicap-page.md §7-F3``).

Covers: a PDF per fund + ``index.pdf``, page count >= 1, the disclaimer
string present in extracted text, and a fill-survival check — the excess-
return cell's background colour must reach the PDF as a filled rectangle,
never invisible white-on-white (spec-flexicap-page §7-F3, §8's
"build failure, not a style nit").

Text/colour extraction via ``pdfplumber`` (dev-only dependency, per
``tests/TESTS.md``'s "no test calls a live source" — local file parsing only,
no network).
"""
from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pdfplumber
import pytest

from foliolens.ingest.index_normalise import IndexRecord
from foliolens.ingest.land import land, land_index
from foliolens.ingest.mftool_client import NavRecord
from foliolens.ingest.scheme_master import SchemeMasterRecord, land_scheme_master
from foliolens.report.flexipage.render import PdfSummary, RenderSummary, render_pdfs, render_site
from foliolens.report.flexipage.render.strings import DISCLAIMER, SURVIVORSHIP_FOOTNOTE
from foliolens.report.flexipage.runner import run

_START = date(2018, 6, 30)
_MATURE_DAYS = 8 * 365  # ~8 years daily -> 96 monthly points; full 5Y panels

#: The excess-return fill colours from the shared layout stylesheet
#: (``templates/layout.html``'s ``.excess-pos``/``.excess-neg``), as the
#: 0-1 RGB triples pdfplumber reports for a filled rectangle's
#: ``non_stroking_color``. A tolerance band, not an exact match — WeasyPrint's
#: PDF backend may round the colour components.
_EXCESS_POS_RGB = (0x1A / 255, 0x7F / 255, 0x37 / 255)
_EXCESS_NEG_RGB = (0xC4 / 255, 0x56 / 255, 0x0C / 255)
_WHITE_RGB = (1.0, 1.0, 1.0)
_RGB_TOLERANCE = 0.02


def _close(a: tuple[float, float, float], b: tuple[float, float, float]) -> bool:
    return all(abs(x - y) < _RGB_TOLERANCE for x, y in zip(a, b))


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
    ]
    land_scheme_master(scheme_records, data_dir)

    index_records: list[IndexRecord] = []
    for code, seed in (("NIFTY500TRI", 10), ("NIFTY50TRI", 11)):
        for d, level in _daily_series(_START, _MATURE_DAYS, seed=seed, vol=0.008):
            index_records.append(IndexRecord(index_code=code, date=d, level=level))
    land_index(index_records, data_dir)

    benchmark_map_path = tmp_path / "benchmark_map.csv"
    _write_benchmark_map(
        benchmark_map_path,
        [
            ("AAAA01", "NIFTY500TRI", "tier1"),
            ("BBBB02", "NIFTY500TRI", "tier1"),
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


@pytest.fixture()
def pdfs(site: RenderSummary) -> PdfSummary:
    return render_pdfs(site.out_dir)


def _all_pdfs(site: RenderSummary) -> list[Path]:
    return [site.out_dir / "index.pdf", *sorted((site.out_dir / "funds").glob("*.pdf"))]


def test_pdf_exists_per_fund_and_index(site: RenderSummary, pdfs: PdfSummary, metrics_path: Path) -> None:
    data = json.loads(metrics_path.read_text())
    assert (site.out_dir / "index.pdf").exists()
    for f in data["funds"]:
        assert (site.out_dir / "funds" / f"{f['amfi_code']}.pdf").exists()
    assert pdfs.pdf_count == 1 + len(data["funds"])


def test_pdf_page_count_at_least_one(site: RenderSummary, pdfs: PdfSummary) -> None:
    for pdf_path in _all_pdfs(site):
        with pdfplumber.open(pdf_path) as pdf:
            assert len(pdf.pages) >= 1


def test_pdf_extracts_non_trivial_text(site: RenderSummary, pdfs: PdfSummary) -> None:
    for pdf_path in _all_pdfs(site):
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        assert len(text.strip()) > 100, f"{pdf_path}: no meaningful extracted text"


def test_disclaimer_present_in_every_pdf(site: RenderSummary, pdfs: PdfSummary) -> None:
    for pdf_path in _all_pdfs(site):
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        # normalise whitespace: WeasyPrint's line-wrapping breaks the verbatim
        # string across lines in extracted text.
        flat = " ".join(text.split())
        assert " ".join(DISCLAIMER.split()) in flat
        assert " ".join(SURVIVORSHIP_FOOTNOTE.split()) in flat


def test_excess_return_fill_survives_to_pdf(site: RenderSummary, pdfs: PdfSummary) -> None:
    """A fund's excess-return cell fill must reach the PDF as a coloured
    rectangle. Never white-on-white — that would silently drop the exact
    colour-coding the F2 renderer produces (spec-flexicap-page §7-F3).
    """
    fund_pdf = site.out_dir / "funds" / "AAAA01.pdf"
    with pdfplumber.open(fund_pdf) as pdf:
        fills = [
            r["non_stroking_color"]
            for page in pdf.pages
            for r in page.rects
            if r.get("non_stroking_color") is not None
        ]
    assert any(_close(f, _EXCESS_POS_RGB) or _close(f, _EXCESS_NEG_RGB) for f in fills), (
        f"no excess-return fill colour found in {fund_pdf}; fills seen: {fills}"
    )
    assert not all(_close(f, _WHITE_RGB) for f in fills)


def test_pdf_total_size_reported(pdfs: PdfSummary) -> None:
    assert pdfs.pdf_count > 0
    assert pdfs.total_size_bytes > 0
