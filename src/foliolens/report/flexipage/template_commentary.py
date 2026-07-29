"""Deterministic commentary floor — a template summary when no LLM block exists.

The fallback sibling of :mod:`.commentary` (FL-NL-1): where that module makes
one Anthropic call per fund at build time, this one composes a short factual
summary from the fund's own artifact figures alone — no model, no network, no
figure computed here that ``assembly.py`` did not already store. It is rendered
onto a fund page **only** when ``fund.commentary`` is null (an absent API key, a
call that failed, or a response that never cleared the descriptive-only
contract); when an LLM block exists this floor is absent, and the page labels
the floor "Generated summary (deterministic)" so the two are never confused.

Three pure stages, mirroring the module's public surface:

1. :func:`select_branches` — pick one branch per section
   (:data:`SECTIONS`) from the fund's raw figures. Total by construction: every
   fund selects a branch for every section, so the fill step never faces a hole.
2. :func:`variant_index` — a stable ``crc32(amfi_code + section) % n`` picks
   which of a branch's interchangeable variants a given fund gets, so the same
   fund always reads the same way across rebuilds (never Python's salted
   ``hash``, which varies per process).
3. :func:`fill` — ``str.format`` the chosen variant with figures pre-formatted
   through :mod:`.render.presentation` (the one percentage/ratio formatter this
   page uses). A placeholder with no field is a loud ``KeyError`` at build.

The registry (:data:`VARIANTS`) is the single source of the prose. Every
variant within a branch shares one placeholder set (tested), states no
comparative unless both compared figures are present (the branch condition
guarantees it), and carries none of :data:`~.commentary.BANNED_VOCABULARY` —
the same list the LLM path gates on, imported here rather than restated.

A residual (Jensen's alpha) is only ever stated alongside its t-statistic
(``CLAUDE.md``: a point estimate without uncertainty is an invalid artifact):
the ``bench_up``/``bench_down`` branches — which quote the alpha value — are
selected only for a window whose t-stat is itself reportable (``n_months`` ≥
:data:`~.render.presentation.T_STAT_MIN_MONTHS`); a shorter history routes to
``young_fund``, which quotes no alpha at all.
"""
from __future__ import annotations

import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from string import Formatter
from typing import Any

from .commentary import BANNED_VOCABULARY
from .render.presentation import (
    ALPHA_T_STAT_GREY_THRESHOLD,
    T_STAT_MIN_MONTHS,
    format_pct,
    format_ratio,
)

__all__ = [
    "BANNED_VOCABULARY",
    "SECTIONS",
    "VARIANTS",
    "build_fields",
    "fill",
    "mechanical_component",
    "render_block",
    "select_branches",
    "variant_index",
]

#: The four sections, in the order they are concatenated into the rendered
#: block. ``significance`` follows ``decomposition`` because it comments on that
#: window's residual; ``suppressed`` is an empty string, so a young fund's block
#: simply skips from decomposition to risk with no dangling clause.
SECTIONS: tuple[str, ...] = ("decomposition", "significance", "risk", "context")

