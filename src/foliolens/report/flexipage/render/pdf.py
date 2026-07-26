"""F3 — print-CSS PDF generation over the already-rendered HTML site.

See ``specs/spec-flexicap-page.md`` §4, §7-F3. No separate PDF layout:
WeasyPrint prints the very same page + the shared print stylesheet already in
``templates/layout.html`` (``@page``, hidden nav/sort-JS, ``page-break-inside:
avoid`` on tables/charts, a running per-page footer carrying the disclaimer).
Reads rendered HTML files off disk only — no ``metrics.json``, no parquet, no
network (``spec-flexicap-page §8``).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from weasyprint import HTML


@dataclass(frozen=True)
class PdfSummary:
    """Everything a caller needs after a PDF pass: count and total size."""

    pdf_count: int
    total_size_bytes: int


def render_pdfs(out_dir: Path) -> PdfSummary:
    """``funds/<amfi_code>.pdf`` per fund page + ``index.pdf``, written
    alongside the HTML the F2 renderer already produced in ``out_dir``.
    """
    pages = [out_dir / "index.html", *sorted((out_dir / "funds").glob("*.html"))]
    written: list[Path] = []
    for page in pages:
        pdf_path = page.with_suffix(".pdf")
        HTML(filename=str(page)).write_pdf(str(pdf_path))
        written.append(pdf_path)
    return PdfSummary(
        pdf_count=len(written),
        total_size_bytes=sum(p.stat().st_size for p in written),
    )
