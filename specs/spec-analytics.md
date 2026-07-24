# spec-analytics — Risk & risk-adjusted metrics over the return series

**Status:** ready for build *after* the §0 refactor lands. Self-contained subset has no remaining structural blockers (four conventions resolved, see `CLAUDE.md`). Benchmark-relative subset is gated on **spec-benchmarks** (rf + TRI ingestion), which runs **in parallel** with this spec.
**Executor:** Claude Code on Sonnet 4.6. §2–§5 require Sonnet; §0 / §1 are Haiku-safe.
**Conventions:** see `CLAUDE.md` (NAV/return + analytics blocks). Do not restate or override them.
**Architecture:** see `ARCHITECTURE.md` → *Analytics (functions over the return series)*.
**Naming:** capability-named, not numbered. Build order lives in `SCOPE.md`, not in this filename.

## Objective
Risk and risk-adjusted metrics over the monthly `ReturnSeries` derived via `returns/convert.py` (`to_returns(nav.month_end())`, cached on the Investment; persistence is spec-scale), validated **own-vs-oracle on frozen fixtures**. Metrics are pure free functions over `ReturnSeries`; `Investment` adapters read `.returns`; drawdown alone reads daily NAV. This layer assumes returns are **already present** (derived and cached on the Investment), never recomputed from NAV inside a metric — except drawdown, by design.

## Decoupling rule (load-bearing)
Analytics acceptance is **own-vs-oracle on a frozen fixture `ReturnSeries`** — never against the published figure, never against a live/in-flux series. This lets the analytics track run in parallel with return reconciliation and with spec-benchmarks without recoupling. Distinct from the return engine, which additionally carries the published leg.

## §0 — Pre-spec refactor (own commit, must land first)
§0 refactor landed on main; verified — `ReturnSource` carries `value_series` + `cashflows` only.

