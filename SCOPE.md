# FolioLens — Scope Brief for Planning

*Revised (rev 3 — analytics-rename-reorder session). Supersedes prior versions. Source of truth for build order, design decisions, and open questions. Rev 3: specs are capability-named (numbers no longer encode sequence; SCOPE owns build order), and the build order is reordered so the analytical core on fixtures (`spec-analytics`) precedes personal/CAS and scale.*

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
- **Bridge artifacts in the repo:** `CLAUDE.md` (standing conventions + invariants), `SCOPE.md` (this brief — **owns build order**), `specs/spec-*.md` (capability-named handoffs with acceptance criteria; **no sequence in the filename**), `tests/` (invariants as tests; the acceptance gate).
- **Every step gates on a green test suite.** Standing correctness laws live in `CLAUDE.md` and are enforced as tests in `tests/invariants/`; step specs add fixture-bound acceptance in `tests/step-NN/`. "Honour the convention" is not the gate — a green test is.
- **Per-step rhythm:** design here → spec committed → build in Claude Code → review here → update brief if a decision changed.
- **Mobile = design/review here; desktop = Claude Code execution.** For curriculum-aligned steps (RAG, LangGraph, MCP, evals), Claude Code scaffolds and reviews rather than autocompletes, to preserve learning.

## Build Order

Specs come in two axes. **Capability specs** = what the product can do. **Platform specs** = how it's served at scale. Order is sequenced here; parallel tracks and the platform-phase boundary are marked. Only `spec-returns` is built; `spec-analytics` is ready; the rest are forward references.

**Phase A — analytical core (local, on fixtures)**
- `spec-returns` — NAV→returns, TWR/SEBI, three-way validation. **Built.**
- `spec-analytics` ‖ `spec-benchmarks` — *parallel.* Risk/risk-adjusted metrics over `ReturnSeries`; rf + benchmark-TRI ingestion + fund→benchmark mapping. Analytics gates on **own-vs-oracle**, not the published reconciliation, which is what lets it run beside return validation. A disposable HTML+Plotly renderer is the tail of `spec-analytics`.

**— Platform-phase boundary: opens once analytics is solid —**

**Phase B — serve & scale (demand-driven)**
- `spec-deploy` → `spec-api` → `spec-ui` — *ordered within:* container/Cloud Run/CI first, then serve the metrics artifact, then the product frontend over that API. Auth/tenancy enter here (external/multi-user only).
- `spec-scale` — fixtures → universe ingestion, GCS swap behind `DataAccess`, daily job. *Parallel to B, pulled by product scope* — a curated-set v1 may not need it yet. Don't pull it forward automatically.

**Phase C — capabilities on the served platform** *(order dependency-driven, not locked)*
- `spec-personal` — **distinct product line (Layer 2).** CAS→ledger→`HeldSource`→MWR/TWR; **realised-gain/tax last** within the line. Needs analytics + CAS, **not** the universe, so it can run parallel to scale. Reuses the shared analytics substrate — additive, not a refactor.
- `spec-screener`, `spec-recommender` — universe features (Layer 1); need `spec-scale`.
- `spec-monitor` — personal + universe-relative alerts.
- `spec-holdings` — DAG, look-through, attribution.
- `spec-factor` — returns-based Carhart (unblocked, IIMA); holdings-based Brinson (after holdings + security master + PIT characteristics).
- `spec-nl`, `spec-construct`, `spec-finance` — NL/RAG interface; portfolio construction; personal-finance integration.

**Background track (not a spec):** holdings forward-append job + security master + NSE characteristics — runs alongside so data accumulates.

**Old→new map:** step-0→`spec-returns`; new→`spec-analytics`,`spec-benchmarks`; steps 1–2→`spec-personal` (personal metrics just reuse `spec-analytics`); step-3→`spec-monitor`+platform; step-4→`spec-scale`; step-5→`spec-monitor`; step-6→`spec-screener`; step-7→`spec-recommender`; step-8→`spec-nl`; step-9→`spec-factor`; step-10→`spec-construct`; step-11→`spec-finance`.

## Key Design Decisions

