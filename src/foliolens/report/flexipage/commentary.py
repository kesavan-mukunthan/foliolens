"""F4 batch commentary generation — one Anthropic API call per fund.

Entry point: ``uv run python -m foliolens.report.flexipage.commentary --metrics PATH``

See ``specs/spec-flexicap-page.md`` §5, §7-F4, §8. Reads and rewrites
``metrics.json`` in place; commentary lands in the artifact, never at render
time (F2 only reads ``fund.commentary`` — see ``render/templates/fund.html``).
No figures are computed here — the model is handed the fund's own artifact
entry and instructed to use only what's in it (enforced by the F4 offline
test suite, not by any runtime check in this module: ``spec-flexicap-page
§8`` executor guard, "descriptive-only contract is enforced by tests, not
trust").

Commentary is never load-bearing (``spec-flexicap-page §5``): an absent
``ANTHROPIC_API_KEY``, or a fund whose call still errors after
:data:`MAX_RETRIES` retries, leaves that fund's ``commentary`` as ``null`` and
the build continues. Calls are sequential — no concurrency (§5 spec text: one
call per fund at build time).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

#: Fixed per spec-flexicap-page §5 — never varied per call.
MODEL = "claude-haiku-4-5"

#: Persisted alongside every commentary result; also the version this
#: module's :data:`COMMENTARY_V1_SYSTEM_PROMPT` is hashed against (§5).
PROMPT_VERSION = "commentary-v1"

#: A fund failing after this many retries (i.e. this many attempts *beyond*
#: the first) gets ``commentary: null`` — never load-bearing (§5).
MAX_RETRIES = 2

#: Modest per-request timeout (seconds) — a build must not hang on one fund.
REQUEST_TIMEOUT_SECONDS = 30.0

#: Generous ceiling for a 100-150 word, two-paragraph commentary (§5).
MAX_OUTPUT_TOKENS = 1024

#: The commentary-v1 system prompt, copied **verbatim** from
#: ``specs/spec-flexicap-page.md`` §5 — the single source of truth this
#: module (and the F4 test that diffs it against the spec file) both read.
#: Do not paraphrase, reflow, or reword; the spec text itself is the contract.
COMMENTARY_V1_SYSTEM_PROMPT = """You are writing a short factual commentary for a mutual fund
analytics page. You will receive a JSON object containing computed
metrics for one fund and its category context.

Rules — absolute:
- Use ONLY figures present in the JSON. Never compute, estimate,
  round differently, or introduce any number not in the input.
- Descriptive only. No recommendations, no "attractive", "strong
  buy", "avoid", no forward-looking statements, no speculation
  about future performance.
- Do not praise or criticise the fund manager or AMC.
- Neutral third-person analyst voice. No superlatives, no
  marketing language, no exclamation marks.
- British English. 100-150 words, two paragraphs.

Structure:
- Paragraph 1: trailing and calendar-year returns versus the
  category benchmark (name it), noting which windows show out-
  or under-performance.
- Paragraph 2: risk and consistency - volatility, drawdown,
  Sharpe/IR versus category median, and the fund's current
  percentile rank with any notable rank movement visible in
  the rolling data.

If a metric is null/absent, omit it silently. Do not mention
data availability, this prompt, or that you are an AI.

Output: plain text, two paragraphs, nothing else."""

#: A commentary transport: ``(system_prompt, user_message) -> response_text``.
#: Production uses :func:`_anthropic_transport`; tests inject a stub so the
#: suite never calls the API (spec-flexicap-page §7-F4).
CommentaryTransport = Callable[[str, str], str]


def build_user_payload(fund: Mapping[str, Any], universe: Mapping[str, Any]) -> dict[str, Any]:
    """The fund's artifact entry (metrics, calendar_years, ranks, benchmark
    block) plus universe aggregates — verbatim, nothing recomputed
    (``spec-flexicap-page §5``).
    """
    return {
        "amfi_code": fund["amfi_code"],
        "scheme_name": fund["scheme_name"],
        "fund_house": fund["fund_house"],
        "benchmark": fund["benchmark"],
        "metrics": fund["metrics"],
        "calendar_years": fund["calendar_years"],
        "ranks": fund["ranks"],
        "universe_aggregates": universe.get("aggregates", {}),
    }


@dataclass(frozen=True)
class CommentaryResult:
    """One fund's persisted commentary — the exact §3 artifact shape."""

    text: str
    model: str
    prompt_version: str
    generated_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "text": self.text,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "generated_at": self.generated_at,
        }


