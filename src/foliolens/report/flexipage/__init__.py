"""F1 — the flexicap page's batch runner: universe -> ``metrics.json``.

See ``specs/spec-flexicap-page.md`` §1-§3, §7-F1. Rendering (F2+) is not built
here (``§8`` executor guard).
"""
from __future__ import annotations

from .assembly import (
    CALENDAR_YEARS,
    RANK_SPECS,
    SCHEMA_VERSION,
    FundPanel,
    assemble_universe,
    benchmark_block,
    build_fund_panel,
    calendar_year_returns,
    figures_of_record,
)
from .runner import BuildSummary, FundLoadFailure, load_universe, run

__all__ = [
    "SCHEMA_VERSION",
    "CALENDAR_YEARS",
    "RANK_SPECS",
    "FundPanel",
    "assemble_universe",
    "benchmark_block",
    "build_fund_panel",
    "calendar_year_returns",
    "figures_of_record",
    "BuildSummary",
    "FundLoadFailure",
    "load_universe",
    "run",
]
