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

**rf carry-forward** (`ingest.iima.extend_rf`): when the IIM-A source lags a cohort run's `as_of`, rf extends flat at its last published value, capped at 12 months — beyond the cap the pipeline fails rather than silently extending a stale source further. Every extension is disclosed on-page with its provenance (last published month, months carried, basis); the disclosure escalates to stronger wording once the carry exceeds 6 months. Carried points are computation-only — never persisted back to the rf store, so a subsequent IIM-A refresh self-heals with no cleanup.

Series never join or substitute across frequencies; scalars derived from different frequencies may combine only where this spec explicitly says so (e.g. Calmar: daily-base max drawdown against monthly-convention CAGR).

**Common as_of anchoring for cross-sectional runs:** a batch run over a cohort (e.g. `report.flexipage.runner.run`) derives one shared `as_of` — the latest calendar month-end emitted by at least half of the cohort's MONTHLY panels — and every fund's fixed-window metrics (sub-year period returns, YTD, 1Y/3Y/5Y) are measured ending exactly at that shared date, never at the fund's own last month. A fund whose panel does not reach the shared `as_of` (a stale fund lagging the rest of the cohort) emits `null` for those metrics via the existing null-propagation path — it never silently falls back to its own last month, which would make its figures measured over a different, incomparable window than its peers'. `SI` (since-inception) is the one metric family that is *not* anchored: it reports the fund's own full history regardless of the cohort's `as_of`. `analytics.artifact.build_metrics`'s `as_of` parameter defaults to the investment's own last date when omitted (single-fund use, unaffected by this rule); the rule only engages when a caller supplies an explicit shared `as_of`.

**Windows are calendar-date slices.** The sub-year 1M/3M/6M period returns and the trailing 1Y/3Y/5Y windows (`analytics.artifact._trailing`), and the rolling 1/3/5y windows (`analytics.rolling.rolling_return`), are sliced from the anchor by **calendar date** — the panel entries dated within `(anchor − N months, anchor]`, lower bound via a shared day-clamped subtraction (`analytics.rolling._subtract_months` for the trailing/period slices, the engine's Feb-29-clamped `_subtract_years` for the rolling step, one clamp convention) compared at month granularity so the boundary month is excluded whole — **not** the last `N` observations. On a contiguous panel the two coincide (`N` observations = `N` calendar months); on a panel with a data hole (rejected/truncated months) last-N would reach back across the hole and stretch the window past `N` calendar months, so a metric and the rf/benchmark legs it reconciles against would cover different periods. A window's **expected** length is `N` months; its **actual** length is whatever survives inside the calendar span. Refusal semantics are unchanged: the young-fund null contract (fewer than the nominal observations → no window) still holds, and the downstream metric's own minimum-observation guard decides on the truthful surviving count (a window too sparse to compute refuses via the `refused` disclosure, never pads and never stretches to reach a count). Only sub-year *rolling* windows keep observation-slicing — `rolling_return` steps by whole years and a sub-year rolling window has no whole-year boundary to slice against.

## Sub-steps (≈ one 45-min session each)
- **§1 — Wire `.returns` + rf fixture Investment** — Implement `ShareClass.returns` and `Fund.returns` as cached `to_returns(source.nav.month_end())` (functools.cached_property is fine — these classes are frozen dataclasses, use object-level caching that respects that). Accept: `.returns` returns a float64 ReturnSeries; NotImplementedError gone from both. Then wrap a frozen rf `ReturnSeries` as an `Investment` for test use (real sourcing is spec-benchmarks). *Accept:* rf series typed; consumed via the Investment contract; no live fetch.
- **§2 Pure core (no benchmark)** — `period_return_abs` (1M/3M/6M/YTD compounding over a `between` slice; built first), then `volatility`, `downside_deviation`, `sharpe`, `sortino`, `calmar` over `ReturnSeries`. *Accept:* own↔oracle ≤ 1e-6 on fixtures; functions never reference NAV. Series utilities land here: `align(a, b) -> tuple[np.ndarray, np.ndarray]` (inner join on dates) and `between(rs, start, end) -> ReturnSeries` (searchsorted slice) in analytics/series_ops.py; every two-series metric routes through align — no ad hoc pandas joins.
- **§3 Daily-basis family** — `max_drawdown`, duration, recovery, plus `var_historical` and `cvar` (95%), over daily NAV via `.source`. Pure functions are periodicity-agnostic over `ReturnSeries`; the adapter derives the daily series. *Accept:* own↔oracle ≤ 1e-6 (empyrical `value_at_risk` / `conditional_value_at_risk` as oracle); intra-month trough captured (daily, not month-end); VaR reported per-period, not annualised. Route through the seam: convert daily NAV via `to_returns(daily nav)` → `to_index`, compute drawdown on float levels. No direct Decimal→float cast outside returns/convert.py.
- **§4 Rolling + distribution** — rolling 1/3/5y (monthly step); % positive, best/worst, skew, kurtosis. *Accept:* window longer than history → no point emitted (empty young-fund panel is correct); each window is a calendar-date slice of its anchor's `W`-year span (not the last `12×W` observations — see *Windows are calendar-date slices* above); own↔oracle where an oracle exists.
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
