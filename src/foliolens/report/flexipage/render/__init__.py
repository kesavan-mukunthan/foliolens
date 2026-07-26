"""F2/F3 — static HTML render over ``metrics.json``, plus print-CSS PDF.

See ``specs/spec-flexicap-page.md`` §4, §7-F2/§7-F3, §8. Reads the F1 artifact
only; computes nothing, never touches parquet or the network (F4 — commentary
— is not built here).
"""
from __future__ import annotations

from .build import RenderSummary, render_site
from .pdf import PdfSummary, render_pdfs

__all__ = ["RenderSummary", "render_site", "PdfSummary", "render_pdfs"]
