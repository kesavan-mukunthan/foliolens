# FolioLens — Domain Model (Architecture)

*Standing reference. The investment/return model the whole platform builds on. `CLAUDE.md` = correctness laws; `SCOPE.md` = build order; this = the object model. Step specs build subsets of it.*

## Principle
**One investment type, behaviour in functions, two pluggable strategies.** Investments are pure data (no I/O); the engine is stateless functions; all reads go through one `DataAccess` seam. Keeps decision logic deterministic, testable, and freeze-and-validate clean. Standard composition-over-inheritance — interface for *what a thing is*, strategy for *what it does*.

## The contract
Everything investable is an `Investment` exposing a **return series**. NAV and cashflows are **not** on the contract — they are inputs to specific return producers, hidden behind it.

```python
class Investment(Protocol):
    id: InvestmentId                # type tag + identifier
    source: ReturnSource            # strategy that owns value_series + cashflows
    benchmark: "Investment | None"
    holdings: list[Holding]         # weighted child edges; empty at leaves
    def returns(self, freq: Frequency) -> ReturnSeries: ...  # panel lookup, keyed by frequency
```

`returns(freq)` is a **lookup**, not a computation: each priced Investment (`ShareClass`, `Benchmark`) carries `panels: Mapping[Frequency, ReturnSeries]`, computed **eagerly, once, at construction** by its factory (`share_class_from_nav`, `benchmark_from_index` — the only sites that call `monthly_returns`/`to_returns` to build a panel). Asking for a frequency that was never built raises `ValueError` naming the investment and the missing frequency — never `KeyError`, never `None`. The engine free function `period_return(source, period, as_of)` is separate and unaffected: it consumes `source.value_series` directly (the Decimal figure-of-record path), never a panel. "Benchmark" is a **role** in a comparison, not a type.

## Return sources (how returns are produced)
- **PricedSource** — investment has its own observed level series (NAV/price/TRI): `returns = TWR(value_series)`. Stock, ShareClass, Fund, Benchmark, real FoF. *Holdings here are look-through only — never the return source.*
- **BlendSource** — no price: `returns = blend(holdings, weights)`. Hypothetical portfolio, synthetic FoF.
- **HeldSource** — `value_series + cashflows`: `returns = MWR/XIRR`. Only your real invested portfolio.

Assign the source in the loader / composition root, **never the caller** — that is what stops a priced fund from accidentally getting a `BlendSource` and rolling returns up from stale holdings.

## Weight policies (how children combine — blends only)
- **Fixed** — rebalanced to targets each period; `Σ wᵢ rᵢ` with constant weights. Frictionless. Vectorisable (one matrix multiply over a shared return matrix) → cheap for side-by-side backtests.
- **Drift** — buy-and-hold; `wᵢ[t+1] ∝ wᵢ[t](1+rᵢ[t])`. Sequential (carries state).
- **PIT** — actual weights from holdings disclosures.

Fixed = costless perfect rebalancing; Drift = zero rebalancing; reality is between. Rebalancing is a **parameter**, not a separate class.

## Value objects (carry invariants so nothing re-checks them)
- **NavSeries** — sorted, de-duped, `Decimal` on construction; owns `.as_of()`, `.between()`. Month-end resampling is *not* a NavSeries method — it needs a `TradingCalendar` (see below) and lives in `returns/monthly.month_end(nav, cal)`: a month is emitted iff the NAV series carries a point exactly on the calendar's last trading day for that month **and** at least one point in the strictly next calendar month (completeness — no look-ahead, and no fabricated completeness for a still-accumulating trailing month); the emitted point is relabelled onto the true calendar month-end date.
- **TradingCalendar** — the set of dates a majority of an active universe published a NAV on (`returns/calendar.derive_calendar`), the artifact `month_end` resolves "last trading day" against. Derived **once per category class per run** (e.g. the equity cohort, separately from any liquid/debt cohort — never mixed) and shared across every fund and benchmark in that class; never derived per fund.
- **ReturnSeries** — periodic returns + a base. ReturnSeries holds float64 data (path of scale) with a Decimal base anchor; a return series + base reconstructs a **ValueIndex** (the dual of NavSeries), which is why composition rebuilds an index internally.
- **ValueIndex** — float-backed synthetic level series from inverse conversion (base·Π(1+r)). Explicitly distinct from NavSeries — no amfi_code, no month-end rule, never reconciled against stored NAV. Reconstruction round-trips return *ratios* (≤1e-6), never NAV levels (only base survives; levels rebase to 100).
- **ReturnResult** — value + provenance (period, both endpoint NAVs, dates, method) for reconciliation/report.
- **Cashflow** — `(date, signed amount)`; fixed sign convention (investor-out negative, in positive, terminal value as final inflow). Empty everywhere except `HeldSource`.

