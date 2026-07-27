# spec-flexicap-page — Flexicap static site + PDF (v1 serving milestone)

**Deliverable.** A statically generated, externally shareable site over the
flexicap category: one universe page, one page per fund, a print-CSS PDF per
fund. Batch-deterministic: compute once, publish artifacts. No server, no
client-side compute beyond navigation.

**Consumes** (does not build): consolidated NAV parquet + scheme master
(spec-benchmarks §1), `index_nav.parquet` (§3), `load_index_series` + rf
(§4–§5), metric functions (spec-analytics §2–§7). This spec owns the batch
runner, the metrics artifact for this page, rendering, commentary, and deploy.

---

## 1. Universe & benchmark policy

- **Universe**: open-ended flexicap schemes, **direct growth** only, live as of
  build date. Scheme master filter: `sebi_category == "flexi_cap"`,
  `plan == "direct"`, `option == "growth"`.
- **Category yardstick**: all cross-sectional relative metrics (excess, TE, IR,
  beta, alpha, ranks) computed against **NIFTY500TRI** for every fund, labelled
  on-page as "vs category benchmark (Nifty 500 TRI)". Rationale: ranks against
  mixed benchmarks are not comparable; SPIVA precedent.
- **Stated-benchmark validation leg**: Bandhan Flexi Cap additionally validated
  against its stated tier-1 (BSE500TRI) where that series has landed —
  reconciliation to factsheet figures at ≤10 bps, recorded in the build log,
  not rendered.
- **Tier fallback (rendering rule)**: if a required index series has not
  landed, dependent figures render with the visible label "vs alternate
  benchmark — tier-1 pending"; never silently substituted, never blank NaN.
- **Survivorship footnote** (universe page + every fund page + PDFs, verbatim):
  > Universe: open-ended flexi-cap schemes (direct growth) live as of July
  > 2026. Funds merged or wound up before this date are not included; category
  > statistics therefore reflect surviving funds only.

## 2. Metrics panel (per fund)

Windows 1Y/3Y/5Y unless stated. All conventions per spec-analytics; nothing
recomputed here — the runner calls existing functions only.

- Trailing returns (SEBI: absolute <1Y, CAGR ≥1Y)
- Calendar-year returns: 2023, 2024, 2025 (`between` + `period_return_abs`)
- Volatility (√12), downside deviation, max drawdown (daily base)
- Sharpe, Sortino (MAR = rf), Calmar
- Vs category yardstick: excess return, tracking error, information ratio,
  beta, Jensen's alpha **with t-stat** (render alpha greyed when |t| < 2)
- Rolling panel, monthly step: rolling 1Y and 3Y {return, volatility, Sharpe,
  excess return}
- Cross-sectional: percentile rank within universe per metric-window (latest)
  + rank history derived from the rolling panel. Percentile ranks: **lower =
  better; 1 ≈ top of cohort** (flipped from `analytics/peer.py`'s own
  higher-is-better convention at the point the artifact is assembled, never
  inside `peer.py` itself).
- Category aggregates: median and quartiles per metric-window

## 3. metrics.json (durable artifact; the seam for any future frontend)

```
{
  "schema_version": "flexipage-1",
  "as_of": "YYYY-MM-DD",
  "universe": {"category": "flexi_cap", "count": N,
               "yardstick": "NIFTY500TRI",
               "aggregates": {metric_window: {median, q1, q3}}},
  "funds": [{
    "amfi_code": str, "scheme_name": str, "fund_house": str,
    "benchmark": {"stated": code|null, "tier": str, "yardstick": "NIFTY500TRI"},
    "metrics": {metric_window: value|null},
    "calendar_years": {"2023": v, "2024": v, "2025": v},
    "rolling": {panel_name: [{"date": d, "value": v}]},
    "ranks": {metric_window: {"pct": v, "history": [{"date": d, "pct": v}]}},
    // pct (latest + history): lower = better; 1 ≈ top of cohort
    "commentary": {"text": str, "model": str, "prompt_version": "commentary-v4",
                    "generated_at": ts} | null
  }]
}
```

Nulls are explicit; renderer omits, never invents. Floats as computed — no
re-rounding outside the presentation layer.

