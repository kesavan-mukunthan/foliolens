# FolioLens — Scope Brief for Planning

*Revised (rev 2 — step-0 spec session). Supersedes prior versions. Source of truth for build order, design decisions, and open questions.*

## What is FolioLens

A multi-agent, finance-domain system for fund selection and monitoring. Built as both a learning vehicle (threads through an 8-week GenAI curriculum) and a consumer-facing product for Indian mutual fund investors. Not a production trading system.

**Data sources.** NAV and scheme metadata come from **mftool** (a Python wrapper over AMFI), now the canonical source — not mfapi.in. mftool/AMFI provides **NAV and scheme metadata only**. Holdings, benchmark returns (TRI), benchmark constituents, expense ratios, and AUM are **not available from this source** and must be sourced separately (see Unsourced Data).

## Business Problem

Four questions the system answers:

1. **What data do I have?** — build the analytical foundation
2. **Which funds should I invest in?** — selection and screening
3. **Are my current holdings still doing what I expect?** — ongoing monitoring
4. **Why is this happening, and what should I do?** — insight and commentary

## Consumer Architecture

**Layer 1 — no onboarding required.** Fund screener and recommender over the mftool universe. Usable by any consumer without uploading personal data.

**Layer 2 — portfolio required.** Personalised monitoring, attribution, portfolio construction, personal finance integration. Gated behind CAS upload (CAMS/KFintech) or MFCentral QR pull. Onboarding mechanism deferred. The transactional (OLTP) store enters here.

## Working Model (build process)

- **Project (Claude.ai) = decisions and specs.** Strategic reasoning, design, sequencing, financial method, review of output. A session ends in a committed spec or a recorded decision.
- **Claude Code = construction.** Implementation against a spec, running, testing, committing.
- **Default executor: Claude Code on Sonnet 4.6.** Haiku-safe for mechanical sub-steps (fetch, land, report); Sonnet for convention-sensitive logic (resampling, return math, reconciliation).
- **Bridge artifacts in the repo:** `CLAUDE.md` (standing conventions + invariants, auto-loaded each session), `SCOPE.md` (this brief, amended here and propagated), `specs/step-NN-*.md` (per-step handoffs with acceptance criteria), `tests/` (standing invariants encoded as tests; the acceptance gate).
- **Every step gates on a green test suite.** Standing correctness laws live in `CLAUDE.md` and are enforced as tests in `tests/invariants/`; step specs add fixture-bound acceptance in `tests/step-NN/`. "Honour the convention" is not the gate — a green test is.
- **Per-step rhythm:** design here → spec committed → build in Claude Code → review here → update brief if a decision changed.
- **Mobile = design/review here; desktop = Claude Code execution.** For curriculum-aligned steps (RAG, LangGraph, MCP, evals), Claude Code scaffolds and reviews rather than autocompletes, to preserve learning.

## Build Order

Start with the return engine on known funds to validate metric logic before any personal data or scaling.

0. **Return engine, validated on known sample funds** — NAV→returns, conventions, three-way validation (own impl, ffn/empyrical, published figures), pytest gate, and an Excel validation report for eyeballing. Reference set spans equity categories + short-duration debt + liquid + **FoF + multi-asset**, with one fund paired direct+regular. *(spec-00; CAS / step-1 split out separately)*
1. Parse personal portfolio from CAS via **casparser** (CAMS/KFintech; provides ISIN→AMFI mapping and 112A capital-gains)
2. Build metric layer on personal funds — returns (on the validated engine), Sharpe, drawdown
3. Basic monitoring on personal holdings *(first deploy)*
4. Extend to full universe (mftool ingestion + stored NAV base)
5. Relative monitoring — peer comparison, universe-relative alerts *(second deploy)*
6. Fund screener
7. Fund recommender *(third deploy — Layer 1 consumer product complete)*
8. Natural language interface — query, commentary generation, RAG
9. Factor analysis — returns-based and holdings-based *(Phase 2, optional; returns-based Carhart 4-factor now unblocked for equity categories via IIM-A library; holdings-based requires holdings + security master + stock characteristics — all three must be operational)*
   - *Parallel track (start anytime):* Holdings forward append job, security master build, current stock characteristics from NSE. These are data infrastructure, not a numbered step — run alongside the main build so data accumulates. Sector/market-cap visualisation per fund is unlocked once this track is complete.
10. Portfolio construction *(fourth deploy)*
11. Personal finance integration

## Key Design Decisions

