"""F4 commentary tests — offline only; the suite never calls the API.

Covers the F4 acceptance surface (``specs/spec-flexicap-page.md §7-F4``):
the ``validate_commentary`` pure function (shared by the runtime retry path
and this suite — no parallel check that could drift), the one-retry-then-null
runtime path, null-tolerance (missing key -> null commentary), and the
system prompt constant matching the spec text verbatim.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from foliolens.report.flexipage.commentary import (
    BANNED_VOCABULARY,
    MAX_RETRIES,
    MAX_WORDS,
    MIN_WORDS,
    MODEL,
    PROMPT_VERSION,
    CommentaryResult,
    CommentarySummary,
    CommentaryTransport,
    COMMENTARY_V3_SYSTEM_PROMPT,
    build_user_payload,
    generate_fund_commentary,
    run,
    validate_commentary,
)

SPEC_PATH = Path(__file__).parent.parent / "specs" / "spec-flexicap-page.md"


def _normalise(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Prompt constant == spec text, verbatim (normalised)
# ---------------------------------------------------------------------------


def _spec_commentary_prompt() -> str:
    text = SPEC_PATH.read_text(encoding="utf-8")
    match = re.search(r"### commentary-v3.*?```\n(.*?)```", text, re.S)
    assert match is not None, "could not locate the commentary-v3 fenced block in the spec"
    return match.group(1)


def test_prompt_constant_matches_spec_verbatim() -> None:
    assert _normalise(COMMENTARY_V3_SYSTEM_PROMPT) == _normalise(_spec_commentary_prompt())


def test_banned_vocabulary_includes_v3_additions() -> None:
    assert "yardstick" in BANNED_VOCABULARY
    assert "year-to-date" in BANNED_VOCABULARY


# ---------------------------------------------------------------------------
# Fixtures: a minimal fund + universe entry, per §3
# ---------------------------------------------------------------------------


def _fund(amfi_code: str = "AAAA01") -> dict[str, Any]:
    return {
        "amfi_code": amfi_code,
        "scheme_name": "Alpha Flexi Cap Fund - Direct Plan - Growth",
        "fund_house": "Alpha Mutual Fund",
        "benchmark": {"stated": "NIFTY500TRI", "tier": "tier1", "yardstick": "NIFTY500TRI"},
        "metrics": {
            "return_1Y": 0.15,
            "return_3Y": 0.12,
            "volatility_3Y": 0.18,
            "sharpe_3Y": 1.2,
            "max_drawdown_SI": -0.22,
        },
        "calendar_years": {"2023": 0.18, "2024": 0.09, "2025": 0.05},
        "alpha": {},
        "rolling": {},
        "ranks": {"return_3Y": {"pct": 12.5, "history": []}},
        "commentary": None,
    }


def _universe() -> dict[str, Any]:
    return {
        "category": "flexi_cap",
        "count": 10,
        "yardstick": "NIFTY500TRI",
        "aggregates": {"return_3Y": {"median": 0.105, "q1": 0.08, "q3": 0.13}},
    }


def _source_json() -> str:
    return json.dumps(build_user_payload(_fund(), _universe()), sort_keys=True)


# A clean, two-paragraph, in-range sample built only from the fixture's own
# figures — the numeral tokens are deliberately picked to be substrings of
# ``_source_json()`` (e.g. 0.105 -> "10.5" would NOT match; percentages are
# derived only from values whose digits already appear after the decimal
# point in the JSON).
_CLEAN_TEXT = (
    "The fund returned 15% over the trailing one-year period and 12% over "
    "three years, measured against the category benchmark. Calendar-year "
    "returns were 18% in 2023, 9% in 2024 and 5% in 2025, tracking the "
    "benchmark across recent years within the cross-sectional comparison "
    "set used for this cohort of funds under review this cycle.\n\n"
    "On risk, three-year volatility stood at 18% and maximum drawdown "
    "since inception reached 22%, sitting above the category's own first "
    "quartile of 08% and below its third quartile of 13% for the same "
    "window. The fund's current percentile rank on the three-year window "
    "is 12.5, placing it toward the upper part of its peer cohort on the "
    "ranking figures available in the underlying data set."
)


def test_clean_sample_has_no_violations() -> None:
    """Sanity check on the fixture text before it's used below."""
    assert validate_commentary(_CLEAN_TEXT, _source_json()) == []


# ---------------------------------------------------------------------------
# validate_commentary: one rule at a time
# ---------------------------------------------------------------------------


def test_validate_commentary_word_count_too_low() -> None:
    text = "Short paragraph one.\n\nShort paragraph two."
    violations = validate_commentary(text, _source_json())
    assert any("word count" in v for v in violations)


def test_validate_commentary_word_count_too_high() -> None:
    text = ("word " * 90).strip() + ".\n\n" + ("word " * 90).strip() + "."
    violations = validate_commentary(text, _source_json())
    assert any("word count" in v for v in violations)