def _anthropic_transport(api_key: str) -> CommentaryTransport:
    """The only path to the Anthropic API in this module."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)

    def _call(system: str, user_message: str) -> str:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        return "".join(block.text for block in response.content if block.type == "text")

    return _call


def generate_fund_commentary(
    fund: Mapping[str, Any],
    universe: Mapping[str, Any],
    transport: CommentaryTransport,
    *,
    max_retries: int = MAX_RETRIES,
) -> CommentaryResult | None:
    """One fund's commentary, or ``None`` if every attempt fails.

    Sequential retries only — never concurrent (§5). ``max_retries`` failures
    *beyond* the first attempt exhaust the budget; every failure is logged,
    none is raised (commentary is never load-bearing, §5).
    """
    amfi_code = fund.get("amfi_code")
    user_message = json.dumps(
        build_user_payload(fund, universe), allow_nan=False, sort_keys=True
    )
    attempts = max_retries + 1
    last_error: Exception | str | None = None
    for attempt in range(1, attempts + 1):
        try:
            text = transport(COMMENTARY_V1_SYSTEM_PROMPT, user_message).strip()
        except Exception as exc:  # noqa: BLE001 - never load-bearing (spec-flexicap-page §5)
            last_error = repr(exc)
            _LOG.warning(
                "commentary attempt %d/%d failed for %s: %s",
                attempt, attempts, amfi_code, last_error,
            )
            continue
        if not text:
            last_error = "empty response text"
            _LOG.warning(
                "commentary attempt %d/%d for %s returned empty text",
                attempt, attempts, amfi_code,
            )
            continue
        return CommentaryResult(
            text=text,
            model=MODEL,
            prompt_version=PROMPT_VERSION,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
    _LOG.warning(
        "commentary generation failed for %s after %d attempts: %s",
        amfi_code, attempts, last_error,
    )
    return None


@dataclass(frozen=True)
class CommentarySummary:
    """Everything a caller needs after a commentary batch run."""

    metrics_path: Path
    total: int
    generated: int
    failed: int
    skipped_no_key: bool


def run(
    metrics_path: Path, *, transport: CommentaryTransport | None = None
) -> CommentarySummary:
    """Generate commentary for every fund in ``metrics_path`` and rewrite it
    in place. ``transport`` overrides the default Anthropic call (tests only —
    the suite never calls the API); when omitted, an absent
    ``ANTHROPIC_API_KEY`` skips every fund (``commentary: null``, logged, no
    call attempted) rather than raising.
    """
    data: dict[str, Any] = json.loads(metrics_path.read_text(encoding="utf-8"))
    funds: list[dict[str, Any]] = data["funds"]
    universe = data["universe"]

    skipped_no_key = False
    if transport is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            _LOG.warning(
                "ANTHROPIC_API_KEY not set - commentary skipped for all %d funds",
                len(funds),
            )
            skipped_no_key = True
        else:
            transport = _anthropic_transport(api_key)

    generated = 0
    failed = 0
    for fund in funds:
        if transport is None:
            fund["commentary"] = None
            continue
        result = generate_fund_commentary(fund, universe, transport)
        if result is None:
            fund["commentary"] = None
            failed += 1
        else:
            fund["commentary"] = result.to_dict()
            generated += 1

    metrics_path.write_text(
        json.dumps(data, allow_nan=False, indent=2) + "\n", encoding="utf-8"
    )
    return CommentarySummary(
        metrics_path=metrics_path,
        total=len(funds),
        generated=generated,
        failed=failed,
        skipped_no_key=skipped_no_key,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="F4 batch commentary: generate + persist into metrics.json in place"
    )
    parser.add_argument("--metrics", required=True, type=Path, metavar="PATH")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    summary = run(args.metrics)
    if summary.skipped_no_key:
        print(
            f"ANTHROPIC_API_KEY not set: wrote {summary.total} funds with "
            f"commentary: null -> {summary.metrics_path}"
        )
    else:
        print(
            f"commentary: {summary.generated}/{summary.total} generated, "
            f"{summary.failed} failed (null) -> {summary.metrics_path}"
        )


if __name__ == "__main__":
    main()
