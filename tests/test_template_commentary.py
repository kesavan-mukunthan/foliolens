"""Deterministic commentary floor tests (Manifest E-2, FL-NL-1).

Offline, pure-function coverage of ``report/flexipage/template_commentary.py``:
the total branch selector, the stable variant hash, ``str.format`` fill, the
one arithmetic (``beta × benchmark_return``), and the epistemic invariants the
variants must uphold — placeholder-set identity within a branch, no comparative
without both figures, no praise/alarm or banned vocabulary, and every rendered
number traceable to a formatted field.

The registry (``VARIANTS``) is the source of truth for the prose; these tests
scan it exhaustively rather than spot-checking, so a new variant cannot be added
without meeting every invariant.
"""
from __future__ import annotations

import re
from typing import Any

import pytest

from foliolens.report.flexipage.commentary import BANNED_VOCABULARY
from foliolens.report.flexipage.render.presentation import format_pct
from foliolens.report.flexipage.template_commentary import (
    SECTIONS,
    VARIANTS,
    build_fields,
    fill,
    mechanical_component,
    placeholders,
    render_block,
    select_branches,
    variant_index,
)

# ---------------------------------------------------------------------------
# Fixtures: canonical artifact rows, one per decomposition/significance state
# ---------------------------------------------------------------------------


def _mature(
    amfi_code: str = "MATURE1",
    *,
    t_stat: float = 3.1,
    benchmark_return_3Y: float = 0.10,
    volatility_3Y: float = 0.18,
) -> dict[str, Any]:
    """A full-history fund: 3Y beta + alpha present, ≥24 monthly points, so the
    decomposition lands on a ``bench_up``/``bench_down`` window.
    """
    return {
        "amfi_code": amfi_code,
        "scheme_name": "Alpha Flexi Cap Fund - Direct Plan - Growth",
        "fund_house": "Alpha Mutual Fund",
        "metrics": {
            "return_1Y": 0.15,
            "return_3Y": 0.12,
            "beta_3Y": 0.95,
            "benchmark_return_1Y": 0.11,
            "benchmark_return_3Y": benchmark_return_3Y,
            "volatility_1Y": 0.20,
            "volatility_3Y": volatility_3Y,
            "max_drawdown_SI": -0.22,
        },
        "alpha": {"alpha_3Y": {"value": 0.025, "t_stat": t_stat, "n": 36}},
        "windows": {"1Y": {"n_months": 12}, "3Y": {"n_months": 36}},
        "calendar_years": {"2023": 0.18, "2024": 0.09, "2025": 0.05},
    }


def _young(amfi_code: str = "YOUNG01") -> dict[str, Any]:
    """An ~8-month fund: no 3Y alpha, so decomposition is ``young_fund`` and
    significance is ``suppressed`` (no residual to characterise).
    """
    return {
        "amfi_code": amfi_code,
        "scheme_name": "Gamma Flexi Cap Fund - Direct Plan - Growth",
        "fund_house": "Gamma Mutual Fund",
        "metrics": {
            "return_1Y": None,
            "benchmark_return_1Y": -0.03,
            "volatility_1Y": 0.14,
            "max_drawdown_SI": -0.10,
        },
        "alpha": {},
        "windows": {},
        "calendar_years": {"2023": None, "2024": None, "2025": 0.05},
    }


def _aggregates() -> dict[str, Any]:
    return {
        "volatility_1Y": {"median": 0.15, "q1": 0.12, "q3": 0.18},
        "volatility_3Y": {"median": 0.16, "q1": 0.13, "q3": 0.19},
    }


# ---------------------------------------------------------------------------
# Registry shape: exactly the branches the manifest names, per section
# ---------------------------------------------------------------------------


def test_sections_are_the_four_named() -> None:
    assert SECTIONS == ("decomposition", "significance", "risk", "context")
    assert set(VARIANTS) == set(SECTIONS)


def test_branch_keys_per_section() -> None:
    assert set(VARIANTS["decomposition"]) == {"bench_up", "bench_down", "young_fund"}
    assert set(VARIANTS["significance"]) == {"suppressed", "insignificant", "significant"}
    assert set(VARIANTS["risk"]) == {"vol_above_median", "vol_below_median", "risk_absolute"}
    assert set(VARIANTS["context"]) == {"calendar_years", "short_history"}