def test_validate_commentary_word_count_in_range_is_clean_of_that_rule() -> None:
    words = ["word"] * 130
    text = " ".join(words[:65]) + ".\n\n" + " ".join(words[65:]) + "."
    violations = validate_commentary(text, _source_json())
    assert not any("word count" in v for v in violations)
    assert MIN_WORDS <= len(text.split()) <= MAX_WORDS


def test_validate_commentary_wrong_paragraph_count_single() -> None:
    text = " ".join(["word"] * 120) + "."
    violations = validate_commentary(text, _source_json())
    assert any("paragraph count" in v for v in violations)


def test_validate_commentary_wrong_paragraph_count_three() -> None:
    para = " ".join(["word"] * 40) + "."
    text = f"{para}\n\n{para}\n\n{para}"
    violations = validate_commentary(text, _source_json())
    assert any("paragraph count" in v for v in violations)


@pytest.mark.parametrize("term", list(BANNED_VOCABULARY))
def test_validate_commentary_flags_every_banned_term(term: str) -> None:
    para1 = " ".join(["word"] * 60) + f" {term}."
    para2 = " ".join(["word"] * 60) + "."
    text = f"{para1}\n\n{para2}"
    violations = validate_commentary(text, _source_json())
    assert any("banned vocabulary" in v and term in v for v in violations)


def test_validate_commentary_yardstick_flagged_even_though_it_is_a_json_key() -> None:
    # "yardstick" is a real field name in the fixture's benchmark block --
    # confirms the check is against the *output text*, not the input JSON.
    assert "yardstick" in _source_json()
    text = _CLEAN_TEXT.replace("category benchmark", "category yardstick")
    violations = validate_commentary(text, _source_json())
    assert any("yardstick" in v for v in violations)


def test_validate_commentary_fabricated_number_flagged() -> None:
    text = _CLEAN_TEXT.replace("15%", "42%")
    violations = validate_commentary(text, _source_json())
    assert any("numbers not in input JSON" in v and "42" in v for v in violations)


def test_validate_commentary_percent_of_json_fraction_passes() -> None:
    """The dominant real-world false positive: the artifact stores a
    fraction (0.0218), prose reports it as a percent (2.18) -- "2.18" is
    never a literal substring of "0.0218" (no decimal point lands between
    the 2 and the 1), so this must pass via the scale-aware match, not the
    substring check.
    """
    fund = _fund()
    fund["metrics"]["return_1Y"] = 0.0218
    input_json = json.dumps(build_user_payload(fund, _universe()), sort_keys=True)
    assert "2.18" not in input_json  # confirms this exercises the scale match

    text = (
        "The fund's trailing one-year return was 2.18% against the category "
        "benchmark, a modest but positive result for the period under review "
        "this cycle across the twelve-month window measured to date overall.\n\n"
        "No further figures are referenced in this short illustrative sample "
        "paragraph, which exists only to exercise the percent-of-fraction "
        "scale match in the validator against the fixture's own figures."
    )
    violations = validate_commentary(text, input_json)
    assert not any("numbers not in input JSON" in v for v in violations)


def test_validate_commentary_genuinely_absent_value_fails_at_both_scales() -> None:
    """A value that is absent at 1x, 100x, and 0.01x scale alike must still
    be flagged -- the fix widens what counts as a match, it doesn't disable
    the check.
    """
    fund = _fund()
    fund["metrics"]["return_1Y"] = 0.1318
    input_json = json.dumps(build_user_payload(fund, _universe()), sort_keys=True)
    text = _CLEAN_TEXT.replace("15%", "14.7%")
    violations = validate_commentary(text, input_json)
    assert any("numbers not in input JSON" in v and "14.7" in v for v in violations)


def test_validate_commentary_multiple_violations_all_reported() -> None:
    text = "This fund is a top pick with a yardstick-beating 42% return."
    violations = validate_commentary(text, _source_json())
    joined = "; ".join(violations)
    assert "word count" in joined
    assert "paragraph count" in joined
    assert "banned vocabulary" in joined
    assert "numbers not in input JSON" in joined


# ---------------------------------------------------------------------------
# generate_fund_commentary: the one-retry, validate-before-persist path
# ---------------------------------------------------------------------------


def test_generate_fund_commentary_success_when_clean() -> None:
    def stub(system: str, messages: list[dict[str, str]]) -> str:
        assert system == COMMENTARY_V3_SYSTEM_PROMPT
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "AAAA01" in messages[0]["content"]
        return _CLEAN_TEXT

    result = generate_fund_commentary(_fund(), _universe(), stub)
    assert isinstance(result, CommentaryResult)
    assert result.text == _CLEAN_TEXT
    assert result.model == MODEL == "claude-sonnet-4-6"
    assert result.prompt_version == PROMPT_VERSION == "commentary-v3"
    datetime.fromisoformat(result.generated_at)  # does not raise


