"""F4 commentary tests — offline only; the suite never calls the API.

Covers the F4 acceptance surface (``specs/spec-flexicap-page.md §7-F4``):
stub transport, no-new-numbers, word count 80-170, banned vocabulary absent,
null-tolerance (missing key -> null commentary), and the system prompt
constant matching the spec text verbatim.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from foliolens.report.flexipage.commentary import (
    MAX_RETRIES,
    MODEL,
    PROMPT_VERSION,
    CommentaryResult,
    CommentarySummary,
    COMMENTARY_V1_SYSTEM_PROMPT,
    build_user_payload,
    generate_fund_commentary,
    run,
)

SPEC_PATH = Path(__file__).parent.parent / "specs" / "spec-flexicap-page.md"

BANNED_VOCABULARY = (
    "buy",
    "sell",
    "avoid",
    "attractive",
    "will outperform",
    "top pick",
    "must",
)

_NUMERAL_TOKEN_RE = re.compile(r"\d*\.\d+|\d{2,}")


def _numeral_tokens(text: str) -> list[str]:
    """Every numeral token of 2+ digits or any decimal (§7-F4); standalone
    single digits — the spec's "1"/"2" paragraph-safe tokens — never match.
    """
    return _NUMERAL_TOKEN_RE.findall(text)


def _no_new_numbers(text: str, source_json: str) -> bool:
    return all(tok in source_json for tok in _numeral_tokens(text))


def _word_count(text: str) -> int:
    return len(text.split())


def _contains_banned_vocabulary(text: str) -> bool:
    lowered = text.lower()
    return any(
        re.search(rf"\b{re.escape(term)}\b", lowered) for term in BANNED_VOCABULARY
    )


def _normalise(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Prompt constant == spec text, verbatim (normalised)
# ---------------------------------------------------------------------------


def _spec_commentary_prompt() -> str:
    text = SPEC_PATH.read_text(encoding="utf-8")
    match = re.search(r"### commentary-v1.*?```\n(.*?)```", text, re.S)
    assert match is not None, "could not locate the commentary-v1 fenced block in the spec"
    return match.group(1)


def test_prompt_constant_matches_spec_verbatim() -> None:
    assert _normalise(COMMENTARY_V1_SYSTEM_PROMPT) == _normalise(_spec_commentary_prompt())


# ---------------------------------------------------------------------------
# no-new-numbers check (validates the checker itself, per §7-F4)
# ---------------------------------------------------------------------------


def test_no_new_numbers_passes_when_every_token_is_in_the_source() -> None:
    source = json.dumps({"return_1Y": 0.15, "ranks": {"pct": 12.5}, "year": "2023"})
    text = "Trailing one-year return was 15% and the percentile rank stood at 12.5 as of 2023."
    assert _no_new_numbers(text, source)


def test_no_new_numbers_fails_on_a_fabricated_number() -> None:
    source = json.dumps({"return_1Y": 0.15})
    text = "The fund returned 15% and is projected to grow 42% next year."
    assert not _no_new_numbers(text, source)


def test_no_new_numbers_ignores_standalone_single_digit_tokens() -> None:
    source = json.dumps({"return_1Y": 0.15})
    text = "Paragraph 1 covers returns. Paragraph 2 covers risk. Return was 15%."
    assert _no_new_numbers(text, source)


# ---------------------------------------------------------------------------
# Word count 80-170
# ---------------------------------------------------------------------------


def test_word_count_within_range() -> None:
    text = " ".join(["word"] * 120)
    assert 80 <= _word_count(text) <= 170


def test_word_count_below_range_is_rejected() -> None:
    text = " ".join(["word"] * 10)
    assert not (80 <= _word_count(text) <= 170)


def test_word_count_above_range_is_rejected() -> None:
    text = " ".join(["word"] * 200)
    assert not (80 <= _word_count(text) <= 170)


# ---------------------------------------------------------------------------
# Banned vocabulary
# ---------------------------------------------------------------------------


def test_banned_vocabulary_detected() -> None:
    assert _contains_banned_vocabulary("This looks like an attractive fund to buy now.")
    assert _contains_banned_vocabulary("Investors must consider this a top pick.")
    assert _contains_banned_vocabulary("Analysts expect it will outperform peers.")


def test_banned_vocabulary_absent_in_clean_text() -> None:
    text = (
        "The fund's three-year trailing return was 12% versus the category "
        "benchmark's 10%. Three-year volatility stood at 18%, close to the "
        "category median."
    )
    assert not _contains_banned_vocabulary(text)


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


_SAMPLE_TEXT = (
    "The fund returned 15% over the trailing one-year period and 12% over "
    "three years, measured against the Nifty 500 TRI category benchmark. "
    "Calendar-year returns were 18% in 2023, moderating in 2024 and 2025, "
    "broadly tracking the benchmark across recent years within the "
    "cross-sectional comparison set used for this cohort of funds.\n\n"
    "On risk, three-year volatility stood at 18% and maximum drawdown since "
    "inception reached 22%, sitting above the category's own first quartile "
    "of 08% and below its third quartile of 13% for the same window. "
    "The fund's current percentile rank on the three-year window is 12.5, "
    "placing it toward the upper part of its peer cohort on the ranking "
    "figures available in the underlying data."
)


def test_sample_commentary_passes_all_checks() -> None:
    """Sanity check on the fixture text itself before it's used below."""
    source_json = json.dumps(build_user_payload(_fund(), _universe()), sort_keys=True)
    assert 80 <= _word_count(_SAMPLE_TEXT) <= 170
    assert not _contains_banned_vocabulary(_SAMPLE_TEXT)
    assert _no_new_numbers(_SAMPLE_TEXT, source_json)


