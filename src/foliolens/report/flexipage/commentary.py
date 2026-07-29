"""F4 batch commentary generation — one Anthropic API call per fund.

Entry point: ``uv run python -m foliolens.report.flexipage.commentary --metrics PATH``

See ``specs/spec-flexicap-page.md`` §5, §7-F4, §8. Reads and rewrites
``metrics.json`` in place; commentary lands in the artifact, never at render
time (F2 only reads ``fund.commentary`` — see ``render/templates/fund.html``).
No figures are computed here — the model is handed the fund's own artifact
entry and instructed to use only what's in it.

The descriptive-only contract is gated at **runtime**, not just by the test
suite: a v1 (claude-haiku-4-5) smoke test surfaced inverted comparatives,
benchmark/category-median conflation, and misread percentile direction; a v2
(claude-sonnet-4-6) smoke test fixed those but still overran the word budget
and, once, wrote "year-to-date" for a closed calendar year; a v3 smoke test
was clean on every named rule but once quoted a raw fraction instead of a
percentage. v4 closes that (a formatting rule), removes the stated-benchmark/
tier fields from the model's input entirely — the source of the benchmark/
category-median conflation class is now absent from the prompt, not just
discouraged in it — and diets the payload itself (:func:`commentary_payload`):
a real batch run showed ~35-40k input tokens per call, because the full
artifact entry carries complete rolling panels and rank histories the model
never needed in full. Rolling/rank-history series are reduced to four
summary points (first, last, min, max) before the call, and the prompt says
so explicitly, so the model describes movement from what it was actually
shown rather than reaching for points it wasn't given. v5 makes the layer
decomposition-first: :func:`commentary_payload` now computes a simple
market-model tracking component per window (``beta_contribution`` = beta ×
benchmark return; the residual is the CAPM Jensen's alpha already carried on
the fund) and surfaces each window's alpha value with its t-stat — but only
where the window clears the same significance sample-size threshold the page
uses, so a suppressed alpha is never quotable in commentary either. The
prompt opens paragraph 1 on that decomposition and adds a significance
register; :func:`validate_commentary` gains four matching runtime gates
(beta_contribution reconciliation, a sub-2-t alpha hedge, no quoting of a
suppressed alpha, and the new banned vocabulary). The figures still arrive
as input — the never-compute contract is unbroken.
Since the remaining violations are the model's, not the pipeline's,
:func:`validate_commentary` checks every real response before it's
persisted, and :func:`generate_fund_commentary` retries once — with the
violated rules named back to the model — before giving up. Commentary is
never load-bearing (§5): an absent ``ANTHROPIC_API_KEY``, or a fund whose
response still violates the contract after that one retry, leaves that
fund's ``commentary`` as ``null`` and the build continues. Calls are
sequential — no concurrency (§5 spec text: one call per fund at build time).

``--only-missing`` makes a rebuild idempotent: a fund whose ``commentary`` is
already non-null is skipped entirely — no API call, no validation, its block
left untouched. The F1 runner always assembles ``commentary: null`` for
every fund, so on its own ``--only-missing`` would regenerate everything on
every rebuild; its companion is the runner's ``--carry-commentary``, which
copies forward matching-version blocks from the previous artifact before
this module ever runs. Full idempotent refresh sequence (spec-flexicap-page
§5): ``runner --carry-commentary prev.json`` → ``commentary --only-missing``
→ ``render``.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from .render.presentation import (
    ALPHA_T_STAT_GREY_THRESHOLD,
    T_STAT_MIN_MONTHS,
    benchmark_display_name,
)

_LOG = logging.getLogger(__name__)

#: Fixed per spec-flexicap-page §5 — never varied per call. Relational
#: fidelity across ~30 figures per fund is the binding constraint; a v1
#: haiku smoke test showed inverted comparatives, benchmark/median
#: conflation, and misread percentile direction — sonnet is worth the cost
#: at this scale.
MODEL = "claude-sonnet-4-6"

#: Persisted alongside every commentary result; also the version this
#: module's :data:`COMMENTARY_V5_SYSTEM_PROMPT` is hashed against (§5). The
#: v5 bump is substantively correct even though nothing about the descriptive-
#: only contract loosened: the payload *shape* changed (market-model
#: decomposition — ``beta_contribution`` + the ``alpha`` block), so v4 blocks
#: carried forward would describe a fund from a different set of inputs and
#: are correctly treated as stale under the carry mechanism (§5).
PROMPT_VERSION = "commentary-v5"

#: One retry, on a validation violation (:func:`validate_commentary`) or a
#: transport exception alike — a second failure gets ``commentary: null``
#: (§5, never load-bearing).
MAX_RETRIES = 1

#: Modest per-request timeout (seconds) — a build must not hang on one fund.
REQUEST_TIMEOUT_SECONDS = 30.0

#: Generous ceiling for a 100-150 word, two-paragraph commentary (§5).
MAX_OUTPUT_TOKENS = 1024

#: Runtime word-count gate (spec-flexicap-page §7-F4) — tighter than the
#: prompt's own 100-150 word target, with headroom for the model rounding up.
MIN_WORDS = 100
MAX_WORDS = 170

#: Case-insensitive, whole-word/phrase match. The first seven are the
#: original descriptive-only guard; "yardstick" and "year-to-date" are the
#: commentary-v3 additions — both were real failures in the v1/v2 smoke
#: tests (the internal comparator label leaking into prose, and a closed
#: calendar year mislabelled as partial). "skill", "added value" and
#: "manager ability" are the commentary-v5 additions: with the market-model
#: decomposition now quoted in paragraph 1, the residual alpha must be read as
#: the return benchmark exposure does not explain — never as evidence of
#: manager skill (§5, "Market model — absolute").
BANNED_VOCABULARY: tuple[str, ...] = (
    "buy",
    "sell",
    "avoid",
    "attractive",
    "will outperform",
    "top pick",
    "must",
    "yardstick",
    "year-to-date",
    "skill",
    "added value",
    "manager ability",
)

_NUMERAL_TOKEN_RE = re.compile(r"\d*\.\d+|\d{2,}")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")

#: The windows over which the market-model decomposition (v5) is emitted —
#: the same 1Y/3Y/5Y trio the relative metrics use (``assembly._RELATIVE_
#: WINDOWS``); named here to keep this module free of a build-time import.
_MARKET_MODEL_WINDOWS: tuple[str, ...] = ("1Y", "3Y", "5Y")

#: Fraction-scale precision the computed ``beta_contribution`` is rounded to
#: before it enters the payload. Six decimals preserves the two-decimal-place
#: *percent* the prompt allows (0.001234 → 0.12%) with two orders of headroom,
#: and matches the module's own 1e-6 scale-match world
#: (:data:`_SCALE_MATCH_TOLERANCE`) — so the round strips float-product noise
#: without ever shifting a figure the model could quote.
_BETA_CONTRIBUTION_NDIGITS = 6

#: The hedge phrases that satisfy the v5 significance register: an alpha
#: quoted for a window whose ``|t_stat| < 2`` must sit in a paragraph that
#: also states the residual is not statistically distinguishable from zero.
#: Case-folded substring match (the prompt names these exact phrases).
_SIGNIFICANCE_HEDGES: tuple[str, ...] = ("not statistically", "indistinguishable")

#: The commentary-v5 system prompt, copied **verbatim** from
#: ``specs/spec-flexicap-page.md`` §5 — the single source of truth this
#: module (and the F4 test that diffs it against the spec file) both read.
#: Do not paraphrase, reflow, or reword; the spec text itself is the contract.
#: v2 (vs v1) added explicit relational-fidelity rules. v3 (vs v2) added two
#: more, verbatim, after a v2 smoke test on claude-sonnet-4-6 still wrote
#: "yardstick" (the internal comparator label) and "year-to-date" for a
#: closed calendar year — both rules now also gate at runtime
#: (:func:`validate_commentary`). v4 (vs v3) added the raw-fraction rule and
#: the summary-points rule and dropped the stated-benchmark/tier payload
#: fields. v5 (vs v4) is the decomposition-first turn: paragraph 1 now opens
#: with the market-model account of the primary window (benchmark return,
#: the supplied ``beta_contribution``, and the residual alpha — all quoted
#: from the JSON), the distinctiveness rule is demoted to paragraph 2, and a
#: significance register lands (hedge a sub-2-t alpha, never quote a
#: suppressed one, and the "skill"/"added value"/"manager ability"
#: vocabulary is banned outright). All four additions also gate at runtime
#: (:func:`validate_commentary`, rules (a)–(d)).
COMMENTARY_V5_SYSTEM_PROMPT = """You are writing a short factual commentary for a mutual fund
analytics page. You will receive a JSON object containing computed
metrics for one fund and its category context.