def test_generate_fund_commentary_retries_after_violation_then_succeeds() -> None:
    calls: list[list[dict[str, str]]] = []

    def stub(system: str, messages: list[dict[str, str]]) -> str:
        calls.append([dict(m) for m in messages])
        if len(calls) == 1:
            return "This is a top pick."  # too short, wrong paragraph count, banned term
        return _CLEAN_TEXT

    result = generate_fund_commentary(_fund(), _universe(), stub)
    assert result is not None
    assert result.text == _CLEAN_TEXT
    assert len(calls) == 2

    # The retry's conversation carries the bad response and a correction
    # turn naming the violated rules -- not just the original user message.
    second_call = calls[1]
    assert len(second_call) == 3
    assert second_call[0]["role"] == "user"
    assert second_call[1] == {"role": "assistant", "content": "This is a top pick."}
    assert second_call[2]["role"] == "user"
    assert "violated" in second_call[2]["content"]
    assert "banned vocabulary" in second_call[2]["content"]


def test_generate_fund_commentary_null_after_second_violation() -> None:
    calls = {"n": 0}

    def stub(system: str, messages: list[dict[str, str]]) -> str:
        calls["n"] += 1
        return "Buy this fund now, it is a top pick!"  # violates every time

    result = generate_fund_commentary(_fund(), _universe(), stub)
    assert result is None
    assert calls["n"] == MAX_RETRIES + 1 == 2


def test_generate_fund_commentary_retries_after_transport_exception_then_succeeds() -> None:
    calls = {"n": 0}

    def stub(system: str, messages: list[dict[str, str]]) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient failure")
        return _CLEAN_TEXT

    result = generate_fund_commentary(_fund(), _universe(), stub)
    assert result is not None
    assert result.text == _CLEAN_TEXT
    assert calls["n"] == 2


def test_generate_fund_commentary_never_raises() -> None:
    def always_fails(system: str, messages: list[dict[str, str]]) -> str:
        raise ValueError("boom")

    # Must return None, never propagate -- commentary is never load-bearing.
    assert generate_fund_commentary(_fund(), _universe(), always_fails) is None


# ---------------------------------------------------------------------------
# run(): writes metrics.json in place
# ---------------------------------------------------------------------------


def _write_metrics(path: Path, funds: list[dict[str, Any]]) -> None:
    artifact = {
        "schema_version": "flexipage-1",
        "as_of": "2026-07-14",
        "universe": _universe(),
        "funds": funds,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact), encoding="utf-8")


def test_run_persists_commentary_fields_in_place(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.json"
    _write_metrics(metrics_path, [_fund("AAAA01"), _fund("BBBB02")])

    def stub(system: str, messages: list[dict[str, str]]) -> str:
        return _CLEAN_TEXT

    summary = run(metrics_path, transport=stub)
    assert isinstance(summary, CommentarySummary)
    assert summary.total == 2
    assert summary.generated == 2
    assert summary.failed == 0
    assert summary.skipped_no_key is False
    assert summary.metrics_path == metrics_path

    data = json.loads(metrics_path.read_text(encoding="utf-8"))
    for fund in data["funds"]:
        commentary = fund["commentary"]
        assert commentary["text"] == _CLEAN_TEXT
        assert commentary["model"] == MODEL
        assert commentary["prompt_version"] == "commentary-v3"
        datetime.fromisoformat(commentary["generated_at"])


def test_run_null_commentary_for_fund_that_exhausts_retries(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.json"
    _write_metrics(metrics_path, [_fund("AAAA01"), _fund("BBBB02")])

    def failing(system: str, messages: list[dict[str, str]]) -> str:
        raise RuntimeError("down")

    summary = run(metrics_path, transport=failing)
    assert summary.generated == 0
    assert summary.failed == 2

    data = json.loads(metrics_path.read_text(encoding="utf-8"))
    for fund in data["funds"]:
        assert fund["commentary"] is None


def test_run_skips_all_funds_when_api_key_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def never_call(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the API must never be called when the key is absent")

    import foliolens.report.flexipage.commentary as commentary_module

    monkeypatch.setattr(commentary_module, "_anthropic_transport", never_call)

    metrics_path = tmp_path / "metrics.json"
    _write_metrics(metrics_path, [_fund("AAAA01"), _fund("BBBB02")])

    summary = run(metrics_path)
    assert summary.skipped_no_key is True
    assert summary.generated == 0
    assert summary.failed == 0
    assert summary.total == 2

    data = json.loads(metrics_path.read_text(encoding="utf-8"))
    for fund in data["funds"]:
        assert fund["commentary"] is None


def test_run_builds_transport_from_env_key_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The key IS present; confirm the module wires it into a transport
    without this test ever touching the network.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")

    seen_keys: list[str] = []

    def fake_anthropic_transport(api_key: str) -> CommentaryTransport:
        seen_keys.append(api_key)

        def _stub(system: str, messages: list[dict[str, str]]) -> str:
            return _CLEAN_TEXT

        return _stub

    import foliolens.report.flexipage.commentary as commentary_module

    monkeypatch.setattr(
        commentary_module, "_anthropic_transport", fake_anthropic_transport
    )

    metrics_path = tmp_path / "metrics.json"
    _write_metrics(metrics_path, [_fund("AAAA01")])

    summary = run(metrics_path)
    assert seen_keys == ["sk-test-not-real"]
    assert summary.skipped_no_key is False
    assert summary.generated == 1