#: The verbatim variant registry (Manifest E-2). ``dict[section][branch] ->
#: (variant_A, variant_B)``, two interchangeable variants per branch except the
#: two deliberately-empty branches (``significance/suppressed``,
#: ``context/short_history`` carries prose but no figures). Placeholders are
#: filled from :func:`build_fields`; every variant within a branch uses the
#: identical placeholder set (enforced by test).
VARIANTS: dict[str, dict[str, tuple[str, ...]]] = {
    "decomposition": {
        "bench_down": (
            "Over the trailing {window}, the category benchmark fell {bench_ret}. "
            "At a beta of {beta}, tracking alone accounts for roughly {mech} of "
            "{fund_short}'s {fund_ret} return; the residual is {alpha}.",
            "{fund_short} returned {fund_ret} over the trailing {window} against a "
            "{bench_ret} fall in the category benchmark. Beta of {beta} implies a "
            "mechanical contribution near {mech}, leaving a residual of {alpha}.",
        ),
        "bench_up": (
            "Over the trailing {window}, the category benchmark rose {bench_ret}. "
            "At a beta of {beta}, tracking alone accounts for roughly {mech} of "
            "{fund_short}'s {fund_ret} return; the residual is {alpha}.",
            "{fund_short} returned {fund_ret} over the trailing {window} against a "
            "{bench_ret} rise in the category benchmark. Beta of {beta} implies a "
            "mechanical contribution near {mech}, leaving a residual of {alpha}.",
        ),
        "young_fund": (
            "{fund_short} has under three years of history; longer-window "
            "comparisons are not yet meaningful. Over the trailing 1Y it returned "
            "{fund_ret} against {bench_ret} for the category benchmark.",
            "With a track record still under three years, {fund_short}'s figures "
            "are limited to shorter windows: {fund_ret} over the trailing 1Y "
            "versus the category benchmark's {bench_ret}.",
        ),
    },
    "significance": {
        # Empty by design: the branch exists so the selector is total (a young
        # fund quotes no alpha, so there is no residual to characterise).
        "suppressed": ("",),
        "insignificant": (
            "That residual carries a t-statistic of {tstat}: statistically "
            "indistinguishable from zero at conventional thresholds.",
            "With a t-statistic of {tstat}, the residual cannot be distinguished "
            "from zero at conventional significance levels.",
        ),
        "significant": (
            "The residual's t-statistic is {tstat}, distinguishable from zero at "
            "conventional thresholds.",
            "That residual is statistically distinguishable from zero (t = {tstat}).",
        ),
    },
    "risk": {
        "vol_above_median": (
            "Annualised volatility of {vol} sits above the category median of "
            "{cat_vol}; the maximum drawdown on record is {mdd}.",
            "At {vol}, volatility runs higher than the category median ({cat_vol}); "
            "maximum drawdown to date is {mdd}.",
        ),
        "vol_below_median": (
            "Annualised volatility of {vol} sits below the category median of "
            "{cat_vol}; the maximum drawdown on record is {mdd}.",
            "At {vol}, volatility runs lower than the category median ({cat_vol}); "
            "maximum drawdown to date is {mdd}.",
        ),
        "risk_absolute": (
            "Annualised volatility over the window is {vol}, with a maximum "
            "drawdown of {mdd}.",
            "Volatility stands at {vol}; the deepest drawdown on record is {mdd}.",
        ),
    },
    "context": {
        "calendar_years": (
            "Calendar-year returns: {cy1_label} {cy1}, {cy2_label} {cy2}, "
            "{cy3_label} {cy3}.",
            "By calendar year, the fund returned {cy1} in {cy1_label}, {cy2} in "
            "{cy2_label} and {cy3} in {cy3_label}.",
        ),
        "short_history": (
            "Calendar-year history is not yet long enough to tabulate.",
            "Fewer than two full calendar years are on record.",
        ),
    },
}


@dataclass(frozen=True)
class _Selection:
    """One fund's resolved branches, plus the windows the fields step reuses."""

    decomposition: str
    significance: str
    risk: str
    context: str
    dec_window: str | None  # None -> young_fund (no alpha window)
    risk_window: str


def mechanical_component(beta: float, benchmark_return: float) -> float:
    """The mechanical (tracking) contribution ``beta × benchmark_return``.

    The one figure this module computes — a deterministic product of two stored
    figures, not a new metric convention — surfaced as ``{mech}`` in the
    decomposition branches. Unit-tested against the arithmetic directly.
    """
    return beta * benchmark_return


def _n_months(windows: Mapping[str, Any], window: str) -> int:
    """The window's ``n_months`` from the artifact's per-window block, or ``0``
    when the block is absent — read, never inferred from the window label
    (mirrors ``presentation._window_n_months``'s discipline; a missing block is
    a conservative zero, so the alpha-reporting gate fails closed).
    """
    entry = windows.get(window)
    if not isinstance(entry, dict):
        return 0
    n = entry.get("n_months")
    return int(n) if isinstance(n, int) else 0


def _fund_short_name(scheme_name: str) -> str:
    """A short fund name for prose: the scheme name up to its first ` - `
    (dropping the ` - Direct Plan - Growth` / ` - Direct - Growth` tail).
    """
    return scheme_name.split(" - ", 1)[0].strip()


def _has(metrics: Mapping[str, Any], key: str) -> bool:
    return metrics.get(key) is not None