## In scope
- **`analytics/` package** — pure free functions over `ReturnSeries`; rf and benchmark passed as **`Investment`** args (never scalar params). Each returns a `MetricsResult`.
- **Self-contained metrics** (no benchmark): period absolute returns (1M/3M/6M/YTD, compounded from the monthly series; trailing 1Y/3Y/5Y/SI CAGRs remain the return engine's figures of record — the artifact references them, never recomputes), volatility (annualised √12), downside deviation, Sharpe, Sortino (MAR = rf), Calmar, rolling returns (monthly step; 1/3/5y windows), distribution stats (% positive periods, best/worst, skew, kurtosis).
- **Tail-risk metrics** — historical VaR and CVaR/expected shortfall at 95%, computed on daily returns (see §3); reported per-period, never annualised.
- **Drawdown family** — `max_drawdown` + duration + recovery, computed over **daily NAV** (read via `investment.source`), not the monthly series.
- **`Investment` adapters** — `sharpe_of(investment, rf)` etc.: read `investment.returns` (materialised) and delegate to the pure function.
- **`MetricsResult`** value object + the **metrics artifact** (`fund → {metadata, metrics, series}`) — serializable, versioned, shaped as the eventual API payload. The durable output contract consumed by the disposable renderer and, later, spec-api.
- **own-vs-oracle harness** — ffn (primary) / empyrical-reloaded (optional) on frozen fixture `ReturnSeries`; periodicity declared monthly.

## Out of scope — do not build
- **Benchmark-relative metrics** (excess return over periods, beta, Jensen's alpha, Treynor, R², tracking error, information ratio, up/down capture) — define signatures as stubs; implement at **§6**, gated on spec-benchmarks delivering rf + TRI. Do not fabricate a benchmark series to unblock.
- **Renderer** — superseded: rendering is owned by specs/spec-flexicap-page.md (pre-rendered SVG, no Plotly). spec-analytics ends at the metrics artifact.
- **Factor/regression alpha** (Carhart) — spec-factor; depends on the factor library + survivorship-free universe.
- **rf Investment data sourcing** — owned by spec-benchmarks. This spec consumes the rf Investment; it does not source it. (If spec-benchmarks lags, §2 can run against a frozen fixture rf series.)

## Conventions (all in `CLAUDE.md` — referenced, not restated)
Canonical monthly return = simple, month-end to month-end. Vol annualises √12; return annualises geometrically `(1+R)^(12/n)−1`. Sortino MAR = rf. Drawdown base = daily NAV. Rolling = monthly step, annual windows. rf = IIMA 91-day T-bill column. rf & benchmark are `Investment`s, not params. Benchmark return-variant (TRI/PRI) is part of identity; never PRI.

## Sub-steps (≈ one 45-min session each)
- **§1 — Wire `.returns` + rf fixture Investment** — Implement `ShareClass.returns` and `Fund.returns` as cached `to_returns(source.nav.month_end())` (functools.cached_property is fine — these classes are frozen dataclasses, use object-level caching that respects that). Accept: `.returns` returns a float64 ReturnSeries; NotImplementedError gone from both. Then wrap a frozen rf `ReturnSeries` as an `Investment` for test use (real sourcing is spec-benchmarks). *Accept:* rf series typed; consumed via the Investment contract; no live fetch.
- **§2 Pure core (no benchmark)** — `period_return_abs` (1M/3M/6M/YTD compounding over a `between` slice; built first), then `volatility`, `downside_deviation`, `sharpe`, `sortino`, `calmar` over `ReturnSeries`. *Accept:* own↔oracle ≤ 1e-6 on fixtures; functions never reference NAV. Series utilities land here: `align(a, b) -> tuple[np.ndarray, np.ndarray]` (inner join on dates) and `between(rs, start, end) -> ReturnSeries` (searchsorted slice) in analytics/series_ops.py; every two-series metric routes through align — no ad hoc pandas joins.
- **§3 Daily-basis family** — `max_drawdown`, duration, recovery, plus `var_historical` and `cvar` (95%), over daily NAV via `.source`. Pure functions are periodicity-agnostic over `ReturnSeries`; the adapter derives the daily series. *Accept:* own↔oracle ≤ 1e-6 (empyrical `value_at_risk` / `conditional_value_at_risk` as oracle); intra-month trough captured (daily, not month-end); VaR reported per-period, not annualised. Route through the seam: convert daily NAV via `to_returns(daily nav)` → `to_index`, compute drawdown on float levels. No direct Decimal→float cast outside returns/convert.py.
- **§4 Rolling + distribution** — rolling 1/3/5y (monthly step); % positive, best/worst, skew, kurtosis. *Accept:* window longer than history → no point emitted (empty young-fund panel is correct); own↔oracle where an oracle exists.
- **§5 Adapters + artifact** — `*_of(investment, …)` read `.returns`; `MetricsResult`; serialize the metrics artifact (versioned). *Accept:* artifact round-trips serialize→deserialize; deterministic; adapters compute nothing beyond delegation.
- **§6 — Benchmark-relative (gated on spec-benchmarks)** — excess return (fund minus benchmark, per period), beta, Jensen's alpha (CAPM regression intercept, monthly, vs TRI), Treynor, R², TE, IR, capture, hit rate (% months beating benchmark), rolling beta/correlation (monthly step, 1/3y windows — catches regime shifts and inconsistencies), taking a benchmark `Investment`. Alpha never ships as a naked point estimate: `MetricsResult` carries the t-stat and window alongside. *Accept:* own↔oracle ≤ 1e-6; benchmark passed as Investment; TRI variant only; alpha without t-stat fails the artifact schema.
- **§7 — Share-class & peer (gated on universe data)** — direct-vs-regular return gap (paired growth share classes under one Fund; the observable expense drag); peer percentile ranks within SEBI category (needs universe NAV panel from the backfill). Stubs until data lands; see `docs/dossier-design-notes-2026-07.md` §5.5.

## Acceptance — the gate
1. §0 refactor green; `ReturnSource` carries no risk method.
2. Every metric with an oracle counterpart: own↔oracle ≤ 1e-6 on frozen fixture `ReturnSeries`.
3. No metric recomputes returns from NAV **except** drawdown (which uses `.source` by design).
4. No analytics path reads a published or live series.
5. Metrics artifact serializes, versions, and re-runs identically.

## Executor guards
- Pure metric functions take `ReturnSeries`, never NAV — structural (drawdown is the one exception, via `.source`).
- Periodicity declared monthly to the oracle.
- rf and benchmark passed as `Investment`s; **no scalar rf** in any signature.
- Fixture inputs only; never published/live; never loosen the 1e-6 tolerance to pass.

## Dependencies
`ffn`, `empyrical-reloaded` (oracle), `numpy`/`pandas`. No new heavy dependencies.