**Sequencing**
- **Analytical core on fixtures first**, ahead of personal/CAS and ahead of scale — the original "personal before universe" rationale (validate on known funds) is now served by fixture validation, so personal no longer needs to precede the universe.
- **`spec-analytics` ‖ `spec-benchmarks`** — benchmarks is its own data-sourcing capability (licensing, TRI/PRI) but times alongside analytics, not after.
- **Analytics decouples via own-vs-oracle on frozen fixtures** — never against published or live series; this is what keeps it parallel to return reconciliation.
- **Platform phase (deploy→api→ui, + scale) opens once analytics is solid**, replacing the old "deploy after steps 3/5/7/10" checkpoints. Scale is demand-driven.
- **Personal portfolio is a distinct product line** built after analytics; reuses the analytics layer; realised-gain/tax is the last module within it; the ledger is lot-grain from the first transaction.
- **Analytics are free functions over `ReturnSeries`**, not methods on data classes or `ReturnSource` — see the `spec-analytics §0` refactor.
- Every build step still gates on a green test suite.

**Data model**
- **Two-level schema: Fund and ShareClass.** Fund = the strategy (one portfolio, one benchmark; holdings and category attach here). ShareClass = one AMFI code (`amfi_code`), carrying plan × option, NAV, expense ratio, ISIN. Regular/direct handling is a **share-class pairing under one Fund** — pair regular-growth with direct-growth to compute expense drag and breakeven (a taxable event; LTCG with 31-Jan-2018 grandfathering must be factored). Fund grouping is derived by parsing names/ISINs (fragile; tested, with a manual-override hook).
- **Numeric types by role:** `Decimal`/`decimal128` on the path of record (NAVs, reconciled metrics, cost basis, cashflows); `float64` for analytical return series and bulk vectorised compute. Convert once at materialisation.
- Cost basis stored at transaction grain (lot-level FIFO + grandfathering), never derived loosely.
- Tenancy key and PII segregation from day one, even with a single user.

**Return engine**
- **Growth-option NAV** is the return basis (IDCW NAVs misstate total return). Regular/direct comparison = regular-growth vs direct-growth.
- **`ReturnSource`** supplies `value_series` + `cashflows` **only**. Returns come from the `period_return` free function; **risk/analytics are free functions over `ReturnSeries`**, not methods on the protocol or the data classes (see `spec-analytics §0`). TWR is the default; MWR/XIRR where cashflows exist. The earlier "risk metrics are protocol surface" rule is withdrawn.
- **Month-end is the base**; daily only for intra-month. Universe metrics materialised at month-end; personal funds may compute daily. Step 0 stores daily as the raw base and validates point-to-point. Monthly return series is the materialised analytical layer (float64, month-end to month-end); daily returns are derived on demand, not stored; trailing CAGRs are Decimal figures of record.
- **Conversion seam:** `returns/convert.py` holds the boundary-crossing free functions — `simple_return(start,end)->float`, `to_returns(NavSeries)->ReturnSeries` (the single Decimal→float cast-at-birth), `to_index(ReturnSeries)->ValueIndex`. ReturnSeries is float64-backed with a Decimal base; ValueIndex (float levels) is distinct from NavSeries. The scalar `period_return->ReturnResult` path stays Decimal and does not route through the series.
- Conventions (in `CLAUDE.md`): month-end NAV = last available on/before calendar month-end; SEBI annualisation (absolute < 1Y, CAGR ≥ 1Y); **day-count = actual_days / 365 (AMFI)**; declare periodicity to ffn/empyrical.
- **Validation:** three-way (own impl vs ffn/empyrical oracle vs published). Tolerances are fixed constants, never loosened at runtime to pass — own↔oracle relative ≤ 1e-6; own/oracle↔published ≤ 10 bps after matching the published as-of. Out-of-tolerance fails loud. **Published leg = the AMC factsheet at a common month-end as-of**; aggregators (Value Research / Morningstar) are cross-checks only.
- **Reuse, don't reimplement:** ffn / empyrical-reloaded (+ pyxirr once cashflows exist) as the production calc and/or validation oracle.