**Sequencing**
- **Return engine first, on known funds**, ahead of CAS — validate the keystone calc before personal data or scale.
- Personal portfolio before universe — avoids upfront volume; validates on known funds.
- Screener and recommender are universe features, not personal features — no upload required.
- Deploy incrementally — after steps 3, 5, 7, 10.
- **Every build step gates on a green test suite** — standing invariants in `CLAUDE.md`/`tests/invariants/`, step-specific acceptance in the spec and `tests/step-NN/`.
- Factor analysis is Phase 2. Returns-based Carhart 4-factor is now unblocked for equity categories (IIM-A library). Holdings-based Brinson requires three layers: holdings (forward append starts now), security master, and stock characteristics — treat as a parallel data infrastructure track, not a gated step.
  - Holdings visualisation (sector treemap, market-cap bucket bar per fund) unlocks as soon as holdings append + security master + current NSE characteristics are operational.
- Consumer onboarding deferred — CAS email vs MFCentral QR, decide at Layer 2.

**Data model**
- **Two-level schema: Fund and ShareClass.** Fund = the strategy (one portfolio, one benchmark; holdings and category attach here). ShareClass = one AMFI code (`amfi_code`), carrying plan × option, NAV, expense ratio, ISIN. Regular/direct handling is a **share-class pairing under one Fund** — pair regular-growth with direct-growth to compute expense drag and breakeven (a taxable event; LTCG with 31-Jan-2018 grandfathering must be factored). Fund grouping is derived by parsing names/ISINs (fragile; tested, with a manual-override hook).
- **Numeric types by role:** `Decimal`/`decimal128` on the path of record (NAVs, reconciled metrics, cost basis, cashflows); `float64` for analytical return series and bulk vectorised compute. Convert once at materialisation.
- Cost basis stored at transaction grain (lot-level FIFO + grandfathering), never derived loosely.
- Tenancy key and PII segregation from day one, even with a single user.

**Return engine**
- **Growth-option NAV** is the return basis (IDCW NAVs misstate total return). Regular/direct comparison = regular-growth vs direct-growth.
- **`ReturnSource` protocol** — Fund, ShareClass, Portfolio, Benchmark all supply `value_series` + `cashflows`; returns/risk implemented once on top. TWR is the default; MWR/XIRR where cashflows exist. Risk metrics (Sharpe/drawdown/vol) are protocol surface only until step 2.
- **Month-end is the base**; daily only for intra-month. Universe metrics materialised at month-end; personal funds may compute daily. Step 0 stores daily as the raw base and validates point-to-point. Monthly return series is the materialised analytical layer (float64, month-end to month-end); daily returns are derived on demand, not stored; trailing CAGRs are Decimal figures of record.
- **Conversion seam:** `returns/convert.py` holds the boundary-crossing free functions — `simple_return(start,end)->float`, `to_returns(NavSeries)->ReturnSeries` (the single Decimal→float cast-at-birth), `to_index(ReturnSeries)->ValueIndex`. ReturnSeries is float64-backed with a Decimal base; ValueIndex (float levels) is distinct from NavSeries. The scalar `period_return->ReturnResult` path stays Decimal and does not route through the series.
- Conventions (in `CLAUDE.md`): month-end NAV = last available on/before calendar month-end; SEBI annualisation (absolute < 1Y, CAGR ≥ 1Y); **day-count = actual_days / 365 (AMFI)**; declare periodicity to ffn/empyrical.
- **Validation:** three-way (own impl vs ffn/empyrical oracle vs published). Tolerances are fixed constants, never loosened at runtime to pass — own↔oracle relative ≤ 1e-6; own/oracle↔published ≤ 10 bps after matching the published as-of. Out-of-tolerance fails loud. **Published leg = the AMC factsheet at a common month-end as-of**; aggregators (Value Research / Morningstar) are cross-checks only.
- **Reuse, don't reimplement:** ffn / empyrical-reloaded (+ pyxirr once cashflows exist) as the production calc and/or validation oracle.