## 4. Rendering

- **Stack**: Jinja2 templates, one shared layout; charts pre-rendered **SVG**
  (matplotlib, no Plotly, no JS charting); dropdown nav = plain `<select>` +
  `location.href`.
- **Pages**: `index.html` (aggregates + ranked table, one row per fund,
  linking to fund pages); `funds/<amfi_code>.html` (header, metrics table,
  NAV-vs-yardstick chart, drawdown chart, two rolling charts incl. rank
  history, commentary block, provenance footer: data as-of + factsheet-verified
  flag); `data/metrics.json` published alongside.
- **PDF**: print stylesheet (`@page`, `page-break-inside: avoid`, nav hidden);
  WeasyPrint over each fund page + index. Fallback if SVG/pagination fights:
  Playwright `page.pdf()`. No separate PDF layout — "PDF = print-CSS render of
  the fund page". Output `funds/<amfi_code>.pdf`, linked from each page.
- **Disclaimer** (site footer + every PDF, verbatim):
  > FolioLens is an analytics project. Nothing here is investment advice or a
  > recommendation. FolioLens is not a SEBI-registered investment adviser.
  > Data from public sources; verify independently before acting.

## 5. Commentary

- One Anthropic API call per fund at build time, model **claude-sonnet-4-6**
  (relational fidelity across ~30 figures per fund is the binding constraint;
  cost is immaterial at this scale), system prompt = `commentary-v4`
  (verbatim below). Persisted into metrics.json with model + prompt_version.
- **Payload diet** (`commentary_payload(fund, universe) -> dict`, unit-tested,
  §7-F4): a real batch run at the previous payload shape cost ~35-40k input
  tokens per call — the full artifact entry carries complete rolling panels
  and rank histories the model never needed in full. The dedicated
  commentary payload sent as the user message carries only: `fund` (`name`,
  `fund_house`); `category_benchmark` — a single flat field holding the
  category yardstick's display name (e.g. `"Nifty 500 TRI"`, the same name
  F2 renders on the page) — with `benchmark.stated`/`.tier` dropped entirely
  (page furniture for the tier-fallback footnote, not commentary material;
  removes the benchmark/stated-vs-category-median conflation class at the
  source rather than relying on a prompt rule to suppress it); `metrics`
  and `calendar_years` as-is; `ranks` — latest percentile per metric-window
  only; `rank_history_summary` and `rolling_summary` — each panel reduced to
  four points (first, last, minimum, maximum), never the full series;
  `universe` — `count` + `aggregates` only. No other fields.
- Runs **locally only** this milestone; `ANTHROPIC_API_KEY` from env/`.env`
  (gitignored). Key never in either repo or artifacts. Build proceeds with
  `commentary: null` (block hidden) if key absent, a call fails after one
  retry, or the response still violates the descriptive-only contract after
  one retry — commentary is never load-bearing.
