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
    returns: ReturnSeries           # declared here; computed by engine.period_return(source, …)
```

`returns` is produced by the engine free function `period_return(source, period, as_of)` consuming `source.value_series`, not by a method on `ReturnSource`. "Benchmark" is a **role** in a comparison, not a type.

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
- **NavSeries** — sorted, de-duped, `Decimal` on construction; owns `.as_of()`, `.month_end()`, `.between()`. The month-end rule (last on/before calendar month-end, no look-ahead) lives here, once.
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
- Investment adapters: `sharpe_of(investment, rf)` read `investment.returns` (the materialised series) and delegate. "Returns already present" lives here.
- Drawdown is the one exception: base is daily NAV, read via `investment.source`, not the monthly series. The protocol exposes both seams — `.source` (daily value path) and `.returns` (periodic series).
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
- **Build concretely:** `Investment`, `ReturnSeries`, `ValueIndex`, `NavSeries` (with month-end), `ReturnResult`, `ReturnSource` protocol, `PricedSource`, `ShareClass`, `Fund` (priced via representative share class), engine (`period_return`, TWR, SEBI), `returns/convert.py` (`simple_return`, `to_returns`, `to_index`).
- **Define but stub** (keep the contract stable, no logic): `Cashflow`, `HeldSource`, `BlendSource`, `WeightPolicy` (Fixed/Drift/PIT), `Holding`/edge + DAG resolve, `Stock`, `Portfolio`, `Benchmark`, `Cash`.
- **Not in step 0:** look-through, weight curves, MWR, blends — this doc is the forward reference for the later steps that build them.
