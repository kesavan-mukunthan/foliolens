# F-TER Stage 0 — TER + AAUM source verification report

*Manifest: F-TER (TER + AAUM ingest). Stage 0 is a **terminal gate**: report and
STOP; no parser code. Parser design is confirmed against this report before
Stage 1. Date: 2026-07-29. Author venue: cloud sandbox.*

---

## 0. TL;DR (the two decisions this gate forces)

1. **Acquisition cannot happen in this cloud sandbox.** All outbound HTTP to the
   open internet is denied at the organisation egress policy — not by AMFI. This
   was verified against `amfiindia.com`, `portal.amfiindia.com`, `huggingface.co`,
   `en.wikipedia.org`, and `example.com` (all blocked). **No AMFI file was
   fetched, and AMFI's own bot-protection behaviour could not be observed** (no
   egress path reaches it). → **Stage 2's venue — and even Stage 1's fixture
   *acquisition* — must be a local / egress-capable machine (the WSL2 build host),
   consistent with SCOPE.md's "Acquisition-aid amendment" (one-time locally-run /
   browser-extension-driven downloads permitted).** Stage 1 *parser development*
   can still run in cloud once the fixtures are committed.

2. **Two schema-critical realities differ from the manifest sketch and must be
   settled before Stage 1 code:**
   - **TER files key on *scheme name*, not `amfi_code` or ISIN.** The disclosure
     workbook carries no scheme code. Name resolution is therefore not a 1:1 join
     but **1 disclosure row → many `amfi_code`s** (one scheme name × {Regular,
     Direct} plan columns → the fund's plan/option code set). This is the real
     work the manifest anticipated, and it is bigger than a lookup.
   - **AMFI does not publish AAUM at scheme (`amfi_code`) grain.** The central
     AMFI AAUM products are **AMC-wise** (monthly) and **scheme-category-wise**
     (quarterly). Scheme-level AAUM exists only on *individual AMC* statutory-
     disclosure pages, each in its own format. The manifest's
     `aaum.parquet (amfi_code, period, aaum)` grain is **not sourceable from a
     single AMFI file** — this needs an explicit grain/venue decision (see §5).

> **Confidence convention used below.** `[OBSERVED]` = directly established in
> this session (HTTP behaviour, proxy logs). `[INDEXED]` = reconstructed from
> WebSearch's indexed snippets / third-party descriptions — *planning-grade, not
> verified against a live file*; every `[INDEXED]` claim is a Stage-1
> confirm-against-real-file item. Nothing below the HTTP section was seen in a
> real AMFI file, because none could be fetched.

---

## 1. Fetch / HTTP behaviour from the sandbox IP  `[OBSERVED]`

The manifest asks to "record HTTP behaviour, not just success/failure," as a
bot-protection check. Findings:

| Path | Target(s) | Result |
|---|---|---|
| `curl` via `$HTTPS_PROXY` | `www.amfiindia.com:443`, `portal.amfiindia.com:443`, a static `/uploads/*.pdf` | **HTTP 403 to the CONNECT tunnel** — `curl: (56) CONNECT tunnel failed, response 403`. Recorded server-side in the proxy status endpoint as `connect_rejected` / "gateway answered 403 to CONNECT (policy denial or upstream failure)". |
| `curl` via `$HTTPS_PROXY` | `huggingface.co:443` | Same `connect_rejected` 403. |
| `WebFetch` (Anthropic infra) | `amfiindia.com` pages, `huggingface.co`, `cafemutual.com`, **`en.wikipedia.org`, `example.com`** | **HTTP 403 for every host, including universally-permissive ones.** |
| `WebSearch` | (indexed backend) | **Works** — the only functioning channel; all of §2–§5 comes from it. |

**Interpretation (important for accuracy):** because even `example.com` and
Wikipedia return 403 through WebFetch, the 403 is the **organisation egress
wall**, *not* destination-specific bot protection. The `curl` failures are the
same wall at the CONNECT layer (confirmed in the proxy's own
`recentRelayFailures` log). Per the proxy README, org policy denials (403/407)
must be reported, not routed around — done here.

**Consequence:** the three real files could not be fetched, so the "verbatim
column headers of all three files" the manifest asks for **cannot be captured in
this venue**. §2–§4 give the best indexed reconstruction with explicit caveats;
Stage 1 must re-capture the real headers from a local download. Whether AMFI
itself applies Cloudflare / UA-filtering / rate-limiting is **unknown and
untestable from here** — do not assume either way; probe it during local
acquisition.

---

## 2. TER disclosure — URLs, structure, format  `[INDEXED]`

### URLs
- **Landing page:** `https://www.amfiindia.com/ter-of-mf-schemes`
- **SIF TER (separate product, out of scope but noted):**
  `https://www.amfiindia.com/sif/ter-of-sif`
- **Supporting master for name resolution (see §5):** the AMFI NAV-history /
  scheme-code portal `http://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx`
  and `https://www.amfiindia.com/otherdata/scheme-details` expose
  `scheme_code / scheme_name / ISIN` — the join key the TER file lacks.

### Structure: **portal-navigation-dependent, per-AMC — NOT a predictable
per-month URL.**
The disclosure is a form: **select fund house (AMC) → then scheme → then date**,
which yields a downloadable spreadsheet. There is **no evidence of a single
consolidated all-industry file**, and no evidence of a stable
`.../TER_YYYY_MM.xlsx`-style monthly URL. Indexed descriptions state each AMC
publishes **one workbook per month, one sheet per scheme**. → The parser cannot
assume a URL template; acquisition is a navigation loop over AMCs (and the daily-
disclosure requirement means a *date* selection too — TER is disclosed daily,
though the manifest wants a monthly cadence, so pick a consistent as-of day).

### Format
- **xlsx** (downloadable spreadsheet). `[INDEXED]` — confirm at Stage 1.
- **Per-AMC, not consolidated.** One workbook per AMC per period.

### Column headers (pre-April-2026 "old all-in" regime)  `[INDEXED — verify]`
Reconstructed from indexed third-party descriptions and a public mirror dataset
(`Na-Rajan/IndianMutualFundsTER`). Per-plan blocks laid **side-by-side as
columns**, one row per scheme:

```
Scheme Name
Regular Plan - Base TER (%)
Regular Plan - Additional expense as per Regulation 52(6A)(b) (%)
Regular Plan - Additional expense as per Regulation 52(6A)(c) (%)
Regular Plan - GST (%)
Regular Plan - Total TER (%)
Direct Plan  - Base TER (%)
Direct Plan  - Additional expense as per Regulation 52(6A)(b) (%)
Direct Plan  - Additional expense as per Regulation 52(6A)(c) (%)
Direct Plan  - GST (%)
Direct Plan  - Total TER (%)
```
plus an effective-date/as-of field. **No `amfi_code`, no ISIN column** in the
disclosure workbook itself (keys on **Scheme Name only**).

### Row granularity  `[INDEXED — verify]`
- **One row per *scheme*, with Regular and Direct as parallel column blocks**
  (not separate rows).
- **Growth vs IDCW:** TER is a **plan-level** figure, not option-level, so a
  single row typically covers all options under a plan. **Confirm at Stage 1**
  whether any AMC splits options into separate rows (it changes the row→code
  fan-out in §5).

---

## 3. TER regime break (April 2026) — the format-drift question  `[INDEXED]`

**The regime break is real and dated.** SEBI (Mutual Funds) Regulations, 2026
took effect **1 April 2026**. The expense framework changed materially:

- **TER → BER rename.** The regulated cap is now the **Base Expense Ratio (BER)**
  = the AMC's fund-management fee **excluding all statutory/regulatory levies**.
- **Levies "on actuals."** STT/CTT, GST, stamp duty, SEBI fees, exchange fees are
  now charged **on actuals**, over and above brokerage limits.
- **New identity:** `Total TER = BER + Brokerage + Regulatory levies + Statutory
  levies`.

**Drift implications for the parser:**
1. The **column set will differ** post-April-2026 (BER + broken-out levies rather
   than the old `Base TER / 52(6A)(b) / 52(6A)(c) / GST / Total TER`). The exact
   new headers are **not observable from here** and are the single most important
   Stage-1 confirm-against-real-file item.
2. **`Base TER` (pre-2026) ≠ `BER` (post-2026).** They are *different definitions*
   (old Base TER excludes additional expenses & GST but is not the regulatory BER
   base). **Do not map pre-2026 `Base TER` onto the schema `ber` column** — that
   would be a definitional error. The manifest's choice to carry **`total_ter`
   only** for pre-2026 rows is the safe one and is endorsed here. This also
   reinforces keeping **BER-vs-total-TER as an explicitly open question** in the
   spec.
3. The parser's **format-dispatch on observed headers** (manifest requirement) is
   the correct design: pre-regime headers → old shape; post-regime headers → new
   shape; neither → **fail loud with the headers it saw**.

**Schema check against manifest sketch** (`ter.parquet →
(amfi_code, month, regime, ber, statutory_levies, total_ter)`): conceptually
compatible with the post-2026 disclosure, but **the observed post-2026 file
wins** — if the disclosed split is finer/coarser (e.g. brokerage broken out
separately, or levies not itemised), adjust the schema and record why in the
schema note. Pre-2026 rows: `total_ter` populated; `ber`/`statutory_levies`
NULL.

---

## 4. AAUM disclosure — URLs, structure, format  `[INDEXED]`

### URLs
- **Monthly "Average AUM" (AMC-wise):**
  `https://www.amfiindia.com/aum-data/average-aum`
- **Quarterly "AUM – AAUM Disclosure" (scheme-category-wise):**
  `https://www.amfiindia.com/aum-data/aum-disclosure`
- **State/geography-wise AAUM:** `https://www.amfiindia.com/geographical-spreads`

### Structure & granularity — **not scheme-level**
- **Monthly "Average AUM"** is **AMC-wise** — one row per Mutual Fund (AMC).
  Indexed column shape: `Mutual Fund Name`, `Average AUM (excl. FoF-Domestic but
  incl. FoF-Overseas)`, `Average AUM (FoF-Domestic only)`; period = month. Form-
  driven (select financial year). **No `amfi_code`.**
- **Quarterly "AUM Disclosure"** is **scheme-category-wise** (Liquid / Debt /
  Equity / ELSS / Hybrid / Index / …) with `AUM as on last day of quarter (Lacs)`,
  `Average AUM for the quarter (Lacs)`, geography split, `% of total`. **No
  `amfi_code`.**
- **Scheme-level AAUM (per `amfi_code`)** is published **only by individual AMCs**
  on their own statutory-disclosure pages (e.g. UTI "AUM Disclosure Scheme-Wise
  (Monthly Average)", Nippon, ABSL, PPFAS), each **its own heterogeneous format**.

### Format
- **xlsx** (downloadable spreadsheet), form-driven per financial year. `[INDEXED]`

---

## 5. Name resolution & the AAUM grain problem (the manifest's "real work")

### TER row → `amfi_code` (fan-out, not 1:1)  `[design implication]`
Because the TER file carries **Scheme Name only** at **scheme × plan** grain, and
`scheme_master.parquet` keys on `amfi_code` at **plan × option** grain
(`src/foliolens/ingest/scheme_master.py`), resolution is:

```
TER row (scheme name) ─┬─ Regular Plan columns ─→ all amfi_codes for that fund with plan=regular
                       └─ Direct  Plan columns ─→ all amfi_codes for that fund with plan=direct
                                                   (same TER applied across growth/IDCW options
                                                    under the plan, pending §2 row-granularity check)
```

The tiered matcher the manifest specifies is right:
- **exact** scheme-name match → fund's code set;
- **normalised** match second (the scheme_master already normalises
  case/punctuation/plan/option tokens — reuse those rules; list them in the module
  docstring, deterministic only);
- **everything else → `unresolved_ter_<month>.csv`** for human review; never
  fuzzy-match silently into a figure of record.
- Resolution stats `(matched / normalised / unresolved)` are a tested return
  value.

Note the extra wrinkle vs the manifest sketch: the join is **name → set-of-codes**
(fund → many share classes), and the Regular/Direct split in the file maps to the
`plan` field, so the fan-out is deterministic given a correct name match. The
`portal.amfiindia.com` scheme-code/ISIN master (§2) is the bridge if name-only
matching proves too lossy — worth pulling as a resolution aid.

### AAUM grain — **decision required before Stage 1**
`aaum.parquet (amfi_code, period, aaum)` cannot be filled from a central AMFI
file. Options, in order of increasing cost:
- **(A) Re-grain to what AMFI actually publishes:** `aaum.parquet
  (amc_id | scheme_category, period, aaum)` from the monthly AMC-wise or quarterly
  category-wise file. Cheap, central, single-writer-clean — but **not scheme
  level**, so it can't feed a per-`amfi_code` selection metric directly.
- **(B) Per-AMC scheme-level scrape** to hit the `amfi_code` grain. Matches the
  manifest schema but is a **much larger, heterogeneous, per-AMC-format** job
  (dozens of distinct layouts) and is squarely a **local-venue** effort.
- The "recent AAUM drop" the manifest wanted fetched is the AMFI **monthly AMC-
  wise** file — which by itself **does not carry `amfi_code`**. So the AAUM leg of
  the manifest needs a scope call, not just a parser.

---

## 6. Spec §ter items to record (for Stage 1, when the spec section lands)
- The **April-2026 regime break** and the resulting **series discontinuity** in
  TER (old all-in `Total TER` vs new `BER + levies-on-actuals`); the two are not
  a continuous series and must be tagged `regime`.
- **Within-month cross-sectional ranking** guidance for the cheapest-expense-
  quartile methodology stream: rank on a **like-for-like** basis — post-April-2026,
  rank on `total_ter` reconstructed as `BER + levies`, or on `BER` alone, but
  **never mix a pre-2026 `Total TER` against a post-2026 `BER`** in one ranking.
- **BER-vs-total-TER** left **explicitly open**.
- **AAUM grain** (§5) left explicitly open pending the (A)/(B) decision.

---

## 7. STOP

Per the manifest, Stage 0 is terminal. **No parser code, schema, or fixtures were
written.** Parser design and the two open decisions (acquisition venue; AAUM
grain) should be confirmed against this report before Stage 1 begins. The
concrete Stage-1 preconditions this report surfaces:
1. Acquire the three real files from an **egress-capable local machine**, then
   commit small excerpts as fixtures.
2. Capture the **real** column headers of all three (esp. the **post-April-2026
   BER** file — unobservable here).
3. Settle the **AAUM grain** decision.