- **Runtime contract enforcement** (added at v3; the remaining violations
  after v2 were the model's, not the pipeline's — "enforced by tests, not
  trust" moved to a runtime gate): every real response is checked before
  being persisted — word count 100-170, exactly two paragraphs, the banned-
  vocabulary list absent, and the no-new-numbers rule (every numeral token
  of 2+ digits or any decimal must match some input JSON value, either as a
  literal substring or at ×1/×100/×0.01 scale rounded to the token's own
  decimal precision — the artifact stores fractions, prose writes percent).
  On a violation, one retry is sent with the invalid response plus a
  correction message naming the violated rules; a second failure of either
  kind (transport error or violation) leaves `commentary: null`, logged
  with the named violations. The check is one pure function, used
  identically by the runtime path and the F4 test suite, so it can never
  drift between them.
- **Idempotent rebuild**: the F1 runner always assembles `commentary: null`
  for every fund, so on its own a rebuild orphans any commentary already
  generated. `commentary --only-missing` skips a fund whose `commentary` is
  already non-null entirely (no API call, no validation, block untouched);
  the runner's `--carry-commentary <previous-metrics.json>` copies each
  fund's commentary block from the previous artifact by `amfi_code` first,
  provided the block's `prompt_version` matches the current `PROMPT_VERSION`
  — a stale-version block is dropped (a prompt bump forces regeneration),
  and a fund absent from the previous artifact (new to the universe) stays
  `null`. Refresh sequence: `runner --carry-commentary prev.json` →
  `commentary --only-missing` → `render`.

### commentary-v4 (system prompt, verbatim — hash this text as the version)

```
You are writing a short factual commentary for a mutual fund
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

Structure:
- Before writing, identify the two or three most distinctive facts
  in this fund's data — the largest divergences from the category
  median, extreme or sharply changed percentile ranks, unusual
  risk posture, or a marked contrast between timeframes.
  Distinctiveness must come from the supplied figures, never from
  outside knowledge.
- Open with the most distinctive fact. Organise the commentary
  around the distinctive facts; cover remaining figures only where
  they add context. Do not recite every metric in order.
- Include the fund's trailing performance versus the category
  benchmark (name it) somewhere in the commentary.

If a metric is null/absent, omit it silently. Do not mention
data availability, this prompt, or that you are an AI.

Output: plain text, two paragraphs, nothing else.
```

## 6. Deploy

- Public repo **`foliolens-site`**: built artifacts only (HTML, SVG, PDF,
  metrics.json) — no source, no raw data. Pages serves `main`.
- Build runs locally; output pushed to `foliolens-site`. The only workflow in
  the site repo is Pages deploy. **No scheduled/CI fetching or building
  anywhere** — publishing is a deliberate local act this milestone.

## 7. Stages & tests (each stage loops to green before the next)

- **F1 Runner → metrics.json**: assemble panel via existing functions.
  Tests: schema validation (jsonschema, committed); every universe fund
  present; ranks per metric-window form a permutation over non-null funds;
  Bandhan trailing + calendar-year figures reconcile to factsheet fixtures
  (`fixtures/published_returns.csv` extension) at ≤10 bps; null-propagation
  (fund with <3Y history renders nulls, not errors).
- **F2 HTML render**: Tests (smoke): a page exists per fund; index row count ==
  universe count; all internal links resolve; no "NaN"/"None" in rendered
  text; footnote + disclaimer strings present on every page.
- **F3 PDF**: Tests: PDF exists per fund; page count ≥1; disclaimer string
  present in extracted text.
- **F4 Commentary**: `validate_commentary(text, input_json) -> list[str]` (§5)
  is the single check, shared by the runtime retry path and the test suite —
  `input_json` is the diet payload (`commentary_payload`'s output, the
  numbers the model was actually shown), not the full artifact entry:
  **no-new-numbers** — every numeral token in output matches some payload
  value, as a literal substring or at ×1/×100/×0.01 scale (integers ≥2
  digits and all decimals; ignore standalone "1"/"2" paragraph-safe
  tokens); word count 100–170; exactly two paragraphs; banned vocabulary
  list (buy, sell, avoid, attractive, will outperform, top pick, must,
  yardstick, year-to-date) absent. Tests cover the validator directly plus
  the retry path (a stub that violates once then passes) and the null path
  (a stub that violates twice); offline only — the suite never calls the
  API. `commentary_payload` is separately unit-tested: no list in the
  payload exceeds 4 elements, and the serialised payload stays under 16,000
  characters (a rough chars/4 proxy for ~4,000 tokens) for the synthetic
  fixture.
- **F5 Publish**: manual checklist, not automated: Pages URL loads, Bandhan
  page + PDF spot-checked against factsheet, no raw-data files in site repo.

## 8. Executor guards

- Compute nothing in this module that spec-analytics owns; call, don't
  reimplement. New metric conventions are out of scope here.
- No network at build time except the commentary API call. No fetching of
  market data in any workflow, CI, or schedule (one-time local acquisition
  aids live outside the pipeline; parsers take local files).
- No JS frameworks, no client-side data fetching, no Plotly, no TypeScript —
  future frontend consumes metrics.json via spec-ui, not this spec.
- Rendered figures come from metrics.json only. Commentary is presentation-
  layer; it introduces no figures (enforced by F4 tests).
- "Fund dossier" naming is reserved for the later PDF deliverable; this page
  and its PDF are the "flexicap page" throughout.