def test_two_variants_per_branch_except_suppressed() -> None:
    for section, branches in VARIANTS.items():
        for branch, variants in branches.items():
            if (section, branch) == ("significance", "suppressed"):
                assert variants == ("",)
            else:
                assert len(variants) == 2, f"{section}/{branch} must have two variants"


# ---------------------------------------------------------------------------
# Placeholder-set identity within a branch (every variant, same set)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "section,branch",
    [(s, b) for s, branches in VARIANTS.items() for b in branches],
)
def test_placeholder_set_identical_within_branch(section: str, branch: str) -> None:
    variants = VARIANTS[section][branch]
    sets = [placeholders(v) for v in variants]
    assert all(s == sets[0] for s in sets), f"{section}/{branch}: variants differ in placeholders"


# ---------------------------------------------------------------------------
# Epistemic invariants scanned over the whole registry
# ---------------------------------------------------------------------------

_ALL_VARIANTS = [
    (section, branch, variant)
    for section, branches in VARIANTS.items()
    for branch, variants in branches.items()
    for variant in variants
]

#: Words that editorialise rather than describe — the deterministic floor
#: states figures, never verdicts. Distinct from BANNED_VOCABULARY (the LLM
#: path's buy/sell/attractive class), which is also asserted absent below.
_PRAISE_ALARM = (
    "strong",
    "weak",
    "impressive",
    "worrying",
    "worryingly",
    "excellent",
    "poor",
    "robust",
    "stellar",
    "alarming",
    "dangerous",
    "outstanding",
    "disappointing",
)


@pytest.mark.parametrize("section,branch,variant", _ALL_VARIANTS)
def test_no_banned_vocabulary_in_any_variant(section: str, branch: str, variant: str) -> None:
    lowered = variant.lower()
    for term in BANNED_VOCABULARY:
        assert not re.search(rf"\b{re.escape(term)}\b", lowered), (
            f"{section}/{branch} contains banned term {term!r}"
        )


@pytest.mark.parametrize("section,branch,variant", _ALL_VARIANTS)
def test_no_praise_or_alarm_vocabulary(section: str, branch: str, variant: str) -> None:
    lowered = variant.lower()
    for term in _PRAISE_ALARM:
        assert not re.search(rf"\b{re.escape(term)}\b", lowered), (
            f"{section}/{branch} contains praise/alarm term {term!r}"
        )


def test_comparative_branches_carry_both_compared_figures() -> None:
    """No comparative without both figures present (Manifest E-2 epistemic
    invariant): the bench branches compare the fund's return to the benchmark's
    (and quote beta/mech/alpha); the vol-vs-median branches carry both vol and
    the category median — all as placeholders, so the branch condition that
    selects them guarantees the figures exist.
    """
    for branch in ("bench_up", "bench_down"):
        ph = placeholders(VARIANTS["decomposition"][branch][0])
        assert {"fund_ret", "bench_ret", "beta", "mech", "alpha"} <= ph
    for branch in ("vol_above_median", "vol_below_median"):
        ph = placeholders(VARIANTS["risk"][branch][0])
        assert {"vol", "cat_vol"} <= ph
    # risk_absolute makes no comparison, so it must NOT reference the median.
    assert "cat_vol" not in placeholders(VARIANTS["risk"]["risk_absolute"][0])


# ---------------------------------------------------------------------------
# Selector: totality + branch conditions
# ---------------------------------------------------------------------------


def test_selector_is_total_over_fixture_funds() -> None:
    """Every fixture fund selects a valid branch for every section, and
    render_block produces a string with no unfilled placeholder or "None".
    """
    funds_and_aggs = [
        (_mature("MATURE1", t_stat=3.1), _aggregates()),
        (_mature("MATURE2", t_stat=1.0), _aggregates()),  # insignificant
        (_mature("MATURE3", benchmark_return_3Y=-0.04), _aggregates()),  # bench_down
        (_mature("MATURE4", volatility_3Y=0.10), _aggregates()),  # vol_below_median
        (_mature("MATURE5"), {}),  # empty aggregates -> risk_absolute
        (_young("YOUNG01"), _aggregates()),
    ]
    for fund, aggs in funds_and_aggs:
        branches = select_branches(fund, aggs)
        assert set(branches) == set(SECTIONS)
        for section in SECTIONS:
            assert branches[section] in VARIANTS[section]
        block = render_block(fund, aggs)
        assert block
        assert "None" not in block
        assert "{" not in block and "}" not in block


