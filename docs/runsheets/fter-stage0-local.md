# Runsheet: F-TER stage 0 (local re-run) — TER/AAUM source observation

Local session, WSL2, main checkout. Observe-and-report only: NO parser
code, NO schema, NO fixtures, NO edits to production data or any parquet.
Supersedes the cloud stage-0 attempt (branch
`claude/manifest-fter-ter-aaum-pxl80f`, egress-blocked, all findings
[INDEXED]-grade). Purpose: real files, verbatim headers, AMFI HTTP
behaviour. On any ambiguity: stop, write the report, end.

Report appended as you go to `~/fter-stage0-report-<date>.md`. Downloads
land in `~/foliolens-data/raw-ter-stage0/` (new dir; production trio
untouched). Steps marked USER are performed by the user in a browser;
the session prompts, waits, then inspects.

## Step 1 — HTTP behaviour probe (session)
- `curl -sI https://www.amfiindia.com/ter-of-mf-schemes` and the AAUM
  pages; record status, server headers, any Cloudflare/UA challenge.
  Retry once with a browser UA string. Record verbatim. This is
  observation, not circumvention — no CAPTCHA solving, no header games
  beyond one UA retry.

## Step 2 — TER acquisition (USER)
- From `https://www.amfiindia.com/ter-of-mf-schemes`, download TER
  workbooks for TWO months: one pre-Apr-2026 (target Jan 2026), one
  post (target Jun 2026).
- First check for a consolidated all-AMC download. If none and the page
  is per-AMC form navigation: download THREE AMCs as representative
  samples (one large: HDFC or ICICI Pru; one mid; Samco or another
  boutique) for BOTH months. Stage 0 verifies formats — it is not the
  backfill.
- Note the navigation shape (AMC→scheme→date?) and whether URLs are
  templatable, verbatim in the report.

## Step 3 — AAUM acquisition (USER)
- From `https://www.amfiindia.com/aum-data/average-aum`: download the
  latest monthly AMC-wise file.
- SPECIFIC PROBE: search the page (and `aum-data/aum-disclosure`) for a
  scheme-wise Average AUM workbook (historically a quarterly
  consolidated product). If found, download the latest; this decides
  the AAUM grain question. Record found/not-found either way, with the
  page evidence.

## Step 4 — inspection (session)
Per file: verbatim sheet names, verbatim column headers, row count,
first 3 data rows (values may be truncated; headers never).
- TER pre- vs post-Apr-2026: header delta table; does the post file
  carry BER/levies-on-actuals? Anything named `Base TER` post-break?
- Row granularity: one row per scheme with plan column-blocks, or
  option-level rows? Check at least one AMC with IDCW options.
- Key check: any amfi_code/ISIN column anywhere? Sample 5 scheme names
  against scheme_master.parquet (read-only) — exact-match hit count.
- AAUM: grain of each file (AMC / category / scheme); scheme-wise file
  found or not.
- Delta section: every material divergence from the cloud report's
  [INDEXED] reconstruction, item by item.

## Step 5 — report + STOP
Sections: HTTP behaviour; acquisition notes (navigation shape, effort
per file); verbatim headers per file; granularity findings; AAUM grain
verdict; deltas vs [INDEXED]; open questions for stage 1.
STATUS: `OBSERVED` | `BLOCKED-<reason>`. Stage 0 remains terminal:
stage 1 proceeds only after review of this report.