# ---------------------------------------------------------------------------
# generate_fund_commentary: retries, success, exhaustion
# ---------------------------------------------------------------------------


def test_generate_fund_commentary_success() -> None:
    def stub(system: str, user_message: str) -> str:
        assert system == COMMENTARY_V1_SYSTEM_PROMPT
        assert "AAAA01" in user_message
        return _SAMPLE_TEXT

    result = generate_fund_commentary(_fund(), _universe(), stub)
    assert isinstance(result, CommentaryResult)
    assert result.text == _SAMPLE_TEXT
    assert result.model == MODEL
    assert result.prompt_version == PROMPT_VERSION == "commentary-v1"
    datetime.fromisoformat(result.generated_at)  # does not raise


def test_generate_fund_commentary_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def stub(system: str, user_message: str) -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient failure")
        return _SAMPLE_TEXT

    result = generate_fund_commentary(_fund(), _universe(), stub)
    assert result is not None
    assert result.text == _SAMPLE_TEXT
    assert calls["n"] == 2


def test_generate_fund_commentary_null_after_max_retries() -> None:
    calls = {"n": 0}

    def stub(system: str, user_message: str) -> str:
        calls["n"] += 1
        raise RuntimeError("permanent failure")

    result = generate_fund_commentary(_fund(), _universe(), stub)
    assert result is None
    assert calls["n"] == MAX_RETRIES + 1


def test_generate_fund_commentary_never_raises() -> None:
    def always_fails(system: str, user_message: str) -> str:
        raise ValueError("boom")

    # Must return None, never propagate — commentary is never load-bearing.
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

    def stub(system: str, user_message: str) -> str:
        return _SAMPLE_TEXT

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
        assert commentary["text"] == _SAMPLE_TEXT
        assert commentary["model"] == MODEL
        assert commentary["prompt_version"] == "commentary-v1"
        datetime.fromisoformat(commentary["generated_at"])


def test_run_null_commentary_for_fund_that_exhausts_retries(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.json"
    _write_metrics(metrics_path, [_fund("AAAA01"), _fund("BBBB02")])

    def failing(system: str, user_message: str) -> str:
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

    def fake_anthropic_transport(api_key: str):
        seen_keys.append(api_key)

        def _stub(system: str, user_message: str) -> str:
            return _SAMPLE_TEXT

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