def _decomposition_window(fund: Mapping[str, Any]) -> str | None:
    """The window the alpha decomposition uses, or ``None`` for a young fund.

    ``3Y`` when its beta, benchmark return and Jensen's alpha are all present
    **and** the window carries at least :data:`T_STAT_MIN_MONTHS` monthly
    points — the same bar the fund page uses to decide a t-stat is reportable.
    A shorter or thinner history returns ``None``: the decomposition then routes
    to ``young_fund``, which quotes no alpha, so no residual is ever stated
    without the t-stat that qualifies it (``CLAUDE.md``).
    """
    metrics = fund["metrics"]
    alpha = fund.get("alpha", {})
    windows = fund.get("windows", {})
    if (
        alpha.get("alpha_3Y") is not None
        and _has(metrics, "beta_3Y")
        and _has(metrics, "benchmark_return_3Y")
        and _n_months(windows, "3Y") >= T_STAT_MIN_MONTHS
    ):
        return "3Y"
    return None


def _resolve(fund: Mapping[str, Any], aggregates: Mapping[str, Any]) -> _Selection:
    """Select every section's branch from the fund's raw figures (total)."""
    metrics = fund["metrics"]

    dec_window = _decomposition_window(fund)
    if dec_window is None:
        decomposition = "young_fund"
        significance = "suppressed"
    else:
        bench_ret = metrics[f"benchmark_return_{dec_window}"]
        decomposition = "bench_up" if bench_ret >= 0 else "bench_down"
        t_stat = fund["alpha"][f"alpha_{dec_window}"].get("t_stat")
        if t_stat is None or _n_months(fund.get("windows", {}), dec_window) < T_STAT_MIN_MONTHS:
            significance = "suppressed"
        elif abs(t_stat) < ALPHA_T_STAT_GREY_THRESHOLD:
            significance = "insignificant"
        else:
            significance = "significant"

    risk_window = "3Y" if _has(metrics, "volatility_3Y") else "1Y"
    vol = metrics.get(f"volatility_{risk_window}")
    cat_entry = aggregates.get(f"volatility_{risk_window}")
    cat_vol = cat_entry.get("median") if isinstance(cat_entry, dict) else None
    if vol is not None and cat_vol is not None:
        risk = "vol_above_median" if vol > cat_vol else "vol_below_median"
    else:
        risk = "risk_absolute"

    calendar_years = fund["calendar_years"]
    present = [y for y in calendar_years if calendar_years.get(y) is not None]
    context = "calendar_years" if len(present) >= 2 else "short_history"

    return _Selection(
        decomposition=decomposition,
        significance=significance,
        risk=risk,
        context=context,
        dec_window=dec_window,
        risk_window=risk_window,
    )


def select_branches(fund: Mapping[str, Any], aggregates: Mapping[str, Any]) -> dict[str, str]:
    """One branch key per section (:data:`SECTIONS`), from the fund's figures.

    Total by construction — every fund selects a branch for every section, so
    :func:`render_block` never hits a missing branch. ``aggregates`` is the
    universe-level ``aggregates`` block (``universe.aggregates`` in the
    artifact); the category volatility median it carries decides the ``risk``
    branch, falling back to ``risk_absolute`` when that median is absent.
    """
    sel = _resolve(fund, aggregates)
    return {section: getattr(sel, section) for section in SECTIONS}


def _calendar_year_fields(fund: Mapping[str, Any]) -> dict[str, str]:
    """The latest three calendar years as ``cy{1,2,3}_label``/``cy{1,2,3}``.

    Chronological (oldest of the three first), reading the artifact's own
    ``calendar_years`` keys — a present-but-null year renders as an em dash
    (never fabricated, never "None"), which is why the branch admits a fund
    with only two of three years populated.
    """
    calendar_years = fund["calendar_years"]
    years = sorted(calendar_years.keys())[-3:]
    fields: dict[str, str] = {}
    for i, year in enumerate(years, start=1):
        fields[f"cy{i}_label"] = year
        fields[f"cy{i}"] = format_pct(calendar_years.get(year))
    return fields


