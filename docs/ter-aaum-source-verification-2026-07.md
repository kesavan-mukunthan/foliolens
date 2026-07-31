# F-TER Stage 0 — TER + AAUM source verification report (local re-run)

*Manifest: F-TER (TER + AAUM ingest). Stage 0 is a **terminal gate**: report
and STOP; no parser code. Parser design is confirmed against this report
before Stage 1. Local session, WSL2, main checkout, 2026-07-29/30. Supersedes
the cloud sandbox's egress-blocked attempt (branch
`claude/manifest-fter-ter-aaum-pxl80f`, all findings `[INDEXED]`-grade,
never merged) — this run fetched and inspected real AMFI files.*

Runsheet: `docs/runsheets/fter-stage0-local.md` (removed by this commit per
the standing runsheet-lifecycle rule — its item is closed).

Data root: `/home/kesavanm19/foliolens-data/data` (nav.parquet,
index_nav.parquet, scheme_master.parquet — read-only reference throughout
this run). Downloaded files landed in `~/foliolens-data/raw-ter-stage0/`
(outside the repo; not committed).

---

## Step 1 — HTTP behaviour probe

All three AMFI pages return `200 OK` on first request, no CAPTCHA/challenge,
identical response (same `Content-Length`/`ETag` on repeat) with default curl
UA vs. a Chrome browser UA retry — no UA-conditional gating observed.

| URL | UA | Status | Server | Cache | Notes |
|---|---|---|---|---|---|
| `/ter-of-mf-schemes` | curl default | 200 | nginx | `x-nextjs-cache: HIT` | Next.js SSR/ISR page (`X-Powered-By: Next.js`), `s-maxage=3600` |
| `/ter-of-mf-schemes` | Chrome UA | 200 | nginx | `x-nextjs-cache: HIT` | identical `Content-Length` (179166) and `ETag` to curl-default request |
| `/aum-data/average-aum` | curl default | 200 | nginx | `x-nextjs-cache: STALE` | first hit triggered ISR revalidation |
| `/aum-data/average-aum` | Chrome UA | 200 | nginx | `x-nextjs-cache: HIT` | `Content-Length` shifted 260030→260019 between the two requests (8s apart) — page embeds a dynamic element (likely a "last updated"/date string), not a static asset |
| `/aum-data/aum-disclosure` | curl default | 200 | nginx | `x-nextjs-cache: HIT` | — |

No Cloudflare, no bot-challenge headers, no `Set-Cookie` on any response.
Security headers present (HSTS, X-Frame-Options, X-Content-Type-Options) but
nothing UA- or automation-gated at the HTTP layer for these three pages.
Verdict: no circumvention concern for a manual/browser download in step
2/3 — plain reachable pages.

Navigation shape (read-only page inspection, no downloads triggered):

- `/ter-of-mf-schemes`: **form/selector page, not a static-link/consolidated
  page**. Dropdowns: Financial Year, Month, Fund Type, Category, Mutual Fund
  (AMC), + "Go" button. No AMC list or file links visible in the fetched
  markup (dropdown options are populated client-side) — confirms AMC→date
  selector, not a templatable URL.
