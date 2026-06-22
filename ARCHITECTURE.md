# FolioLens — Domain Model (Architecture)

*Standing reference. The entity/return model the whole platform builds on. `CLAUDE.md` = correctness laws; `SCOPE.md` = build order; this = the object model. Step specs build subsets of it.*

## Principle
**One entity type, behaviour in functions, two pluggable strategies.** Entities are pure data (no I/O); the engine is stateless functions; all reads go through one `DataAccess` seam. Keeps decision logic deterministic, testable, and freeze-and-validate clean. Standard composition-over-inheritance — interface for *what a thing is*, strategy for *what it does*.

## The contract
Everything investable is an `Entity` exposing a **return series**. NAV and cashflows are **not** on the contract — they are inputs to specific return producers, hidden behind it.

```python
class Entity(Protocol):
    id: EntityId             # type tag + identifier
    source: ReturnSource     # how returns are produced (strategy)
    benchmark: "Entity | None"
    holdings: list[Holding]  # weighted child edges; empty at leaves
    @property
    def returns(self) -> ReturnSeries:
        return self.source.compute(self)
```

`returns` is produced by a pluggable `ReturnSource`, not by subclassing. "Benchmark" is a **role** in a comparison, not a type.

## Return sources (how returns are produced)
- **PricedSource** — entity has its own observed level series (NAV/price/TRI): `returns = TWR(value_series)`. Stock, ShareClass, Fund, Benchmark, real FoF. *Holdings here are look-through only — never the return source.*
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
- **ReturnSeries** — periodic returns + a base. A return series + base = a **value index** (the dual of NavSeries) — which is why composition rebuilds an index internally.
- **ReturnResult** — value + provenance (period, both endpoint NAVs, dates, method) for reconciliation/report.
- **Cashflow** — `(date, signed amount)`; fixed sign convention (investor-out negative, in positive, terminal value as final inflow). Empty everywhere except `HeldSource`.

## Concrete entities (all the same class; differ by source + role)
- **Stock** — leaf; PricedSource over price/TRI; no holdings.
- **ShareClass** — one AMFI code (`isin, plan, option`); PricedSource over NAV. The true priced unit.
- **Fund** — strategy; groups share classes + benchmark + holdings; priced via a representative ShareClass NAV.
- **Portfolio** — composite; `BlendSource` (hypothetical) or `HeldSource` (your real one); recurses → FoF.
- **Benchmark** — PricedSource over TRI; identical behaviour to a fund; "benchmark" is the comparison role, not machinery.
- **Cash** — one shared leaf entity; PricedSource over a cash-rate index (not zero-return — a fund's NAV already earns on its cash); makes a parent's weights sum to 1; also the home for unclassifiable residual. INR-only → a single `CASH` node.

## Holdings as a DAG (not a tree)
Children are weighted edges; a shared child has multiple parents → **DAG, deduped by entity id**.

```
entities:  id, type, metadata                     # one row per entity
edges:     parent_id, child_id, as_of, weight      # sparse, point-in-time
```
- **Sparse PIT:** only actual holdings stored; absence of a row = not held. Never store explicit 0s — avoids the 0-vs-unknown ambiguity and universe-sized bloat.
- **Reference children by id** → one Stock entity, many inbound edges (overlap is native, no duplication).
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
1. Priced entities return from their **series, not holdings**.
2. Cashflows live **only** on `HeldSource`.
3. Weights at one `as_of` sum to 1 via an explicit `Cash`/residual node.
4. Source + policy are assigned in the composition root, not by callers.
5. Aggregate at the **value/level**, then differentiate to returns — never average multi-period returns. Per-period re-weighting in return space is the equivalent (single-period returns are linear: `Σ wᵢ rᵢ`).

## Step-0 subset (build now vs stub)
- **Build concretely:** `Entity`, `ReturnSeries`, `NavSeries` (with month-end), `ReturnResult`, `ReturnSource` protocol, `PricedSource`, `ShareClass`, `Fund` (priced via representative share class), engine (`period_return`, TWR, SEBI).
- **Define but stub** (keep the contract stable, no logic): `Cashflow`, `HeldSource`, `BlendSource`, `WeightPolicy` (Fixed/Drift/PIT), `Holding`/edge + DAG resolve, `Stock`, `Portfolio`, `Benchmark`, `Cash`.
- **Not in step 0:** look-through, weight curves, MWR, blends — this doc is the forward reference for the later steps that build them.
