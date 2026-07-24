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
  + rank history derived from the rolling panel
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
    "commentary": {"text": str, "model": str, "prompt_version": "commentary-v1",
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

- One Anthropic API call per fund at build time, model **claude-haiku-4-5**,
  system prompt = `commentary-v1` (verbatim below), user message = the fund's
  entry from metrics.json (metrics, calendar_years, ranks, universe
  aggregates). Persisted into metrics.json with model + prompt_version.
- Runs **locally only** this milestone; `ANTHROPIC_API_KEY` from env/`.env`
  (gitignored). Key never in either repo or artifacts. Build proceeds with
  `commentary: null` (block hidden) if key absent or a call fails after 2
  retries — commentary is never load-bearing.

### commentary-v1 (system prompt, verbatim — hash this text as the version)

```
You are writing a short factual commentary for a mutual fund
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
- **F4 Commentary**: Tests: **no-new-numbers** — every numeral token in output
  substring-matches the input JSON (integers ≥2 digits and all decimals;
  ignore standalone "1"/"2" paragraph-safe tokens); word count 80–170; banned
  vocabulary list (buy, sell, avoid, attractive, will outperform, …) absent;
  offline test uses a recorded stub — the suite never calls the API.
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