- `/aum-data/average-aum`: same shape — Select Data / Select Type / Select
  Mutual Fund / Select Financial Year / Select Period dropdowns + "Go". No
  "scheme-wise" mention anywhere on the page; terminology ("Select Mutual
  Fund") implies AMC-wise grain only. Page notes AAUM moved from monthly to
  **quarterly** upload cadence effective Q/E Dec 2010.
- `/aum-data/aum-disclosure`: same dropdown shape (Select Type, Select
  Financial Year, Go). No "scheme-wise" mention found in this fetch either —
  scheme-wise AAUM grain question stays open pending the live browser check
  in step 3.

Both pages require in-browser interaction (dropdown selection → Go) to reach
an actual file — there is no directly curl-able/templatable download URL to
probe further at the HTTP layer. Step 2/3 proceed as user-driven browser
downloads.

---

## Step 2 — TER acquisition (USER) — instructions issued

Page: `https://www.amfiindia.com/ter-of-mf-schemes` (form/selector, confirmed
step 1 — no consolidated all-AMC download exists).

Requested: 3 AMCs × 2 months = 6 files.
- Months: FY 2025-2026 / January (pre-Apr-2026 target: Jan 2026) and
  FY 2026-2027 / June (post-Apr-2026 target: Jun 2026).
- AMCs: large = HDFC Mutual Fund (fallback ICICI Prudential); mid = Kotak
  Mahindra Mutual Fund (fallback: user's choice); boutique = Samco Mutual
  Fund (fallback: user's choice).
- Fund Type/Category: requested "All"/default; user to report verbatim
  whatever the form actually forced.

User's browser downloads to a Windows folder (WSL2 session); user reported
the folder path + filenames, session copied via `/mnt/c/...` into
`~/foliolens-data/raw-ter-stage0/ter/`.

STATUS: **actual pull exceeded scope** — Claude for Chrome (2026-07-29/30)
downloaded 12 consecutive months × 3 AMCs (Aug 2025 → Jul 2026, the latter
marked `_partial`), not the 2 targeted months, then the Chrome session ended
without reporting dropdown selections or notes. Per user direction: inspect
the full set delivered rather than discard the extra months (see Step 4); log
the scope/process gap for the next acquisition round rather than re-pulling.

## Step 3 — AAUM acquisition (USER) — instructions issued

Page A: `https://www.amfiindia.com/aum-data/average-aum` — requested: latest
available AMC-wise Average AUM file (1 file), whatever the current
latest period is.

Scheme-wise probe (both `average-aum` and `aum-data/aum-disclosure`): user
asked to check the "Select Type" dropdown on each page specifically for a
"Scheme wise"/"Scheme-wise Average AUM" option. If present: download latest
period for it. If absent: user to report the verbatim list of options that
DO appear, as evidence for the negative finding.

STATUS: **partially delivered, probe answer lost** — no scheme-wise dropdown
finding was reported before the Chrome session disappeared; no file or note
records what "Select Type" actually offered. Logged as a gap in Step 4/5 —
answered incidentally by file inspection (see 4.4), but the *dropdown-option*
evidence itself is still missing and should be re-checked next round.

---

## Step 4 — inspection

Files landed: `~/foliolens-data/raw-ter-stage0/ter/` (36 `.xlsx`, HDFC/Kotak/
Samco × Aug 2025–Jul 2026, Jul marked `_partial`) and
`~/foliolens-data/raw-ter-stage0/aaum/` (12 per-AMC quarterly files + 3
"Industry" quarterly files, missing the Industry file for 202507-202509 —
unexplained gap, Chrome session gave no reason). All inspected read-only via
`openpyxl`/`pandas` in an ephemeral `uv run --with openpyxl` env (no repo
dependency added, no parquet touched). scheme_master.parquet used strictly
as a read-only join target.

### 4.1 TER — verbatim headers, pre- vs post-April-2026

All three AMCs break **exactly at April 2026** (202604), consistent across
HDFC/Kotak/Samco — no AMC leads or lags the switch.

Single sheet per workbook: `TER_Revised`. **15 columns**, one row per scheme
per **calendar day** (not trading day — row count for Aug 2025 HDFC = 106
codes × 31 days = 3286 exactly; row count = codes actually present each day,
so mid-month launches/exits shave the total below the full N×days product in
other months).

**Pre-April-2026 header** (verbatim, e.g. `TER_HDFC_202508.xlsx`):
```
NSDL Scheme Code | Scheme Name | Scheme Type | Scheme Category | TER Date |
Regular Plan - Base TER (%) |
Regular Plan - Additional expense as per Regulation 52(6A)(b) (%) |
Regular Plan - Additional expense as per Regulation 52(6A)(c) (%) |
Regular Plan - GST (%) | Regular Plan - Total TER (%) |
Direct Plan - Base TER (%) |
Direct Plan - Additional expense as per Regulation 52(6A)(b) (%) |
Direct Plan - Additional expense as per Regulation 52(6A)(c) (%) |
Direct Plan - GST (%) | Direct Plan - Total TER (%)
```

**Post-April-2026 header** (verbatim, e.g. `TER_HDFC_202604.xlsx`):
```
NSDL Scheme Code | Scheme Name | Scheme Type | Scheme Category | TER Date |
Regular Plan - Base Expense Ratio (BER) (%) |
Regular Plan - Brokerage cost (%) |
Regular Plan - Transaction Cost incurred for the purpose of execution of trade (%) |
Regular Plan - Statutory Levies (including GST) (%) |
Regular Plan - Total TER (%) |
Direct Plan - Base Expense Ratio (BER) (%) |
Direct Plan - Brokerage cost (%) |
Direct Plan - Transaction Cost incurred for the purpose of execution of trade (%) |
Direct Plan - Statutory Levies (including GST) (%) |
Direct Plan - Total TER (%)
```

Column **count is unchanged (15→15)**; only the 4 sub-columns per plan are
redefined. No column is literally named `Base TER` post-break — it's renamed
`Base Expense Ratio (BER) (%)`, matching `Total TER` as the one label that
survives both regimes unchanged.

**Anomaly not anticipated by the cloud report:** every file — including all
pre-break months back to Aug 2025 — carries an **identical 13-row footer
disclaimer** that already describes the **post-2026** methodology verbatim
("Base Expense Ratio (BER) as per Regulation 66(7)... Regulations, 2026",
"Brokerage Cost... Regulation 66(9)..."), even though that same file's column
headers use the pre-2026 terminology (`Base TER`, `Regulation 52(6A)`). The
footer is static boilerplate that doesn't describe the file it's attached to
for any pre-break month — **do not use the footer text to infer a file's
methodology; only the column headers are authoritative per file.**

`TER_*_202607_partial.xlsx`: confirmed genuinely partial — HDFC's file
carries data through **2026-07-28** (27 of 28 possible calendar days;
downloaded 2026-07-30, consistent with AMFI's normal disclosure lag). The
`_partial` label Chrome applied to the filename is accurate, not a Chrome
invention.

### 4.2 Row granularity — plan column-blocks, no option-level split

Checked exhaustively on Samco (small AMC, 11–13 schemes across the year,
includes hybrid/multi-asset funds that always carry IDCW-eligible categories
elsewhere in the universe): **zero** scheme names carry a Growth/IDCW
qualifier, and no scheme name maps to more than one `NSDL Scheme Code`. TER
is disclosed **once per scheme per day**, with Regular and Direct as parallel
column blocks — confirms the cloud report's `[INDEXED]` guess exactly:
**plan-level, not option-level.** No AMC in the sample splits options into
separate rows.

### 4.3 Key check — no amfi_code/ISIN in TER; name-match against scheme_master

No `amfi_code` or ISIN column anywhere in any TER file, in either regime. The
only identifier is `NSDL Scheme Code` (format
`<AMC>/O/<Type>/<Sub>/<YY>/<MM>/<Serial>`, e.g.
`HDFC/O/H/ARB/07/08/0017`) — a wholly different namespace from
`scheme_master.amfi_code`.

Sample of 5 TER scheme names checked for **exact** match against
`scheme_master.scheme_name` (7,913 rows):

| TER `Scheme Name` | Exact match | Notes |
|---|---|---|
| HDFC Arbitrage Fund | **0** | 261 fuzzy (substring) candidates — scheme_master always appends `- Regular/Direct Plan - Growth/IDCW Option` |
| Samco Overnight Fund | **0** | 23 fuzzy candidates |
| SAMCO ELSS TAX SAVER FUND | **0** | 23 fuzzy candidates |
| Samco Large Cap Fund | **0** | 23 fuzzy candidates |
| HDFC Dividend Yield Fund | **0** | 261 fuzzy candidates — bare name collides with "Dividend Yield" as a *category*, not an IDCW option flag |

**0/5 exact match**, confirmed as expected: TER names are bare fund names
with no plan/option suffix, so resolution requires normalised-name +
fund_house matching, fanning one TER row out to **every** `(plan × option)`
`amfi_code` under that fund/plan — exactly the cloud report's `[design
implication]` in §5, now confirmed against real files rather than indexed
guesses.

### 4.4 AAUM — grain findings (supersedes cloud report §4/§5)

Three distinct AAUM products were actually captured, and the grain picture is
**more resolved than either the runsheet or the cloud report anticipated**:

1. **`AUM-AAUM_Industry_<quarter>.xlsx`** (whole-market, category-level,
   quarterly) — one row per SEBI scheme category (`Overnight Fund`, `Liquid
   Fund`, ... `Total`), **no AMC and no scheme breakdown at all**. Matches
   the cloud report's "quarterly AUM Disclosure, scheme-category-wise"
   description closely. 3 of 4 quarters present (202504-202506,
   202510-202512, 202601-202603); **202507-202509 is missing** with no
   record of why — re-check in the next round whether it exists upstream or
   was simply not pulled.

2. **`AAUM_<AMC>_<quarter>.xlsx`** (per-AMC, selected via "Select Mutual
   Fund") — **this is genuinely scheme-wise AAUM**, carrying an actual
   **`AMFI Code`** column plus `Scheme NAV Name`, grouped by SEBI category
   within the AMC. Cross-checked 5 `(AMFI Code, Scheme NAV Name)` pairs from
   `AAUM_HDFC_202504-202506.xlsx` against `scheme_master.parquet` by
   `amfi_code`: **5/5 found, 5/5 exact `scheme_name` match** (e.g. `136090` →
   "HDFC Retirement Savings Fund - Equity Plan - Growth Option" in both
   files, verbatim). **This directly contradicts the cloud report's §4/§5
   claim that "AMFI does not publish AAUM at scheme (amfi_code) grain"** and
   that scheme-level AAUM exists "only on individual AMC's own statutory-
   disclosure pages" — it is available on AMFI's own central
   `/aum-data/average-aum` page, just gated behind a per-AMC selection
   rather than offered as one consolidated cross-AMC file.

3. **Cadence correction**: the cloud report characterised `average-aum` as
   "Monthly Average AUM (AMC-wise)". Every file actually pulled from that
   page — including the per-AMC scheme-wise ones — is labelled **quarterly**
   ("...for the quarter of April - June 2025..."), matching the page's own
   static text found in Step 1 ("AAUM is uploaded on AMFI Website on
   quarterly basis" since Q/E Dec 2010). The cloud report's monthly-AMC-wise
   characterisation appears to be **stale/incorrect indexed information**,
   not a live-file finding — there is no evidence a monthly cadence exists
   on this page today.

4. **Scheme-wise dropdown probe**: the Step 3 explicit ask (search "Select
   Type" for a literal "Scheme wise" option) was **never answered** — Chrome
   disappeared before reporting it. Finding #2 above answers the
   *substantive* question (scheme-wise AAUM is obtainable, via AMC
   selection) but the **dropdown-label evidence itself is a genuine gap**;
   re-run that specific check next round.

**AAUM grain verdict**: scheme-level (`amfi_code`) AAUM is sourceable from
AMFI's central page, contra the cloud report — but only **one AMC at a
time**, no all-AMC consolidated scheme-wise file was found or is implied to
exist. A full universe pull is a per-AMC loop (same shape as TER
acquisition), not a single download. The whole-industry category file (#1)
remains the only true single-file product, and it stays at category grain.

### 4.5 Deltas vs. the cloud `[INDEXED]` report — item by item

| Cloud report claim (`[INDEXED]`) | Local finding | Verdict |
|---|---|---|
| TER keys on scheme name only, no amfi_code/ISIN | Confirmed exactly (`NSDL Scheme Code`, bare names) | **Confirmed** |
| Pre-2026 header shape (`Base TER`/52(6A)(b)/(c)/GST/Total TER) | Verbatim match, plus 5 columns the cloud report didn't have (`NSDL Scheme Code`, `Scheme Type`, `Scheme Category`, `TER Date`) since it couldn't see the real file | **Confirmed + extended** |
| Post-2026 header is BER + broken-out levies, exact shape unobservable | Verbatim match: BER / Brokerage cost / Transaction Cost / Statutory Levies / Total TER | **Confirmed** |
| One row per scheme, plan-level not option-level (flagged "confirm at Stage 1") | Confirmed, incl. an IDCW-heavy AMC (Samco) | **Confirmed** |
| No consolidated all-industry TER file; per-AMC/date form navigation | Confirmed — form/selector page, no static links | **Confirmed** |
| AAUM not sourceable at amfi_code grain from a central AMFI file; scheme-level only via individual AMCs' own pages | **Contradicted** — central `/aum-data/average-aum` page yields scheme-wise AAUM with `amfi_code` when a specific AMC is selected; 5/5 exact match to scheme_master | **Overturned** |
| `average-aum` page is monthly, AMC-wise | **Contradicted** — every file pulled is quarterly; page's own text confirms quarterly cadence since 2010 | **Overturned** |
| Quarterly category-wise AAUM disclosure exists, whole-market | Confirmed (`AUM-AAUM_Industry_*` files) | **Confirmed** |
| TER disclosed at some cadence finer than monthly ("pick a consistent as-of day") | Confirmed as literally **daily** (one row per scheme per calendar day) | **Confirmed + precise** |
| Footer/disclaimer text describes the file's own regime | Not addressed by cloud report (couldn't see real files) | **New finding**: footer is static, always post-2026 language, unreliable as a per-file methodology signal |

---

## Step 5 — report + STOP

**HTTP behaviour**: no bot-gating observed on any of the 3 AMFI pages; both
are Next.js form/selector pages requiring browser interaction — no
templatable download URL exists to probe further.

**Acquisition notes**: TER and (per-AMC) AAUM both require a per-AMC
navigation loop, no consolidated cross-AMC file for either. Actual
acquisition (Claude for Chrome) substantially over-delivered scope (12
months vs. 2 requested) and under-delivered process notes (dropdown
selections, scheme-wise probe answer both lost when the session ended
ungracefully) — a process gap for how browser-automation downloads are
supervised next time, not a data-quality issue.

**Verbatim headers**: see 4.1 (TER pre/post) and 4.4 (AAUM, 2 distinct
per-file shapes: whole-industry category rows vs. per-AMC `amfi_code` +
scheme-name rows).

**Granularity findings**: TER = daily, per-scheme, plan-level (Regular/Direct
columns), no option split. AAUM = quarterly; either whole-industry
category-level (no AMC/scheme) or per-AMC scheme-level (with `amfi_code`),
depending on the "Select Mutual Fund" choice — no single file spans both
dimensions.

**AAUM grain verdict**: scheme-level AAUM **is** sourceable from AMFI's
central page (overturning the cloud report), but only per-AMC — a full
universe scheme-wise AAUM pull is a per-AMC loop, same acquisition shape as
TER, not a one-shot download.

**Deltas vs. `[INDEXED]`**: see 4.5 table — 6 confirmed, 2 overturned
(central-page scheme-wise AAUM existing at all; its cadence), 1 new finding
(stale-footer anomaly) not previously visible.

**Open questions for stage 1**:
- Re-run the literal "Select Type" scheme-wise dropdown-label check on both
  AAUM pages (lost this round) — needed to know if there's a labeled
  scheme-wise *product* vs. the incidental per-AMC grain found here.
- Confirm whether the missing `AUM-AAUM_Industry_202507-202509` file exists
  upstream at all.
- Decide the AAUM ingestion shape given per-AMC-only scheme grain: loop all
  ~50+ AMCs quarterly (matches TER's acquisition shape), or accept
  category-level grain from the single whole-industry file and drop the
  manifest's `amfi_code` AAUM ambition.
- TER name→`amfi_code` resolver: confirm the normalisation rules already in
  `scheme_master.py` are sufficient for the fan-out (fund name → all
  plan×option codes), or whether the `portal.amfiindia.com` scheme-code/ISIN
  bridge the cloud report flagged is still needed.
- Decide whether to keep or discard the 10 extra TER months per AMC already
  on disk (currently sitting in `~/foliolens-data/raw-ter-stage0/`, well
  past the 2-month stage-0 scope) before stage 1 fixture selection.

**STATUS: `OBSERVED`.** Stage 0 remains terminal — no parser code, schema, or
fixtures were written; `scheme_master.parquet` was read-only throughout.
Stage 1 proceeds only after review of this report.