Rules — absolute:
- Use ONLY figures present in the JSON. Never compute, estimate,
  round differently (except percentiles, below), or introduce any
  number not in the input.
- Use figures only with the labels they carry in the JSON. A full
  calendar year is never "year-to-date". The category median and
  the benchmark are different comparators — never merge them in
  one phrase.
- Call the category comparator "the category benchmark" (naming the
  index). The word "yardstick" must never appear, even if it
  appears in field names in the JSON.
- Never write "year-to-date" or "YTD". Calendar-year figures are
  full-year figures and are described by their year alone.
- Percentile ranks: lower is better; 1 is approximately the top of
  the cohort, 100 the bottom. Never describe a low percentile as
  underperformance. Round percentiles to whole numbers in prose.
- Before writing any comparative (above, below, exceeded, trailed,
  outperformed, underperformed), verify the direction against the
  two figures being compared. If uncertain, state both figures
  without a comparative.
- Descriptive only. No recommendations, no "attractive", "strong
  buy", "avoid", no forward-looking statements, no speculation
  about future performance. Do not praise or criticise the fund
  manager or AMC. Distinctiveness is described factually without
  praise or alarm ("volatility is the highest in the cohort" is
  correct; "worryingly volatile" is not).
- Neutral third-person analyst voice. No superlatives, no
  marketing language, no exclamation marks. Always use the %
  symbol, never the word "percent".