**Storage**
- **OLAP analytical store:** raw NAV lands in GCS → partitioned parquet on GCS as source of truth → DuckDB as a stateless query engine. NAV is the raw base; returns/metrics are a derived, materialised layer. Analytics read stored NAV, **never mftool at read time**.
- **Step 0 runs on local parquet behind a single `DataAccess` read seam; GCS swaps in at step 4** by repointing the seam (local path → `gs://`). No other module reads parquet paths directly. NAV stored as `decimal128` (DuckDB `DECIMAL(18,6)`), round-tripping without a DOUBLE cast.
- **Single-writer pattern:** a scheduled ingestion Job writes; read-only query instances pick up refreshed parquet (Cloud Run autoscaling can't share a writable DuckDB file).
- **Daily update:** Cloud Run Job, business days, after AMFI publishes; **upsert keyed `(code, date)`** (absorbs revisions), short lookback for late-publishing funds, holiday no-op, staleness alarm.
- **OLTP store (Postgres):** agent checkpoints, accounts, query logs — enters at Layer 2 / step 8, not before.
- **Return materialisation:** NAVs and reconciled trailing metrics as `decimal128`/Decimal; **monthly return series stored as `float64`** for factor/regression analytics; daily returns derived on demand from stored daily NAV. The monthly panel stores completed months only and is immutable once written; the current in-progress month is derived on demand, never stored. Provenance stamp: each scheme's panel carries a single hash over its month-end NAV inputs + the code/convention version; a hash mismatch triggers a full recompute of that scheme's panel (one regeneration job). Daily NAV appends don't feed a completed month, so they don't trip the stamp.

**Reporting**
- **Excel/CSV exports and factsheet links are one-directional review surfaces** for eyeballing — never authoritative, never read back into the pipeline. Stored parquet, computed metrics, and recorded fixtures are the source of truth. Excel display: NAV 4dp, returns as % 2dp; failures highlighted; metadata tab carries the amfi_code → isin → option/plan → factsheet provenance.

**GenAI layer (step 8)**
- **Route quantitative queries to SQL/metrics, qualitative to RAG.** Never read a figure off a PDF when the authoritative number is computed.
- Document corpus (SID/KIM/SAI/factsheets) is **date-versioned**; retrieval respects as-of. pgvector (on the step-8 Postgres) is the candidate vector store; verify before committing.

## Technical Constraints

- Infrastructure: GCP Cloud Run, Docker, GitHub Actions CI/CD. Postgres (OLTP) from Layer 2. (No Docker/CI at step 0 — local only.)
- Data source: **mftool** (AMFI) for NAV + metadata.
- Libraries (reuse): **casparser** (CAS, MIT — stay on the pdfminer path to avoid AGPL), **mftool** (NAV), **ffn / empyrical-reloaded** (returns/risk; the original empyrical is archived), **pyxirr** (XIRR/MWR — deferred until cashflows exist, step 1+), **pytest** (test gate), **xlsxwriter** (Excel reports). `hypothesis` optional for property-based invariant tests.
- Orchestration: LangGraph (primary); Google ADK evaluated in Week 5.
- Storage: parquet-on-GCS as source of truth, DuckDB analytical query engine; pgvector candidate for RAG.
- Builder: ~45-minute mobile sessions; scope build steps accordingly.
- Python primary; limited C#/C++.

## Unsourced Data (gaps to close)

None of the following come from mftool/AMFI:

- **Expense ratio** — needed for the step-3 regular/direct breakeven. **Sequencing conflict:** source separately before step 3, or descope breakeven from the first deploy. *Needs a decision.*
- **Holdings** — two distinct problems with different effort and timelines:
  - *Forward append (start now, parallel to main build):* AMFI mandates monthly portfolio disclosure within 30 days of month-end; parseable from AMFI's disclosure page. Implement as a scheduled Cloud Run Job alongside the NAV ingestion job. Storage: parquet on GCS partitioned by `fund_code/year/month`; columns: `fund_code`, `as_of_date` (portfolio date), `disclosure_date` (publication date), `isin`, `security_name`, `asset_type`, `market_value_cr`, `pct_of_nav`, `quantity`, `source_url`.
  - *Historical backfill (assess before building):* Depth of machine-readable AMFI history is unknown. AMC websites are inconsistent (PDF/HTML/XLS varies by fund house and vintage). Dead/merged fund holdings are unlikely to be archived — the survivorship-bias problem is worst here. **Do not build a backfill scraper without first checking AMFI portal depth and verifying mstarpy India coverage and terms.**
  - Both tiers block holdings-based Brinson attribution. Factor-based Carhart (already sourced via IIM-A) remains the primary tool for Phase 3 validation regardless.

- **Security master** — prerequisite for all holdings-based analysis and stock-level visualisation. Maps `ISIN → NSE ticker → stock characteristics`. Sources: NSDL ISIN database (authoritative); NSE publishes a daily symbol-ISIN map. One-time build with incremental updates for new listings/delistings/corporate actions. Must exist before any characteristic enrichment of holdings can run. Dependency: holdings parser → ISIN extraction → security master join → downstream use.

- **Stock characteristics** — needed for per-fund sector/market-cap visualisation and (eventually) Brinson attribution. Two tiers with different data requirements:
  - *Current characteristics (visualisation — start after security master):* Sector (NSE/SEBI classification) and market-cap bucket (large/mid/small/micro by SEBI thresholds) from NSE sector master and daily bhavcopy. Free and reliable. P/E and P/B from yfinance — workable for large caps, degrades for mid/small. Applying today's characteristics to 30-day-lagged holdings is defensible for visualisation; label as-of date explicitly.
  - *Historical point-in-time characteristics (Brinson attribution — defer):* Sector and market-cap classification as of each historical disclosure date. Materially harder than current lookup; requires per-stock historical snapshots. Defer until holdings backfill depth is confirmed and Brinson is confirmed as the attribution path over factor-based.
- **Benchmark TRI returns** and **benchmark constituents** — block relative monitoring (step 5) and returns-based factor analysis.
- **AUM** — needed for size-based universe analysis.

**Candidate (unverified):** Morningstar via **mstarpy** exposes total-return series and holdings; India coverage, AMFI-code matching, and terms of use must be verified before relying on it.

**Sourced (step 9, equity categories only):** Returns-based Carhart 4-factor attribution for equity funds has a confirmed data source. The **IIM-A Indian Factor Library** (Agarwalla, Jacob & Varma) provides monthly MRP, SMB, HML, and WML factor returns for the Indian equity market from January 1994 to present (updated monthly to December 2025 as of this writing).
- URL: `https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/`
- Factors: market risk premium (MRP = Rm − Rf, using 91-day T-bill), size (SMB), value (HML), momentum (WML). Daily and yearly series also available; monthly is the relevant frequency for fund regression.
- India-specific methodology: big/small breakpoint at 90th percentile (not median); portfolio formation in September (not June — Indian fiscal year ends March); survivorship-bias correction applied (3,184 vanishing firms; correction effect is trivial, <0.2% on factor returns).
- Key empirical priors for the framework: WML dominates (mean ~17% pa); HML is meaningful (~11% pa); SMB is negative over the full history (–3% pa) — small-cap excess return in India comes from stock selection, not the size factor itself.
- **Scope boundary:** applies to equity fund categories only (large cap, mid cap, small cap, flexi cap, multi cap, value/contra, ELSS). Do not apply to debt, hybrid, or liquid funds.
- SMB–HML correlation is 37% (higher than US norms) — factor loading estimates will have wider confidence intervals; focus on residual alpha t-stat, not individual beta magnitudes.

## Learning Alignment

| Step | Curriculum week |
|------|----------------|
| 0–2 | Data engineering foundations (parallel activity) |
| 3 | Week 3 — RAG and retrieval patterns |
| 4–5 | Week 2 — embeddings; Week 4 — LangGraph agents |
| 6–7 | Week 6 — MCP; Week 7 — evals |
| 8 | Week 8 — multi-agent capstone |
| 9 | Phase 2 — MLE block |

## Open Questions

**Resolved**
- CAS parser structure → casparser. Step-2 minimum metrics → returns first, then Sharpe/drawdown/vol. DuckDB schema → Fund/ShareClass + NavPoint/Transaction/Lot/Position/materialised metrics on parquet-GCS.
- **Step-0 task breakdown → spec-00** (CAS / step-1 split out separately).
- **Execution model** → Claude Code on Sonnet 4.6; Haiku for mechanical sub-steps.
- **Test layer** → added as a bridge artifact; standing invariants as tests, every step gates on green.
- **Step-0 storage** → local parquet + decimal128; GCS at step 4 via the `DataAccess` seam.
- **Day-count** → actual_days / 365 (AMFI).
- **Validation tolerances** → own↔oracle relative ≤ 1e-6; published ≤ 10 bps after as-of match.
- **Published-return source** → AMC factsheet at a common month-end as-of; aggregators cross-check only.
- **Step-0 reference set** → equity categories + short-duration debt + liquid + FoF + multi-asset; one fund paired direct+regular.
- **Reporting** → Excel/CSV exports and factsheet links are one-directional review surfaces; fixtures/parquet/metrics are authoritative.
- **Numeric types / materialisation** → Decimal on the path of record; float64 for analytical return series + bulk compute; monthly returns materialised, daily derived, convert once.
- **Return-series representation & storage** → ReturnSeries float64 + Decimal base; inverse conversion yields ValueIndex (distinct from NavSeries); conversions in `returns/convert.py`; monthly panel = completed months only, immutable; per-scheme provenance hash over month-end NAV inputs, recompute-on-mismatch. ReturnResult stays Decimal.

**Still open**
- **Expense-ratio sourcing** — the step-3 sequencing conflict above. *Decision needed.*
- **Deployment checkpoint scope** — exactly what is live after step 3 vs step 7.
- **Time estimates per step** — step 0 estimated at ≈8 × 45-min sessions; remaining steps unestimated.
- **NL interface** — built incrementally across earlier steps, or a distinct phase (currently leaning distinct, step 8).
- **Onboarding mechanism** — CAS email vs MFCentral QR (deferred to Layer 2).
- **Verify Morningstar/mstarpy** as the holdings + TRI source — India coverage, AMFI-code matching, and terms of use. Also check AMFI portal depth for machine-readable historical holdings before committing to a backfill scraper.
- **Security master source selection** — NSDL + NSE daily symbol-ISIN map is the assumed path. Confirm coverage completeness (especially for older ISINs in historical holdings) before build.
- **Step-0 anchor/annualisation convention** — pin in 0.6 (gold 1Y ~21 bps); match factsheet, don't loosen tolerance.
