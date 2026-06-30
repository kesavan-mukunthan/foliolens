# CLAUDE.md — FolioLens standing conventions

Auto-loaded each session. These are the standing correctness laws of the analytical / return engine. Spec-specific acceptance lives in `specs/spec-*.md`, which **reference this file rather than restate it**. Every law below is enforced by an executable test in `tests/invariants/`. "Honour the convention" is not the gate — a green test is.

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
- Day-count: `years = actual_days / 365` (AMFI convention). Fixed; do not vary per call. SEBI mandates CAGR but is silent on the day-count basis — it does not adjudicate actual/365 vs integer-year exponents. The per-fund reconciliation target is the AMC factsheet's own stated methodology; a days/365-vs-integer-year gap is a convention difference, not a bug, and is never closed by loosening tolerance.
- Time-weighted return (TWR) is the default. On a cashflow-free NAV series, TWR equals the point-to-point geometric return — they must coincide. MWR/XIRR applies only where cashflows exist (not in step 0).

## Analytics conventions
- Analytics consume the materialised monthly `ReturnSeries` (float64). Pure functions take `ReturnSeries`; `Investment` adapters read `.returns`. Drawdown is the only exception — base = daily NAV via `.source`.
- Canonical monthly return = simple (arithmetic), month-end to month-end. Log returns derived on demand.
- Annualisation: return geometric `(1+R)^(12/n) − 1`; volatility `√12`. Declared explicitly to the oracle.
- Risk-free = IIMA 91-day T-bill column (RBI new-issuance yield, 250-trading-day basis, bundled with the factor library). Same rf for Sharpe and Sortino; Sortino MAR = rf. An `Investment`, not a scalar. Live extension past the IIMA release lag comes only from RBI-direct; fixtures stay inside the IIMA range.
- Rolling returns: monthly step, 1/3/5y windows. A window longer than history emits no point — an empty young-fund panel is correct, not a bug.
- Benchmark return-variant (TRI vs PRI) is part of benchmark identity. Never PRI for any relative metric. fund→benchmark is a stored default, overridable.
- Analytics acceptance = own-vs-oracle on a frozen fixture `ReturnSeries` — never published or live. (The return engine keeps the three-way incl. published; analytics stop at own-vs-oracle.)

## Source of truth & determinism
- Analytics read **stored** NAV only. Never call mftool (or any live source) at read/compute time. Ingestion writes; analysis reads stored parquet.
- The same stored inputs must produce an identical validation report across runs.
- **IIMA factor library is not licensed for redistribution** (derived from CMIE Prowess). Use as a computation input with citation (the 2013 working paper); never republish the factor or rf series as data. Re-check on any external-exposure decision — same discipline as benchmark TRI and survivorship-free universe sourcing.

## Validation
- Three-way: own implementation vs a library oracle (ffn primary; empyrical-reloaded optional) vs the published figure.
- **Periodicity is declared explicitly** to the oracle (daily vs monthly). Undeclared periodicity silently mis-annualises.
- Tolerances — fixed constants. A step spec may tighten them; **never loosen them at runtime to make a test pass**:
  - own ↔ oracle: relative ≤ `1e-6`.
  - own/oracle ↔ published: ≤ `10 bps` absolute, after matching the published as-of date.
- Out-of-tolerance **fails loud** with fund / period / delta. Never swallow, never auto-loosen.

## Reporting
- Any Excel/CSV export is a **one-directional review surface** for eyeballing. It is never authoritative and is never read back into the pipeline. Stored parquet, computed metrics, and recorded fixtures are the source of truth.

## Commits & PRs
- Keep the `Co-Authored-By: Claude ...` trailer on commits. **Do not** add a `Claude-Session:` line (or any `https://claude.ai/code/session_...` link) to commit messages or PR bodies — no session links in repo artifacts.

## Protocol
- `ReturnSource` supplies `value_series` + `cashflows` **only**. Returns are produced by the `period_return` free function. **Risk/analytics are free functions over `ReturnSeries`, not methods on `ReturnSource` or any data class** — mirroring the engine. The earlier "risk metrics are protocol surface" rule is **withdrawn** (see `specs/spec-analytics.md` §0): no `sharpe`/`max_drawdown`/`volatility` on the protocol or the concrete sources.