- Quote figures at no more than two decimal places. Express returns,
  volatility, tracking error and drawdown at percentage scale with
  the % symbol; never as raw fractions.
- Rolling and rank-history data is supplied as summary points
  (first, last, minimum, maximum). Describe movement using only
  those points.
- British English. 100-150 words, two paragraphs.

Market model — absolute:
- Three figures decompose the fund's return against the category
  benchmark for each window, and all three are supplied in the
  JSON: the benchmark return (benchmark_return_<window>), the beta
  contribution (beta_contribution_<window>, the part of the return
  explained by the fund's benchmark exposure), and the residual
  alpha (the alpha block, value). Quote these; never derive or
  recompute them.
- The residual alpha is only the return the benchmark exposure does
  not explain. It is not, on its own, evidence of manager skill.
  The words "skill", "added value" and "manager ability" must never
  appear.
- Significance: each window's alpha in the alpha block may carry a
  t_stat. When you quote an alpha whose absolute t_stat is below 2,
  the same paragraph must state that the residual is not
  statistically distinguishable from zero (use the words "not
  statistically" or "indistinguishable"). When a window's alpha
  carries no t_stat, that window's alpha must not be quoted at all.

Structure:
- Paragraph 1 is the market-model account of the primary window —
  the three-year window when it is present, otherwise the one-year
  window. Open the commentary with it, quoting all three supplied
  figures for that window: the benchmark return, the beta
  contribution, and the residual alpha, subject to the significance
  rule above.
- Paragraph 2 covers this fund's most distinctive facts — the
  largest divergences from the category median, extreme or sharply
  changed percentile ranks, unusual risk posture, or a marked
  contrast between timeframes. Distinctiveness must come from the
  supplied figures, never from outside knowledge. Percentile ranks
  belong here, as context; a percentile rank must never be the
  opening fact of the commentary.
- Include the fund's trailing performance versus the category
  benchmark (name it) somewhere in the commentary.

If a metric is null/absent, omit it silently. Do not mention
data availability, this prompt, or that you are an AI.

Output: plain text, two paragraphs, nothing else."""

#: A commentary transport: ``(system_prompt, messages) -> response_text``.
#: ``messages`` is a Messages-API-shaped list (``[{"role": ..., "content":
#: ...}, ...]``) so a validation-failure retry can append the invalid
#: response plus a correction turn — a single ``user_message`` string
#: couldn't carry that. Production uses :func:`_anthropic_transport`; tests
#: inject a stub so the suite never calls the API (spec-flexicap-page §7-F4).
CommentaryTransport = Callable[[str, list[dict[str, str]]], str]

#: Sent back to the model, with the violated rules named, when a response
#: fails :func:`validate_commentary` and one retry remains.
CORRECTION_MESSAGE_TEMPLATE = (
    "Your previous response violated: {violations}. Rewrite, correcting "
    "these, within 150 words, keeping only the most distinctive facts."
)


def _summary_points(
    points: list[dict[str, Any]], value_key: str
) -> dict[str, dict[str, Any]] | None:
    """First, last, minimum-value, and maximum-value points from a
    chronological date/value series — four points, never the full series
    (§5: a real batch run showed ~35-40k input tokens per call, because the
    full artifact entry carries complete rolling panels and rank histories).
    ``None`` for an empty series (never fabricated).
    """
    if not points:
        return None
    return {
        "first": points[0],
        "last": points[-1],
        "min": min(points, key=lambda p: p[value_key]),
        "max": max(points, key=lambda p: p[value_key]),
    }


def _window_n_months(windows: Mapping[str, Any], window: str) -> int | None:
    """This window's ``n_months`` from the fund's per-window disclosure block
    (``spec-flexicap-page`` B2), or ``None`` when the block or the count is
    absent. Mirrors ``render.presentation._window_n_months`` so commentary
    suppresses a thin-sample alpha t-stat at exactly the sample size the page
    does — the two surfaces never disagree about which alphas are significant.
    """
    entry = windows.get(window)
    if not isinstance(entry, Mapping):
        return None
    n = entry.get("n_months")
    return int(n) if isinstance(n, int) and not isinstance(n, bool) else None


def _market_model_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """``metrics`` with the per-window market-model tracking component added:
    ``beta_contribution_W = beta_W × benchmark_return_W`` for every window
    where both inputs are present (v5).

    This is the *simple market-model* component of the fund's return that its
    benchmark exposure explains; the residual left over is the CAPM Jensen's
    alpha carried in the ``alpha`` block. It is computed here, never by the
    model — the never-compute contract holds because the figure arrives as
    input (§5). Rounded to :data:`_BETA_CONTRIBUTION_NDIGITS` fraction-scale
    places to strip float-product noise without shifting a quotable figure.
    """
    out = dict(metrics)
    for window in _MARKET_MODEL_WINDOWS:
        beta = metrics.get(f"beta_{window}")
        benchmark_return = metrics.get(f"benchmark_return_{window}")
        if beta is None or benchmark_return is None:
            continue
        out[f"beta_contribution_{window}"] = round(
            beta * benchmark_return, _BETA_CONTRIBUTION_NDIGITS
        )
    return out


def _alpha_summary(
    fund_alpha: Mapping[str, Any], windows: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """Each window's Jensen's alpha reduced to what commentary may use: the
    ``value`` always, and the ``t_stat`` **only** where the window's sample
    clears :data:`~foliolens.report.flexipage.render.presentation.T_STAT_MIN_MONTHS`
    — the same threshold the page's alpha cell uses
    (``render.presentation.build_alpha_row``, D2c).

    A window whose t-stat is suppressed keeps its ``value`` in the payload —
    so :func:`validate_commentary` can positively guard against that figure
    being quoted (rule (c)) — but drops the ``t_stat``, which is exactly the
    signal the prompt and validator read as "this window's alpha must not be
    quoted". A window with no alpha object is omitted entirely (never a
    fabricated/empty entry).
    """
    summary: dict[str, dict[str, Any]] = {}
    for window in _MARKET_MODEL_WINDOWS:
        entry = fund_alpha.get(f"alpha_{window}")
        if not isinstance(entry, Mapping):
            continue
        value = entry.get("value")
        if value is None:
            continue
        out: dict[str, Any] = {"value": value}
        n_months = _window_n_months(windows, window)
        if n_months is not None and n_months >= T_STAT_MIN_MONTHS:
            t_stat = entry.get("t_stat")
            if t_stat is not None:
                out["t_stat"] = t_stat
        summary[f"alpha_{window}"] = out
    return summary


def commentary_payload(fund: Mapping[str, Any], universe: Mapping[str, Any]) -> dict[str, Any]:
    """The diet payload actually sent to the model (``spec-flexicap-page
    §5``) — nothing recomputed, only reduced.

    The stated benchmark and its tier (``fund.benchmark.stated`` / ``.tier``)
    are page furniture for the tier-fallback footnote, not commentary
    material — they are never sent to the model, which removes the
    benchmark/category-median conflation class entirely rather than relying
    on a prompt rule to suppress it. The only comparator identity the model
    receives is the category benchmark's display name, under the single flat
    field ``category_benchmark`` (e.g. "Nifty 500 TRI") — the same name F2
    renders on the page (:func:`.render.presentation.benchmark_display_name`),
    so the commentary and the page it sits on never disagree about what the
    comparator is called.

    Rolling panels and rank histories are each reduced to four summary
    points (:func:`_summary_points`) — a panel with no points is omitted
    entirely, never an empty/fabricated entry. ``ranks`` carries only the
    latest percentile per metric-window; the full rank history moves to
    ``rank_history_summary``. ``universe`` carries only ``count`` and
    ``aggregates`` — ``category``/``yardstick`` add nothing the model needs
    once ``category_benchmark`` already names the comparator.

    v5 adds the market-model decomposition: ``metrics`` gains a
    ``beta_contribution_W`` per window (:func:`_market_model_metrics`), and a
    new ``alpha`` block surfaces each window's Jensen's alpha ``value`` with
    its ``t_stat`` where the sample is large enough (:func:`_alpha_summary`).
    Both are reductions/products of figures already on the fund — nothing is
    recomputed from raw data — so the never-compute contract is preserved.
    """
    rank_history_summary: dict[str, dict[str, Any]] = {}
    ranks_latest: dict[str, Any] = {}
    for key, entry in fund["ranks"].items():
        ranks_latest[key] = entry.get("pct")
        history = entry.get("history") or []
        points = [{"date": p["date"], "pct": p["pct"]} for p in history]
        summary = _summary_points(points, "pct")
        if summary is not None:
            rank_history_summary[key] = summary

    rolling_summary: dict[str, dict[str, Any]] = {}
    for panel_name, points in fund.get("rolling", {}).items():
        shaped = [{"date": p["date"], "value": p["value"]} for p in points]
        summary = _summary_points(shaped, "value")
        if summary is not None:
            rolling_summary[panel_name] = summary

    return {
        "fund": {"name": fund["scheme_name"], "fund_house": fund["fund_house"]},
        "category_benchmark": benchmark_display_name(fund["benchmark"]["yardstick"]),
        "metrics": _market_model_metrics(fund["metrics"]),
        "alpha": _alpha_summary(fund.get("alpha", {}), fund.get("windows", {})),
        "calendar_years": fund["calendar_years"],
        "ranks": ranks_latest,
        "rank_history_summary": rank_history_summary,
        "rolling_summary": rolling_summary,
        "universe": {
            "count": universe.get("count"),
            "aggregates": universe.get("aggregates", {}),
        },
    }


def _numeral_tokens(text: str) -> list[str]:
    """Every numeral token of 2+ digits or any decimal (§7-F4); standalone
    single digits — e.g. paragraph markers — never match.
    """
    return _NUMERAL_TOKEN_RE.findall(text)


def _banned_vocabulary_hits(text: str) -> list[str]:
    lowered = text.lower()
    return [
        term for term in BANNED_VOCABULARY if re.search(rf"\b{re.escape(term)}\b", lowered)
    ]


def _paragraph_count(text: str) -> int:
    return len([p for p in _PARAGRAPH_SPLIT_RE.split(text.strip()) if p.strip()])


#: Absolute tolerance on the rounded-value comparison in
#: :func:`_matches_at_some_scale` — the same order of magnitude as this
#: codebase's own float-reconciliation convention (``CLAUDE.md``: own ↔
#: oracle at relative ≤ 1e-6), generous enough to absorb float round-trip
#: noise while never blurring two genuinely different figures together.
_SCALE_MATCH_TOLERANCE = 1e-6

#: The scale factors a written figure can be a faithful transform of an
#: artifact value under: the artifact stores fractions (0.0218), prose
#: writes percent (2.18) — that's ×100. ÷100 is kept for symmetry (a value
#: already on a 0-100 scale, e.g. a percentile rank, echoed as a fraction).
_SCALE_FACTORS = (1.0, 100.0, 0.01)


def _json_numeric_leaves(node: object) -> list[float]:
    """Every numeric leaf value in a parsed JSON structure (not its string
    values or dict keys — those are still covered by the literal-substring
    check, e.g. a calendar year used as a dict key, or a benchmark code
    like ``NIFTY500TRI`` embedding ``500``).
    """
    values: list[float] = []
    if isinstance(node, bool):
        return values
    if isinstance(node, (int, float)):
        values.append(float(node))
    elif isinstance(node, dict):
        for v in node.values():
            values.extend(_json_numeric_leaves(v))
    elif isinstance(node, list):
        for v in node:
            values.extend(_json_numeric_leaves(v))
    return values


def _decimal_places(token: str) -> int:
    return len(token.split(".", 1)[1]) if "." in token else 0


def _matches_at_some_scale(token: str, json_values: list[float]) -> bool:
    """Whether ``token`` (a numeral with no sign, per :func:`_numeral_tokens`)
    is some JSON value rounded to the token's own decimal precision, at any
    of :data:`_SCALE_FACTORS` — the fix for the dominant real-world false
    positive: a fraction in the artifact (``0.0218``) written as a percent
    in prose (``"2.18"``), which never substring-matches its own JSON source.
    """
    try:
        token_value = float(token)
    except ValueError:
        return False
    decimals = _decimal_places(token)
    for value in json_values:
        for factor in _SCALE_FACTORS:
            rounded = round(abs(value) * factor, decimals)
            if abs(rounded - token_value) < _SCALE_MATCH_TOLERANCE:
                return True
    return False


def _fabricated_numbers(text: str, input_json: str) -> list[str]:
    """Numeral tokens in ``text`` that are neither a literal substring of
    ``input_json`` nor a same-value-at-another-scale match
    (:func:`_matches_at_some_scale`) — genuinely absent figures.
    """
    tokens = list(dict.fromkeys(_numeral_tokens(text)))
    if not tokens:
        return []
    json_values = _json_numeric_leaves(json.loads(input_json))
    return [
        tok
        for tok in tokens
        if tok not in input_json and not _matches_at_some_scale(tok, json_values)
    ]


def _paragraphs(text: str) -> list[str]:
    """Non-empty, blank-line-separated paragraphs of ``text`` — the unit the
    v5 significance register reasons over ("in the same paragraph").
    """
    return [p for p in _PARAGRAPH_SPLIT_RE.split(text.strip()) if p.strip()]


def _value_is_quoted(value: float, text: str) -> bool:
    """Whether any numeral token in ``text`` is a faithful rendering of
    ``value`` at any of :data:`_SCALE_FACTORS` — the same scale-aware match
    the no-new-numbers rule uses, so "the figure appears in the prose" means
    exactly what it means everywhere else in this module.
    """
    return any(_matches_at_some_scale(tok, [value]) for tok in _numeral_tokens(text))


def _has_significance_hedge(paragraph: str) -> bool:
    lowered = paragraph.lower()
    return any(hedge in lowered for hedge in _SIGNIFICANCE_HEDGES)


def _market_model_violations(text: str, payload: Mapping[str, Any]) -> list[str]:
    """The v5 market-model runtime gates (``spec-flexicap-page §5``), each
    fired only when the prose actually quotes the figure in question:

    (a) a quoted ``beta_contribution_W`` must reconcile to
        ``beta_W × benchmark_return_W`` — the identity :func:`_market_model_
        metrics` built it from (so a payload that shipped a wrong contribution
        can never be faithfully quoted into the page);
    (b) an alpha quoted for a window whose ``|t_stat| < 2`` must sit in a
        paragraph that also carries a significance hedge;
    (c) a window whose ``t_stat`` is suppressed — present in the ``alpha``
        block as a bare ``value`` with no ``t_stat`` — must not have its alpha
        figure quoted at all.

    (d), the new banned vocabulary, is enforced by the shared
    :func:`_banned_vocabulary_hits` and needs nothing here.

    A note on (c)'s precision: the guard fires on any appearance of the
    suppressed alpha value, so in the rare case that a suppressed alpha
    coincides numerically with a legitimately quoted figure it can over-fire;
    the retry names the window, and payload alpha values are distinct enough
    in practice that this is the safe direction to err.
    """
    metrics = payload.get("metrics", {})
    alpha_block = payload.get("alpha", {})
    if not isinstance(metrics, Mapping) or not isinstance(alpha_block, Mapping):
        return []

    violations: list[str] = []
    paragraphs = _paragraphs(text)

    for window in _MARKET_MODEL_WINDOWS:
        contribution = metrics.get(f"beta_contribution_{window}")
        beta = metrics.get(f"beta_{window}")
        benchmark_return = metrics.get(f"benchmark_return_{window}")
        if (
            contribution is not None
            and beta is not None
            and benchmark_return is not None
            and _value_is_quoted(contribution, text)
        ):
            expected = round(beta * benchmark_return, _BETA_CONTRIBUTION_NDIGITS)
            if abs(expected - contribution) > _SCALE_MATCH_TOLERANCE:
                violations.append(
                    f"beta_contribution_{window} ({contribution}) does not "
                    f"reconcile to beta × benchmark_return ({expected})"
                )

        entry = alpha_block.get(f"alpha_{window}")
        if not isinstance(entry, Mapping):
            continue
        alpha_value = entry.get("value")
        if alpha_value is None:
            continue
        quoting_paragraphs = [p for p in paragraphs if _value_is_quoted(alpha_value, p)]
        t_stat = entry.get("t_stat")
        if t_stat is None:
            if quoting_paragraphs:
                violations.append(
                    f"alpha_{window} quoted but its t-stat is suppressed "
                    f"(must not be stated)"
                )
        elif abs(t_stat) < ALPHA_T_STAT_GREY_THRESHOLD and any(
            not _has_significance_hedge(p) for p in quoting_paragraphs
        ):
            violations.append(
                f"alpha_{window} quoted with |t| < 2 but the paragraph lacks "
                f"a significance hedge"
            )

    return violations


def validate_commentary(text: str, input_json: str) -> list[str]:
    """The descriptive-only contract, as a pure function: no I/O, no
    retries. Returns the list of named violations (empty means clean); each
    violation names the exact offending tokens/terms, never just a count, so
    a build log always shows what to look for.

    Shared by the runtime retry path (:func:`generate_fund_commentary`) and
    the F4 test suite (``spec-flexicap-page §7-F4``) — the check the tests
    encode is exactly the check that gates a real response before it's
    persisted, never a parallel implementation that could drift from it.
    """
    violations: list[str] = []

    word_count = len(text.split())
    if not (MIN_WORDS <= word_count <= MAX_WORDS):
        violations.append(f"word count {word_count} outside [{MIN_WORDS}, {MAX_WORDS}]")

    paragraph_count = _paragraph_count(text)
    if paragraph_count != 2:
        violations.append(f"paragraph count {paragraph_count} (must be exactly 2)")

    banned = _banned_vocabulary_hits(text)
    if banned:
        violations.append(f"banned vocabulary: {', '.join(banned)}")

    fabricated = _fabricated_numbers(text, input_json)
    if fabricated:
        violations.append(f"numbers not in input JSON: {', '.join(fabricated)}")

    try:
        payload = json.loads(input_json)
    except (ValueError, TypeError):
        payload = None
    if isinstance(payload, dict):
        violations.extend(_market_model_violations(text, payload))

    return violations


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
    from anthropic.types import MessageParam

    client = anthropic.Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)

    def _call(system: str, messages: list[dict[str, str]]) -> str:
        typed_messages = cast(list[MessageParam], messages)
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system,
            messages=typed_messages,
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
    """One fund's commentary, or ``None`` if it still violates the
    descriptive-only contract after one retry.

    Every real response is checked by :func:`validate_commentary` before
    being persisted — the remaining violations after commentary-v2 were the
    model's, not the pipeline's, so enforcement moved to runtime. On a
    violation (or a transport exception), one retry is attempted; a
    violation retry appends the invalid response plus a correction message
    naming the violated rules, so the model rewrites instead of repeating
    the same mistake blind. A second failure of either kind returns
    ``None`` — commentary is never load-bearing (§5) — and every failure is
    logged, never raised.
    """
    amfi_code = fund.get("amfi_code")
    user_message = json.dumps(
        commentary_payload(fund, universe), allow_nan=False, sort_keys=True
    )
    messages: list[dict[str, str]] = [{"role": "user", "content": user_message}]
    attempts = max_retries + 1
    last_violations: list[str] = []

    for attempt in range(1, attempts + 1):
        try:
            text = transport(COMMENTARY_V5_SYSTEM_PROMPT, messages).strip()
        except Exception as exc:  # noqa: BLE001 - never load-bearing (spec-flexicap-page §5)
            _LOG.warning(
                "commentary attempt %d/%d failed for %s: %r",
                attempt, attempts, amfi_code, exc,
            )
            if attempt == attempts:
                return None
            continue

        violations = validate_commentary(text, user_message)
        if not violations:
            return CommentaryResult(
                text=text,
                model=MODEL,
                prompt_version=PROMPT_VERSION,
                generated_at=datetime.now(timezone.utc).isoformat(),
            )

        last_violations = violations
        _LOG.warning(
            "commentary attempt %d/%d for %s violated: %s",
            attempt, attempts, amfi_code, "; ".join(violations),
        )
        if attempt == attempts:
            break

        messages.append({"role": "assistant", "content": text})
        messages.append(
            {
                "role": "user",
                "content": CORRECTION_MESSAGE_TEMPLATE.format(
                    violations="; ".join(violations)
                ),
            }
        )

    _LOG.warning(
        "commentary null for %s after %d attempts: %s",
        amfi_code, attempts, "; ".join(last_violations),
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
    skipped_populated: int = 0


def run(
    metrics_path: Path,
    *,
    transport: CommentaryTransport | None = None,
    only_missing: bool = False,
) -> CommentarySummary:
    """Generate commentary for every fund in ``metrics_path`` and rewrite it
    in place. ``transport`` overrides the default Anthropic call (tests only —
    the suite never calls the API); when omitted, an absent
    ``ANTHROPIC_API_KEY`` skips every fund (``commentary: null``, logged, no
    call attempted) rather than raising.

    ``only_missing`` (default off — regenerate-all): a fund whose
    ``commentary`` is already non-null is skipped entirely — no API call, no
    :func:`validate_commentary`, its block left untouched in the artifact.
    Pairs with the runner's ``--carry-commentary`` (spec-flexicap-page §5):
    carry first, so unchanged funds already have a block to skip past.
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
    skipped_populated = 0
    for fund in funds:
        if only_missing and fund.get("commentary") is not None:
            skipped_populated += 1
            continue
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
        skipped_populated=skipped_populated,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="F4 batch commentary: generate + persist into metrics.json in place"
    )
    parser.add_argument("--metrics", required=True, type=Path, metavar="PATH")
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help=(
            "skip funds whose commentary is already non-null (no API call, "
            "no validation, untouched) -- default regenerates every fund"
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    summary = run(args.metrics, only_missing=args.only_missing)
    if summary.skipped_no_key:
        print(
            f"ANTHROPIC_API_KEY not set: wrote {summary.total} funds with "
            f"commentary: null -> {summary.metrics_path}"
        )
    else:
        print(
            f"commentary: {summary.generated}/{summary.total} generated, "
            f"{summary.failed} failed (null), {summary.skipped_populated} "
            f"skipped (already populated) -> {summary.metrics_path}"
        )


if __name__ == "__main__":
    main()
