"""F2 — static HTML render over ``metrics.json``.

See ``specs/spec-flexicap-page.md`` §4, §7-F2, §8. Reads the F1 artifact only;
computes nothing, never touches parquet or the network (F3/F4 — PDF and
commentary — are not built here).
"""
from __future__ import annotations

from .build import RenderSummary, render_site

__all__ = ["RenderSummary", "render_site"]