**Personal portfolio (distinct product line)**
- Separate bounded context (Layer 2): own CAS ingestion, own transaction ledger, own MWR/lot logic — **reusing** the shared analytics layer, not duplicating it.
- **Store the transaction ledger as the primitive, lot-grain, from the first row.** Per row: `txn_type` (buy/sell/switch-in/out/IDCW-reinvest/payout), `nav_at_txn`, `units`, signed amount — all `Decimal`. Units-held, market-value series, net-invested, weights, returns all **derive**; never persist a "net units" or "amount invested" series (netting can't be un-netted, and a stored derived series drifts from the ledger + NAV).
- Positions are **PIT edges carrying units** on the existing holdings DAG; weights derive from units×NAV per `as_of`. No new mechanism.
- **Two returns, two questions:** MWR/XIRR (scalar — "what my money earned," timing included; the headline personal figure) vs portfolio TWR (the value series → feeds risk metrics). **Risk analytics run on the TWR-derived `ReturnSeries`, never MWR.**
- **Realised-gain/tax is its own module, built last in the line.** Needs: per-lot FIFO matching; 31-Jan-2018 FMV per scheme (grandfathering — backfillable from AMFI); ruleset **parameterised by financial year** (rates/holding-period/indexation shift with budgets — never hardcode; verify against live FY rules at build time). Performance surface (MWR/TWR/weights) needs only net units + transactions, so it ships before any lot/tax logic.

**Platform phase**
- Triggered by *analytics solid*, not by a step number. `DataAccess` (input seam) and the metrics artifact (output contract) make it **additive**: scaling data = swapping behind the seam; the API/UI consume the contract, not rebuild compute.
- Internal order: `spec-deploy` (Docker/Cloud Run/CI) → `spec-api` (serve artifact) → `spec-ui` (frontend). `spec-scale` runs parallel, demand-driven.
- There is **no single "data-layer spec."** Per-capability ingestion lives inside each capability spec (returns→NAV, benchmarks→TRI/rf, personal→CAS, holdings→AMFI); only universe scale-out is its own spec (`spec-scale`). One combined data spec would recreate the coupling the seam prevents.

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
- **Spec-naming scheme** → capability-named, no numbers; `SCOPE.md` owns build order as an ordered list that reorders without renaming files.
- **Analytics design** → free functions over `ReturnSeries`, not methods on data classes or `ReturnSource` (see `spec-analytics §0`).
- **Analytics conventions** → rf = IIMA 91-day column; Sortino MAR = rf; drawdown base = daily NAV; rolling monthly 1/3/5y; vol √12; geometric annualisation; simple canonical month-end return.
- **rf source** → IIMA bundled column (not FBIL).
- **Benchmark identity** → return-variant (TRI/PRI) is part of the identity; never PRI for relative metrics.
- **Benchmarks vs analytics** → split into `spec-benchmarks`, timed parallel to `spec-analytics`, not after.
- **Personal portfolio** → distinct product line; realised-gain/tax built last in the line; transaction ledger stored lot-grain from the first row.

**Still open**
- **IIMA factor/rf library redistribution** — **not licensed for redistribution** (CMIE Prowess derived); fine as a computation input with citation, but get written permission before any external exposure of the factor or rf series.
- **Platform-phase first-deploy scope** — curated set vs `spec-scale`; decide when Phase B opens.
- **Expense-ratio sourcing** — the step-3 sequencing conflict above. *Decision needed.*
- **Deployment checkpoint scope** — exactly what is live after step 3 vs step 7.
- **Time estimates per step** — step 0 estimated at ≈8 × 45-min sessions; remaining steps unestimated.
- **NL interface** — built incrementally across earlier steps, or a distinct phase (currently leaning distinct, step 8).
- **Onboarding mechanism** — CAS email vs MFCentral QR (deferred to Layer 2).
- **Verify Morningstar/mstarpy** as the holdings + TRI source — India coverage, AMFI-code matching, and terms of use. Also check AMFI portal depth for machine-readable historical holdings before committing to a backfill scraper.
- **Security master source selection** — NSDL + NSE daily symbol-ISIN map is the assumed path. Confirm coverage completeness (especially for older ISINs in historical holdings) before build.
- **Step-0 anchor/annualisation convention** — pin in 0.6 (gold 1Y ~21 bps); match factsheet, don't loosen tolerance.