def build_fields(
    fund: Mapping[str, Any], aggregates: Mapping[str, Any], selection: _Selection
) -> dict[str, dict[str, str]]:
    """Per-section, per-branch placeholder values — every figure pre-formatted
    through :mod:`.render.presentation` (never a raw float, never ``None``: a
    null figure is an em dash, so the filled prose can carry it honestly).
    """
    metrics = fund["metrics"]
    fund_short = _fund_short_name(fund["scheme_name"])
    fields: dict[str, dict[str, str]] = {}

    # decomposition
    window = selection.dec_window
    if window is None:
        fields["decomposition"] = {
            "fund_short": fund_short,
            "fund_ret": format_pct(metrics.get("return_1Y")),
            "bench_ret": format_pct(metrics.get("benchmark_return_1Y")),
        }
    else:
        beta = metrics[f"beta_{window}"]
        bench_ret = metrics[f"benchmark_return_{window}"]
        alpha_value = fund["alpha"][f"alpha_{window}"]["value"]
        fields["decomposition"] = {
            "window": window,
            # "fell/rose {bench_ret}" already carries the direction, so the
            # figure itself is the magnitude — the sign lives in the verb, not a
            # leading minus.
            "bench_ret": format_pct(abs(bench_ret)),
            "beta": format_ratio(beta),
            "mech": format_pct(mechanical_component(beta, bench_ret)),
            "fund_short": fund_short,
            "fund_ret": format_pct(metrics.get(f"return_{window}")),
            "alpha": format_pct(alpha_value),
        }

    # significance
    if selection.significance == "suppressed":
        fields["significance"] = {}
    else:
        t_stat = fund["alpha"][f"alpha_{window}"]["t_stat"]
        fields["significance"] = {"tstat": format_ratio(t_stat)}

    # risk
    risk_window = selection.risk_window
    mdd = format_pct(metrics.get("max_drawdown_SI"))
    vol = format_pct(metrics.get(f"volatility_{risk_window}"))
    if selection.risk == "risk_absolute":
        fields["risk"] = {"vol": vol, "mdd": mdd}
    else:
        cat_entry = aggregates.get(f"volatility_{risk_window}") or {}
        fields["risk"] = {
            "vol": vol,
            "cat_vol": format_pct(cat_entry.get("median")),
            "mdd": mdd,
        }

    # context
    if selection.context == "short_history":
        fields["context"] = {}
    else:
        fields["context"] = _calendar_year_fields(fund)

    return fields


def variant_index(amfi_code: str, section: str, n_variants: int) -> int:
    """Which variant of a branch a fund reads — ``crc32(amfi_code + section) %
    n_variants``. A stable CRC (never Python's per-process-salted ``hash``) so a
    fund reads identically across rebuilds; keyed on the section, not the
    branch, so the choice is fixed before the branch is even known.
    """
    return zlib.crc32(f"{amfi_code}{section}".encode()) % n_variants


def fill(template: str, fields: Mapping[str, str]) -> str:
    """``str.format`` the variant with ``fields``. A placeholder with no field
    raises ``KeyError`` — loud at build, never a silently half-filled sentence.
    """
    return template.format(**fields)


def render_block(fund: Mapping[str, Any], aggregates: Mapping[str, Any]) -> str:
    """The deterministic commentary paragraph for one fund.

    Selects a branch per section, picks each section's variant by
    :func:`variant_index`, fills it, and joins the non-empty pieces with single
    spaces (an empty ``suppressed``/``short_history`` piece drops out cleanly).
    ``aggregates`` is the artifact's ``universe.aggregates`` block.
    """
    selection = _resolve(fund, aggregates)
    fields = build_fields(fund, aggregates, selection)
    amfi_code = fund["amfi_code"]

    parts: list[str] = []
    for section in SECTIONS:
        branch = getattr(selection, section)
        variants = VARIANTS[section][branch]
        template = variants[variant_index(amfi_code, section, len(variants))]
        text = fill(template, fields[section])
        if text:
            parts.append(text)
    return " ".join(parts)


def placeholders(template: str) -> set[str]:
    """The named ``{...}`` fields a variant references — used by the
    placeholder-set-identical-within-branch test, kept here so the parse rule is
    defined once.
    """
    return {name for _, name, _, _ in Formatter().parse(template) if name}
