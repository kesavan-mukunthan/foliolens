"""Verbatim spec strings — copied exactly, never paraphrased or reflowed.

``spec-flexicap-page.md §1`` (survivorship footnote) and ``§4`` (disclaimer)
require these exact strings on every page. Single source of truth so the
renderer and its tests read the same text.
"""
from __future__ import annotations

SURVIVORSHIP_FOOTNOTE = (
    "Universe: open-ended flexi-cap schemes (direct growth) live as of July "
    "2026. Funds merged or wound up before this date are not included; "
    "category statistics therefore reflect surviving funds only."
)

DISCLAIMER = (
    "FolioLens is an analytics project. Nothing here is investment advice or "
    "a recommendation. FolioLens is not a SEBI-registered investment "
    "adviser. Data from public sources; verify independently before acting."
)

#: Tier-fallback visible label (``spec-flexicap-page §1``), shown wherever a
#: fund's ``benchmark.tier == "alternate-pending-tier1"``.
TIER_FALLBACK_LABEL = "vs alternate benchmark — tier-1 pending"