## Numeric types & materialisation
- **Path of record → `Decimal`/`decimal128`:** daily NAV, reconciled trailing metrics, cost basis, cashflows. `NavSeries` and `ReturnResult` stay Decimal.
- **Path of scale → `float64`:** analytical return *series* (factor/regression/optimisation), universe screens, fixed-weight backtests — float-native libraries, derived views, not figures of record. Float precision is far below the binding constraint here; sampling error dominates factor results.
- **Materialise vs derive:** daily NAV stored (decimal128); **monthly return series materialised** (`float64` — matches the IIM-A library and attribution); **daily returns derived on demand**; month-end NAV derived. Convert once at materialisation.

## Analytics (functions over the return series)
A layer above the model: pure free functions over `ReturnSeries`, never methods on the data classes or on `ReturnSource`. Mirrors the engine — `period_return` is a free function; analytics follow the identical pattern.

- Two branches off NAV, never unified. (A) `period_return(source) -> ReturnResult` — the SEBI scalar, Decimal, a figure of record. (B) `to_returns(NavSeries) -> ReturnSeries` — the materialised monthly float64 series. Risk metrics consume B; they never touch the scalar path.
- Pure metric functions: `f(r: ReturnSeries, …) -> MetricsResult`. They receive a return series and structurally cannot re-derive from NAV (never see it) — which makes own-vs-oracle trivial.
- Investment adapters: `sharpe_of(investment, rf)` read `investment.returns(Frequency.MONTHLY)` (the materialised, eagerly-built panel) and delegate. "Returns already present" lives here — the adapter looks the panel up, it never computes it.
- Drawdown is the one exception: base is the DAILY panel, `investment.returns(Frequency.DAILY)` — still a lookup, not a recomputation, since the factory built that panel eagerly too. The protocol exposes both seams — `.source` (daily value path, for the odd case that needs the raw NAV's own first date) and `.returns(freq)` (the panel lookup).
- rf is an Investment, not a scalar param: the 91-day T-bill (IIMA-bundled column) with its own return series; Sharpe/Sortino consume it exactly as beta/alpha consume the benchmark Investment.
- Benchmark identity: natural key (provider, index_name, return_variant). Return variant (TRI vs PRI) is part of identity -> PRI cannot be silently substituted. The fund->benchmark mapping is a stored default (FK to a benchmark Investment, at Fund level), overridable by an explicit arg.
- Output contract: the metrics artifact — fund -> {metadata, metrics, series}, serializable, versioned, the eventual API payload. Renderers are disposable consumers; the artifact is the durable output seam, dual to DataAccess on input.

## Concrete investments (all the same class; differ by source + role)
- **Stock** — leaf; PricedSource over price/TRI; no holdings.
- **ShareClass** — one AMFI code (`isin, plan, option`); PricedSource over NAV. The true priced unit.
- **Fund** — strategy; groups share classes + benchmark + holdings; priced via a representative ShareClass NAV.
- **Portfolio** — composite; `BlendSource` (hypothetical) or `HeldSource` (your real one); recurses → FoF.
- **Benchmark** — PricedSource over TRI; identical behaviour to a fund; "benchmark" is the comparison role, not machinery.
- **Cash** — one shared leaf investment; PricedSource over a cash-rate index (not zero-return — a fund's NAV already earns on its cash); makes a parent's weights sum to 1; also the home for unclassifiable residual. INR-only → a single `CASH` node.

## Holdings as a DAG (not a tree)
Children are weighted edges; a shared child has multiple parents → **DAG, deduped by investment id**.

```
investments: id, type, metadata                   # one row per investment
edges:     parent_id, child_id, as_of, weight      # sparse, point-in-time
```
- **Sparse PIT:** only actual holdings stored; absence of a row = not held. Never store explicit 0s — avoids the 0-vs-unknown ambiguity and universe-sized bloat.
- **Reference children by id** → one Stock investment, many inbound edges (overlap is native, no duplication).
- `holdings(as_of)` resolves edges for that parent+month → `[(child, weight)]`; recurse on each child; stop at leaves (no edges). Guard cycles, cap depth.
- Persisted as the brief's holdings parquet (long/tidy, partitioned `parent/year/month`); the in-memory DAG is the adjacency resolved per `as_of`.

## Two operations off the DAG (treat differently)
- **Returns** — blend child returns up each level. Sharing is irrelevant; each priced node returns from its own series. No dedup, no look-through.
- **Look-through exposure** — flatten to leaves, **summing weight across every path**:
  `w_eff(leaf) = Σ_paths Π edge_weights`.
  This is where sharing matters (overlap / concentration). e.g. a portfolio 60/40 over two 50/50 funds that share one stock → that stock = 50%, hidden concentration neither fund shows alone.

## Weights as a time series
Each edge weight is a **curve** (step function: PIT disclosures, or a `WeightPolicy`), not a scalar.
- **Resolve at a date first:** `weight(parent, child, as_of)` → scalar; then the traversal is the static computation. Time lives in the edges; the traversal stays point-in-time and scalar.
- A time series of exposure = `w_eff(leaf, t)` mapped over an `as_of` grid.
- **Align all curves to a common grid before multiplying** (sample each at last value on/before the grid date — the month-end rule). Multiplying weights pulled from mismatched disclosure dates is the silent error.
- Exposure curve (from weight curves) and portfolio return (from blending fund NAV returns with the **portfolio-level** weights) are two different series off the same DAG; the return never touches stock-level curves.

## Invariants
1. Priced investments return from their **series, not holdings**.
2. Cashflows live **only** on `HeldSource`.
3. Weights at one `as_of` sum to 1 via an explicit `Cash`/residual node.
4. Source + policy are assigned in the composition root, not by callers.
5. Aggregate at the **value/level**, then differentiate to returns — never average multi-period returns. Per-period re-weighting in return space is the equivalent (single-period returns are linear: `Σ wᵢ rᵢ`).
6. Analytics are free functions over `ReturnSeries`, never methods on `ReturnSource` or any data class. Drawdown is the sole reader of daily NAV (via `.source`).
7. rf and benchmark are `Investment`s, not parameters. Benchmark return-variant (TRI/PRI) is part of identity; PRI is never used for relative metrics.

## Step-0 subset (build now vs stub)
- **Build concretely:** `Investment`, `ReturnSeries`, `ValueIndex`, `NavSeries`, `TradingCalendar` (`returns/calendar.py`), `returns/monthly.py` (`month_end`, `monthly_returns`), `ReturnResult`, `ReturnSource` protocol, `PricedSource`, `ShareClass`, `Fund` (priced via representative share class), engine (`period_return`, TWR, SEBI), `returns/convert.py` (`simple_return`, `to_returns`, `to_index`).
- **Define but stub** (keep the contract stable, no logic): `Cashflow`, `HeldSource`, `BlendSource`, `WeightPolicy` (Fixed/Drift/PIT), `Holding`/edge + DAG resolve, `Stock`, `Portfolio`, `Benchmark`, `Cash`.
- **Not in step 0:** look-through, weight curves, MWR, blends — this doc is the forward reference for the later steps that build them.

## Calendar architecture
There is no published Indian mutual-fund trading calendar in scope, so the calendar is **derived** from the NAV panel itself: a date is a trading day when a majority (a quorum) of the funds active on it published a NAV (`returns/calendar.derive_calendar`). One such calendar is derived **per category class per run** — the equity cohort separately from any liquid/debt cohort, shared across every fund in the class, never derived per fund and never mixed across classes. A **benchmark resolves its calendar from its own published index dates** (`returns/calendar.calendar_from_dates`), never the shared cohort calendar: a fiscal-year-end NAV that many AMCs stamp on a non-session day (e.g. 31 March) can make the cohort calendar treat a day the index never traded on as a trading day, which would silently drop that month — and, via the adjacent-month rule, the next month's return too — from the benchmark panel. Month emission follows the **tail-match completeness rule**: month `M` is emitted only once the fund's last NAV in `M` reaches `M`'s true last trading day **and** at least one NAV exists in the strictly next month `M+1` (no look-ahead, no fabricated completeness for a still-accumulating trailing month); the emitted point is relabelled onto the true calendar month-end. Trailing windows then slice on **calendar dates** — the span `(as_of − N months, as_of]`, whatever survives — not a fixed count of trailing points. Detail and the normative statements live in `specs/spec-returns.md` §0.4 (month-end rule), `specs/spec-benchmarks.md` (benchmark-on-own-dates), and the invariants `tests/invariants/test_month_end.py` and `tests/invariants/test_benchmark_calendar.py`.

## Storage
Current truth, then the target it is built toward.

- **Parquet is local.** The three datasets of record — `nav.parquet`, `index_nav.parquet`, `scheme_master.parquet` — live together on the build machine (WSL2), resolved one way through `FOLIOLENS_DATA_DIR` and read only through the single `data_access.py` seam. NAV is stored `decimal128` (DuckDB `DECIMAL(18,6)`) and round-trips parquet → load → compute with no cast to DOUBLE. Durability today is a **Drive-synced backup** of that directory, not a cloud object store.
- **DuckDB is a stateless query engine** over those local files: per-fund figure-of-record reads and bulk Arrow panel reads, both keeping NAV `decimal128`, never casting to DOUBLE inside SQL.
- **No deployment artifacts exist yet.** There is no container, no Cloud Run job, no CI-invoked ingestion, no `gs://` path in the read seam. Ingestion is a locally-run, resumable job; analysis reads the stored parquet it produced.

### Target state (not current)
The aspirational architecture, kept here so the seam is built toward it — **none of this is wired today**:
- Raw NAV lands in **GCS**; a consolidated sorted parquet per dataset on GCS becomes the source of truth (single file, `amfi_code` an ordinary column, rows sorted `(amfi_code, date)`, row-group pruning serving per-fund reads).
- The `DataAccess` seam is **repointed** from a local path to `gs://` with no other module changing — the swap is what `spec-scale` owns.
- A scheduled **Cloud Run** ingestion Job is the single writer (business days, upsert keyed `(code, date)`, holiday no-op, staleness alarm); read-only query instances pick up refreshed parquet. Container / Cloud Run / CI land under `spec-deploy`.
- An **OLTP Postgres** store (checkpoints, accounts, query logs) enters at Layer 2, not before.

## Capability inventory

<!-- BEGIN capability-inventory (generated by scripts/gen_inventory.py; do not edit) -->
_Generated by `scripts/gen_inventory.py` — do not edit by hand. Regenerate after adding or removing a module in `src/foliolens/`; CI fails on drift._

52 modules. One line per module — first sentence of its docstring, extracted mechanically.

### `foliolens`

- `__init__.py` — FolioLens — NAV ingestion, return engine, and validation harness.
- `benchmark_map.py` — Fund→benchmark mapping — the hand-curated half of the metadata surface.
- `cli.py` — End-to-end runner.
- `data_access.py` — Single read seam for NAV parquet data.

### `foliolens.analytics`

- `__init__.py` — Analytics — pure free functions over the materialised ``ReturnSeries``.
- `adapters.py` — §5 Investment adapters for the §2/§4 metrics — ``*_of(investment, …)``.
- `artifact.py` — §5 metrics artifact — the durable, versioned per-fund output contract.
- `distribution.py` — §4 distribution statistics over ``ReturnSeries`` — % positive, best/worst, skew, kurtosis.
- `drawdown.py` — §3 daily-basis family: drawdown (max + duration + recovery), VaR, CVaR.
- `metrics.py` — §2 pure-core metrics over ``ReturnSeries`` (no benchmark).
- `peer.py` — §7 peer / cross-sectional machinery — pure functions over a cohort.
- `relative.py` — §6 benchmark-relative metrics over aligned ``ReturnSeries`` (no benchmark I/O).
- `rolling.py` — §4 rolling returns — monthly step, 1/3/5y windows, over ``ReturnSeries``.
- `series_ops.py` — Series utilities for the analytics layer.

### `foliolens.ingest`

- `__init__.py` — Ingestion sub-package: mftool client and raw parquet landing.
- `iima.py` — IIM-A factor-library parser — the 91-day T-bill (risk-free) column.
- `index_normalise.py` — Per-source normalisers for benchmark index levels (TRI only).
- `land.py` — Raw NAV landing layer.
- `mftool_client.py` — mftool client — all mftool calls are isolated here.
- `scheme_master.py` — Scheme master — universe-scale fund metadata derived from backfill shards.
- `universe.py` — Resumable universe NAV landing.

### `foliolens.model`

- `__init__.py` — FolioLens domain model — step-0 subset.
- `holdings.py` — Holdings edge dataclass and DAG resolver stub.
- `investments.py` — Investment protocol and concrete investment types.
- `sources.py` — Return source strategies.
- `value_objects.py` — Value objects for the FolioLens domain model.
- `weights.py` — Weight policies for blend-based investments.

### `foliolens.report`

- `__init__.py` — Report sub-package: Excel validation report writer.
- `excel.py` — Excel validation report writer (xlsxwriter, write-only).

### `foliolens.report.flexipage`

- `__init__.py` — F1 — the flexicap page's batch runner: universe -> ``metrics.json``.
- `__main__.py` — ``uv run python -m foliolens.report.flexipage --data-dir PATH --out PATH``.
- `assembly.py` — F1 per-fund panel assembly — composes spec-analytics functions into one entry.
- `commentary.py` — F4 batch commentary generation — one Anthropic API call per fund.
- `runner.py` — F1 batch runner — flexicap direct-growth universe → ``metrics.json``.
- `template_commentary.py` — Deterministic commentary floor — a template summary when no LLM block exists.

### `foliolens.report.flexipage.render`

- `__init__.py` — F2/F3 — static HTML render over ``metrics.json``, plus print-CSS PDF.
- `__main__.py` — ``uv run python -m foliolens.report.flexipage.render --metrics PATH --out DIR``.
- `build.py` — F2 renderer orchestration — parsed ``metrics.json`` -> static HTML site.
- `charts.py` — Pre-rendered SVG charts (matplotlib, no Plotly — ``spec-flexicap-page §4``).
- `pdf.py` — F3 — print-CSS PDF generation over the already-rendered HTML site.
- `presentation.py` — Pure shaping of one parsed ``metrics.json`` into template-ready structures.
- `strings.py` — Verbatim spec strings — copied exactly, never paraphrased or reflowed.

### `foliolens.returns`

- `__init__.py` — Returns sub-package: the return engine.
- `calendar.py` — Trading-calendar derivation from cross-sectional NAV publication.
- `convert.py` — The single Decimal→float seam on the return-series path.
- `engine.py` — Return engine.
- `frequency.py` — Declared periodicity of a ``ReturnSeries`` — never inferred from dates.
- `monthly.py` — Calendar-derived month-end resampling — the sole month-end rule.

### `foliolens.validation`

- `__init__.py` — Validation sub-package: oracle wrapper, three-way reconciliation, and the post-assembly identity checker (``identities.check_identities``).
- `identities.py` — B1 identity checker — post-assembly self-consistency cross-checks.
- `oracle.py` — Oracle wrapper for library-based return verification.
- `reconcile.py` — Three-way reconciliation: own implementation vs oracle vs published.
<!-- END capability-inventory -->

*A module can't exist without announcing itself here. Before speccing a sibling, read the adjacent module's line (and its docstring) first — see `CLAUDE.md`.*