def test_significant_when_t_stat_above_threshold() -> None:
    branches = select_branches(_mature(t_stat=3.1), _aggregates())
    assert branches["decomposition"] == "bench_up"
    assert branches["significance"] == "significant"


def test_insignificant_when_abs_t_stat_below_two() -> None:
    branches = select_branches(_mature(t_stat=1.3), _aggregates())
    assert branches["significance"] == "insignificant"
    # Symmetric in sign: a t of -1.3 is equally insignificant.
    assert select_branches(_mature(t_stat=-1.3), _aggregates())["significance"] == "insignificant"


def test_young_fund_selects_young_fund_and_suppressed() -> None:
    branches = select_branches(_young(), _aggregates())
    assert branches["decomposition"] == "young_fund"
    assert branches["significance"] == "suppressed"


def test_short_window_below_24_months_suppresses_alpha() -> None:
    """A fund whose only alpha window carries fewer than 24 monthly points must
    route to young_fund / suppressed — a residual is never quoted without a
    reportable t-stat (CLAUDE.md).
    """
    fund = _mature()
    fund["windows"]["3Y"]["n_months"] = 23
    branches = select_branches(fund, _aggregates())
    assert branches["decomposition"] == "young_fund"
    assert branches["significance"] == "suppressed"
    # And the rendered block quotes no alpha value.
    assert "residual" not in render_block(fund, _aggregates())


def test_risk_absolute_when_category_median_absent() -> None:
    assert select_branches(_mature(), {})["risk"] == "risk_absolute"


def test_vol_above_and_below_median() -> None:
    assert select_branches(_mature(volatility_3Y=0.30), _aggregates())["risk"] == "vol_above_median"
    assert select_branches(_mature(volatility_3Y=0.05), _aggregates())["risk"] == "vol_below_median"


def test_context_short_history_when_fewer_than_two_calendar_years() -> None:
    fund = _mature()
    fund["calendar_years"] = {"2023": None, "2024": None, "2025": 0.05}
    assert select_branches(fund, _aggregates())["context"] == "short_history"
    fund["calendar_years"] = {"2023": None, "2024": 0.09, "2025": 0.05}
    assert select_branches(fund, _aggregates())["context"] == "calendar_years"


# ---------------------------------------------------------------------------
# Arithmetic: mechanical component = beta × benchmark_return
# ---------------------------------------------------------------------------


def test_mechanical_component_arithmetic() -> None:
    assert mechanical_component(0.95, 0.10) == pytest.approx(0.095)
    assert mechanical_component(1.1, -0.04) == pytest.approx(-0.044)


def test_rendered_mech_equals_formatted_beta_times_benchmark_return() -> None:
    fund = _mature(benchmark_return_3Y=0.10)  # beta 0.95 -> mech 0.095 -> 9.50%
    fields = build_fields(fund, _aggregates(), _selection(fund, _aggregates()))
    assert fields["decomposition"]["mech"] == format_pct(mechanical_component(0.95, 0.10))
    assert fields["decomposition"]["mech"] == "9.50%"


def _selection(fund: dict[str, Any], aggs: dict[str, Any]) -> Any:
    # Reach the private resolver via the public build_fields' expectation by
    # rebuilding it from select_branches would lose the windows; use the module
    # helper directly for the fields test.
    from foliolens.report.flexipage.template_commentary import _resolve

    return _resolve(fund, aggs)


# ---------------------------------------------------------------------------
# Every rendered number traces to a formatted field
# ---------------------------------------------------------------------------

_NUMERAL_RE = re.compile(r"-?\d*\.\d+|-?\d{2,}")


