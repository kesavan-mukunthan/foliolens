# Runsheet: E local batch — commentary v5 + publish (+ scheme-master rebuild)

Local session, WSL2, main checkout. Execute-and-report; every step is
mechanical. On any ambiguity: stop, write the report, end. No code,
tolerance, prompt, or data edits. Report appended as you go to
`~/e-batch-report-<date>.md`; batch stdout tee'd to `~/e-batch-<date>.log`
— do NOT narrate per-fund progress, report only final counts and verbatim
rejection texts.

Fill at kickoff: `<metrics-path>` (the live metrics.json the published site
was rendered from — the D-run artifact, as_of 2026-06-30, 39 funds),
`<site-checkout>` (local clone of `foliolens-site`).

## Step 1 — preconditions
- `git checkout main && git pull`. Verify by content:
  `grep -c "commentary-v5" src/foliolens/report/flexipage/commentary.py` ≥ 1
  AND `ls src/foliolens/report/flexipage/template_commentary.py`.
  Either fails → STOP, report which.
- `uv sync --all-groups`.
- `test -n "$ANTHROPIC_API_KEY"` — absent → STOP (the export is the user's,
  before session start; generation model is pinned in code).
- `git -C <site-checkout> status` clean; pull.
- Record: HEAD sha; metrics.json as_of and fund count (expect 2026-06-30, 39).
- `cp <metrics-path> <metrics-path>.pre-v5` — preserve the pre-commentary
  artifact of record.

## Step 2 — batch (39 API calls, sequential)
```
uv run python -m foliolens.report.flexipage.commentary --metrics <metrics-path> 2>&1 | tee ~/e-batch-<date>.log
```
No `--only-missing` — v5 regenerates everything (version bump staled v4).
Record generated / retried / null counts. Copy every validation rejection
verbatim into the report. Transport failures land null by design — note,
don't stop.

## Step 3 — sanity gate
Null count > 8 (>20% of cohort) → STOP: report counts + all rejections, do
not render. That is an adjudication, not a retry.

## Step 4 — render + publish
- Render with `--out <site-checkout>` (match the D-run's recorded
  invocation, including `--pdf` if it used it — see
  `~/d-run-report-2026-07-30.md`).
- `git -C <site-checkout> status` — HTML/asset changes only.
- Commit `commentary v5 + deterministic fallback (FolioLens <sha>)`, push.

## Step 5 — live spot-checks (report each pass/fail)
- **118424**: commentary present; paragraph 1 opens with the market-model
  account (benchmark return, beta contribution, residual) for 3Y; if the
  quoted alpha's |t| < 2, hedge phrasing in the same paragraph; no
  percentile in the opening sentence.
- **119718**: same structural checks.
- **Any null-commentary fund**: the deterministic block renders — heading
  "Generated summary (deterministic)", the no-language-model note, prose
  present. If zero funds are null: state so, run
  `uv run pytest tests/test_template_commentary.py -q` as belt-and-braces.
- **Negative check** on any commentary-bearing fund: "skill", "added
  value", "manager ability", "yardstick", "YTD" appear nowhere.

## Step 6 — scheme-master rebuild (same sitting)
- Regenerate the production scheme_master.parquet from the EXISTING raw
  scheme-details shards (no refetch, no network) via the standard build
  path, now including `inception_date` (PR 48).
- Report: rows total; non-null inception count; and the informational
  consistency list — funds where `inception_date > first NAV date` (mfapi
  depth vs true inception; violations are reported, never failed on).

## Step 7 — report
Counts; rejections verbatim; site commit sha; spot-check verdicts;
scheme-master coverage + violations; STATUS: `PUBLISHED` |
`BLOCKED-BATCH` | `BLOCKED-PAGE-CHECK`.

## After (reviewer, not this session)
Review = rejection texts + ~5 randomly sampled commentaries. E closes on
acceptance.
