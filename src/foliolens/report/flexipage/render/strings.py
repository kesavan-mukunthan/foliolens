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

#: Percentile-convention footnote (D2b). Describes what the artifact's rendered
#: ``pct`` actually is: ``analytics/peer.py`` computes a within-cohort rank with
#: the direction applied per metric (its ``higher_is_better`` flag), which
#: ``assembly._to_display_pct`` then flips to the rendered convention — lower is
#: better, 1 ≈ top of cohort. So a low percentile is always the better one,
#: whether the underlying metric is higher-is-better (return, Sharpe) or
#: lower-is-better (volatility, tracking error). One note per page, referenced
#: from the percentile column header — never restated per metric.
PERCENTILE_FOOTNOTE = (
    "Percentile ranks are within category, from 1st (best) to 100th (worst). "
    "The ranking direction is applied per metric before ranking, so a lower "
    "percentile is always better regardless of the metric — a 13th-percentile "
    "volatility, for example, is lower (better) than 87% of peers."
)

#: t-stat suppression footnote (D2c). A t-statistic estimated over a window
#: with fewer than 24 monthly observations is too thin to report; the cell
#: renders an em dash and its value never appears in the HTML. Verbatim wording
#: — the executable test asserts this exact string. The 24-month threshold
#: itself lives in :data:`foliolens.report.flexipage.render.presentation.T_STAT_MIN_MONTHS`.
T_STAT_SUPPRESSION_FOOTNOTE = "suppressed: insufficient sample (n < 24 months)"