@pytest.mark.parametrize(
    "fund,aggs",
    [
        (_mature("MATURE1", t_stat=3.1), _aggregates()),
        (_mature("MATURE2", t_stat=1.0, benchmark_return_3Y=-0.04), _aggregates()),
        (_mature("MATURE3", volatility_3Y=0.05), {}),
        (_young("YOUNG01"), _aggregates()),
    ],
)
def test_every_rendered_number_is_a_formatted_field(fund: dict[str, Any], aggs: dict[str, Any]) -> None:
    selection = _selection(fund, aggs)
    fields = build_fields(fund, aggs, selection)
    all_field_values = {v for section in fields.values() for v in section.values()}

    block = render_block(fund, aggs)
    for token in _NUMERAL_RE.findall(block):
        assert any(token in value for value in all_field_values), (
            f"rendered number {token!r} not traceable to a formatted field"
        )


def test_field_values_never_none_or_raw_float() -> None:
    """A null figure renders as an em dash, never "None" and never a bare
    float — so a filled sentence is always a clean string.
    """
    fund = _young()
    selection = _selection(fund, _aggregates())
    fields = build_fields(fund, _aggregates(), selection)
    for section in fields.values():
        for value in section.values():
            assert isinstance(value, str)
            assert value != "None"


# ---------------------------------------------------------------------------
# Variant hash: stable, section-keyed, asserted literally
# ---------------------------------------------------------------------------


def test_variant_index_is_stable_and_literal() -> None:
    """A fixed fund code + section maps to a fixed variant — asserted against
    the exact crc32-derived values (a regression guard on the hash function).
    """
    assert variant_index("MATURE1", "decomposition", 2) == 1
    assert variant_index("MATURE1", "significance", 2) == 1
    assert variant_index("MATURE1", "risk", 2) == 0
    assert variant_index("MATURE1", "context", 2) == 0
    assert variant_index("YOUNG01", "decomposition", 2) == 0
    assert variant_index("YOUNG01", "context", 2) == 1


def test_variant_index_uses_crc32_not_python_hash() -> None:
    import zlib

    for code in ("MATURE1", "YOUNG01", "AAAA01"):
        for section in SECTIONS:
            expected = zlib.crc32(f"{code}{section}".encode()) % 2
            assert variant_index(code, section, 2) == expected


def test_variant_index_suppressed_single_variant_is_index_zero() -> None:
    # A one-variant branch (suppressed) always resolves to index 0.
    assert variant_index("ANYCODE", "significance", 1) == 0


def test_render_block_is_deterministic() -> None:
    fund, aggs = _mature(), _aggregates()
    assert render_block(fund, aggs) == render_block(fund, aggs)


# ---------------------------------------------------------------------------
# fill: KeyError on a missing placeholder field (loud at build)
# ---------------------------------------------------------------------------


def test_fill_raises_key_error_on_missing_field() -> None:
    with pytest.raises(KeyError):
        fill("value is {missing}", {})


def test_fill_leaves_no_placeholder_when_field_present() -> None:
    assert fill("beta {beta}", {"beta": "0.95"}) == "beta 0.95"


def test_suppressed_and_short_history_fill_to_empty_or_prose() -> None:
    assert fill(VARIANTS["significance"]["suppressed"][0], {}) == ""
    # short_history carries prose but no fields.
    assert fill(VARIANTS["context"]["short_history"][0], {})


# ---------------------------------------------------------------------------
# fund_short: the scheme name up to its plan/option tail
# ---------------------------------------------------------------------------


def test_fund_short_name_strips_plan_option_tail() -> None:
    fund = _mature()
    fields = build_fields(fund, _aggregates(), _selection(fund, _aggregates()))
    assert fields["decomposition"]["fund_short"] == "Alpha Flexi Cap Fund"


# ---------------------------------------------------------------------------
# bench direction wording carries the sign; the figure is the magnitude
# ---------------------------------------------------------------------------


def test_bench_down_uses_fall_wording_and_magnitude() -> None:
    fund = _mature(benchmark_return_3Y=-0.04)
    block = render_block(fund, _aggregates())
    assert "fell 4.00%" in block or "4.00% fall" in block
    assert "-4.00%" not in block  # the minus lives in the verb, not the figure


def test_bench_up_uses_rise_wording() -> None:
    fund = _mature(benchmark_return_3Y=0.10)
    block = render_block(fund, _aggregates())
    assert "rose 10.00%" in block or "10.00% rise" in block
