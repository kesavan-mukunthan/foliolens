# CLAUDE.md — FolioLens standing conventions

Auto-loaded each session. These are the standing correctness laws of the analytical / return engine. Step-specific acceptance lives in `specs/step-NN-*.md`, which **reference this file rather than restate it**. Every law below is enforced by an executable test in `tests/invariants/`. "Honour the convention" is not the gate — a green test is.

## Working model
- Design, specs, and review happen in the Claude.ai project. Construction happens in Claude Code against a committed spec.
- A build step is done only when **all tests are green**.

## Money & precision
- **Decimal on the path of record; float64 on the path of scale.**
  - `Decimal` for anything stored as a figure of record, reconciled, or touching money: NAVs, reconciled trailing metrics (1Y/3Y/5Y CAGR), cost basis, cashflows. The engine's `ReturnResult` is a figure of record → stays `Decimal` (enforced by `test_no_float_in_returns`).
  - `float64` for analytical return *series* (factor/regression/optimisation inputs) and bulk vectorised compute (universe screens, fixed-weight backtests) — derived views, never figures of record.
  - Convert **once, at materialisation**, never per call. Float never flows back into a stored figure of record or a money sum.
- NAV is stored as parquet `decimal128` (DuckDB `DECIMAL(18,6)`). It must round-trip parquet → load → compute with **no cast to DOUBLE**. Enforced by `test_decimal_roundtrip`.

## NAV & return conventions
- Return basis is the **growth** option NAV. IDCW NAVs understate total return — never use them as the return basis. Direct-vs-regular comparison is growth-vs-growth.
- Month-end NAV = the last available NAV **on or before** the calendar month-end. Never select a NAV dated after month-end (no look-ahead).
- Daily NAV is the stored raw base; month-end is a derived series on top. Both are queryable.
- Daily returns are **derived on demand** from daily NAV (never stored). Monthly returns (month-end to month-end) are the **materialised** analytical series. Trailing CAGRs are figures of record.
- Annualisation follows **SEBI**: period **< 1 year → absolute** return `(end/start − 1)`, never annualised; period **≥ 1 year → CAGR** `(end/start)^(1/years) − 1`.
- Day-count: `years = actual_days / 365` (AMFI convention). Fixed; do not vary per call.
- Time-weighted return (TWR) is the default. On a cashflow-free NAV series, TWR equals the point-to-point geometric return — they must coincide. MWR/XIRR applies only where cashflows exist (not in step 0).

## Source of truth & determinism
- Analytics read **stored** NAV only. Never call mftool (or any live source) at read/compute time. Ingestion writes; analysis reads stored parquet.
- The same stored inputs must produce an identical validation report across runs.

## Validation
- Three-way: own implementation vs a library oracle (ffn primary; empyrical-reloaded optional) vs the published figure.
- **Periodicity is declared explicitly** to the oracle (daily vs monthly). Undeclared periodicity silently mis-annualises.
- Tolerances — fixed constants. A step spec may tighten them; **never loosen them at runtime to make a test pass**:
  - own ↔ oracle: relative ≤ `1e-6`.
  - own/oracle ↔ published: ≤ `10 bps` absolute, after matching the published as-of date.
- Out-of-tolerance **fails loud** with fund / period / delta. Never swallow, never auto-loosen.

## Reporting
- Any Excel/CSV export is a **one-directional review surface** for eyeballing. It is never authoritative and is never read back into the pipeline. Stored parquet, computed metrics, and recorded fixtures are the source of truth.

## Protocol
- `ReturnSource`: Fund, ShareClass, Portfolio, Benchmark each supply `value_series` + `cashflows`; returns/risk are implemented once on top. Risk metrics (Sharpe, drawdown, vol) are **protocol surface only** until step 2.
