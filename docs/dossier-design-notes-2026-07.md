# Fund Dossier & Analytics — Design Notes

*Source: manager-selection literature review (Jul 2026) — Stewart, Ang, Ilmanen and the papers in §4 — applied to FolioLens. Purpose: update scope, invariants, and build priorities; define the per-fund dossier deliverable.*

---

## 1. Context

FolioLens's per-fund analytical deliverable (the **fund dossier**) sits on two data foundations that most retail-facing fund material lacks: the fund's own NAV return history (fees, peers, real performance) and its holdings time series (positioning, risk structure, manager behaviour). These notes record what the dossier should contain, the correctness laws any LLM-generated analytical narrative must obey, and the resulting scope changes.

A general caution from the record itself: scheme histories in India are segmented by manager changes, AMC ownership changes, and SEBI events (direct plans exist only from Jan 2013). *Whose* skill a long-window alpha measures is ambiguous unless every rolling metric segments at these dates — hence the manager-tenure table in §5.3.

## 2. Dossier capabilities to build

- **Falsifiable prediction registry** — dated, binary, no-partial-credit predictions tied to theses, reviewed every edition. The pre-registration discipline already adopted for Phase 3 validation, applied to monitoring.
- **Days-to-liquidate (DTL) analysis** — position ÷ 20% of 60d ADV (standard buy-side participation convention), per holding; AUM-multiple capacity stress; pro-rata vs waterfall redemption profiles (waterfall selling concentrates the residual book into the illiquid tail).
- **Effective Number of Bets chain** — holdings count → effective stocks (1/HHI) → correlation-adjusted ENB (Meucci entropy on PCA of the covariance matrix) → stress-regime ENB. Each step removes an illusion of diversification. Requires covariance shrinkage first (§4).
- **Corporate-family exposure roll-up** — group-level concentration invisible to sector views; highly India-relevant (promoter groups, group-contagion episodes); absent from US-centric frameworks.
- **Cross-dependency analysis** — internal contradictions (long a supplier while short its customers) and hidden shared-input concentrations (monsoon, semiconductors, single-policy clusters), tagged intentional/accidental.
- **Counter-evidence rows in every thesis** — deliberate disconfirmation retrieval, not confirmation-only sourcing.
- **Revealed-preference reading of trades** — a large add against a stated structural underweight is the manager contradicting their own thesis; trades outrank commentary.
- **Attention-allocation metric** — analyst attention should be proportional to alpha at stake; zero-holds can cost multiples of the most-debated active positions and go undiscussed.

## 3. Correctness laws for LLM-generated analytical narrative

Anti-patterns any compute-then-narrate pipeline is prone to; each is banned by an invariant in §5.1.

1. **Backcast presented as performance.** Current weights × past returns is positioning/risk analysis, not fund performance — and a *biased* estimator of realised returns (bias direction set by trading style: contrarian adds overstate backcast losses). Belongs in a risk section labelled prospective; NAV owns performance.
2. **"Alpha" mislabelling.** Raw active-return contributions are not alpha — no risk adjustment, never actually delivered. Precise-sounding jargon on unsound numbers is worse than no number.
3. **Unreproducible derived figures.** Any derived statistic must reproduce from a stated formula on stated inputs. Rule: *define it, reproduce it, or delete it.*
4. **Per-section generation without a global validator.** Independently generated sections contradict each other (a reported beta inconsistent with the two vols it implies; counts that differ between sections; a holding labelled improving in one section and top-risk in another). A cross-section consistency pass must run before render.
5. **Provenance overclaiming.** Extrapolated calendar dates presented as verified; theses inferred from weights presented as the manager's stated worldview; computed regression sensitivities and freehand LLM ranges mixed in one table format.
6. **Non-partitioned attribution.** Overlapping narrative buckets double-count holdings; contributions that cannot reconcile to total active return; no unexplained-residual row. Attribution requires a MECE partition and an accounting identity.
7. **Self-referential accountability.** Predictions that test the engine's own reconstructed theses rather than manager-stated commitments; predictions outliving the positions that motivated them (no VOID status).
8. **Missing the object of evaluation.** No fees/TER, no direct-plan NAV, no manager identity/tenure, no peer or passive comparison. Distributor-audience material systematically omits these (Ang's agency lens: fee analysis works against the channel); a selection tool cannot.
9. **Statistical dishonesty by omission.** No t-stats or error bars; one-year windows treated as verdicts; an N×N covariance estimated from ~T≈N daily observations with no shrinkage (severe eigenvalue dispersion); false precision throughout.

## 4. Core methods (with references)

| Method | Use in FolioLens | Reference |
|---|---|---|
| Active share + tracking error 2×2 (stock picker / factor bettor / closet indexer) | Classify funds; endogenous benchmark = index minimising active share (kills self-declared-benchmark gaming); fee-per-unit-active-share (TER ÷ active share) | Cremers & Petajisto (2009), *RFS* 22(9) — https://doi.org/10.1093/rfs/hhp057 ; Petajisto (2013), *FAJ* — SSRN: https://ssrn.com/abstract=1685942 |
| Holdings-implied returns; weight-change × subsequent return as skill measure | Trade event studies (per-decision skill, no factors needed) | Grinblatt & Titman (1989), *J. Business* 62(3); Grinblatt & Titman (1993), *J. Business* 66(1) |
| **Return gap** = actual NAV return − holdings-implied return; persistent, predictive; captures fees, interim trading, window-dressing | Highest-value first computation once NAV + holdings both exist | Kacperczyk, Sialm & Zheng (2008), "Unobserved Actions of Mutual Funds," *RFS* 21(6) — https://doi.org/10.1093/rfs/hhl041 |
| Brinson allocation/selection attribution; requires MECE partition + reconciliation to total | Holdings-based attribution (chain-linked monthly weights, never one snapshot); accounting-identity constraint on any narrative decomposition | Brinson, Hood & Beebower (1986), *FAJ* 42(4) |
| Effective Number of Bets via PCA entropy | Fund- and user-portfolio-level diversification (how many independent bets across a multi-fund portfolio) | Meucci (2009), "Managing Diversification," *Risk* — SSRN: https://ssrn.com/abstract=1358533 |
| Covariance shrinkage (blend sample matrix toward structured target, data-driven intensity) | Precondition for any PCA/ENB on N large vs T; `sklearn.covariance.LedoitWolf` | Ledoit & Wolf (2003) *J. Empirical Finance*; (2004) "Honey, I Shrunk the Sample Covariance Matrix," *J. Portfolio Mgmt* — http://www.ledoit.net/honey.pdf |
| Random-matrix (Marchenko–Pastur) eigenvalue filtering | Alternative covariance cleaning; flatten eigenvalues inside the noise band | Marchenko & Pastur (1967); application: Laloux, Cizeau, Bouchaud & Potters (1999), *PRL* 83 |
| Returns-based style analysis (constrained regression on index returns) | Style mix + style-adjusted residual using only investable NSE indices — the honest "alpha" without factor portfolios | Sharpe (1992), "Asset Allocation: Management Style and Performance Measurement," *J. Portfolio Mgmt* 18(2) — https://web.stanford.edu/~wfsharpe/art/sa/sa.htm |
| Fired-vs-hired manager performance (firing on performance destroys value) | Exit rules keyed to *change vs hire-time thesis*, not raw performance | Goyal & Wahal (2008), *J. Finance* 63(4) — https://doi.org/10.1111/j.1540-6261.2008.01375.x |
| Significance arithmetic: t = alpha/(TE/√years); confirming 2% alpha at 6% TE needs ~36 years | Mandatory error bars / t-stats on all alpha claims; one-year windows never produce verdicts | Stewart (project text) Ch 2/6; Ang (project text) Ch 10 |
| Carhart 4-factor for India | Already sourced: IIM-A Indian Factor Library (MRP/SMB/HML/WML, monthly, 1994–present; equity categories only; not redistributable) — https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/ | Agarwalla, Jacob & Varma (IIM-A) |

**Correction recorded:** the "no factor data for India" premise was wrong — IIMA covers returns-based factor work. The real constraints are holdings-based factor attribution (PIT characteristics) and redistribution licensing.

## 5. Decisions / instruction changes for the FolioLens project

### 5.1 New invariant class (add to CLAUDE.md): LLM-output verification
The numeric layers gate on tests; narrative layers must gate on the equivalent. Pipeline is **compute → write → verify**, with the verifier authorised to block claims:
- **Provenance tag on every claim:** `computed` (formula stated, reproducible) / `quoted` (source + date) / `inferred` (engine hypothesis, labelled as such).
- **Reconciliation invariant:** any narrative decomposition (thesis buckets, contribution stories) must partition (each holding in exactly one bucket, or fractional weights summing to 1) and reconcile to an accounting identity with an explicit unexplained-residual row.
- **Cross-section consistency pass** before render: same fund, no contradictory readings (beta vs vols, counts, tone vs risk labels).
- **Uncertainty attaches to numbers or decimals are dropped.** t-stats/error bands on alpha-like quantities; regime-conditioned estimates flagged as such.
- **Derived-figure rule:** define it, reproduce it, or delete it.

### 5.2 spec-holdings — expand scope
Beyond DAG/look-through/attribution, the holdings *time series* carries the differentiating analytics:
- Trade event studies (adds/trims → subsequent 3/6/12m relative returns); manager reaction to catalysts and to adverse prediction resolutions (behaviour under disconfirmation).
- Active share vs multiple benchmarks (endogenous-benchmark check: if a narrower index yields lower active share than the declared benchmark, the fund is misbenchmarked); active-share and concentration trajectories (closet-index / style drift detection).
- Concentration battery: top-N, HHI/effective stocks, ENB (post-shrinkage), all rendered against peer distributions — "concentrated" is undefined until statistic + comparator are named.
- Return gap (KSZ 2008) once NAV + holdings coexist.
- Thesis-stability measurement: median half-life of inferred themes across monthly snapshots (if ~2 months, the worldview layer is fitting noise).

### 5.3 New reference tables
- **Promoter-group taxonomy** (security-master extension): `group_id`, `group_type` ∈ {promoter-controlled, professional-ecosystem (weaker contagion channel), PSU (common owner GoI), MNC-parent}. Seeded from quarterly shareholding-pattern disclosures; LLM for offline entity resolution only; versioned; manual override; quarterly diff-and-flag refresh. Enables fund-level and **cross-fund group exposure** (a user's four funds may unknowingly stack 15%+ in one group — invisible to per-fund factsheets).
- **Manager-tenure table:** manager identity, start/end dates per fund, AMC ownership events. Every rolling metric segments at these dates; track records attach to managers, not schemes.

### 5.4 spec-monitor — linked schema (five objects, foreign keys)
`position ↔ thesis ↔ prediction ↔ event ↔ trade/reaction`:
- Thesis carries state: ACTIVE / WEAKENING / ABANDONED, updated from monthly holdings + three evidence streams (trades, prices, manager tone). Stream disagreements are surfaced signals, not editorial problems.
- Prediction resolves PASS / FAIL / PENDING / **VOID-BY-POSITION-CHANGE**; each row pre-commits an "if FAIL then…" consequence at creation (else accountability is theatre).
- Predictions anchor on manager-stated views where available (factsheet commentary, AMC outlook notes, scheme ARs, interviews — a date-versioned corpus; fits the existing RAG design); engine hypotheses explicitly labelled. Handle thin corpora (new managers) gracefully.
- Events (earnings, MPC, AMC portfolio-disclosure dates — include fund-level events) link to the predictions they resolve; post-event holdings diff feeds manager-reaction profile.
- Scenario axes generated from the portfolio's dominant risk directions (PCA components), with newsflow overlays second — not headlines first.

### 5.5 spec-analytics — additions
- Peer percentile ranks within SEBI category (category NAVs already in the mftool universe).
- RBSA (Sharpe 1992) against spec-benchmarks indices; complements IIMA Carhart, covers its equity-only boundary.
- Returns battery: rolling active return, TE, IR, hit rate, up/down capture, drawdown profile, rolling beta/correlation (a consistency check on any reported beta), direct-vs-regular gap. One rolling-window engine, many projections.

### 5.6 Data gaps to add to Unsourced
- **Stock daily price/return series** — required for ENB/PCA, trade event studies, DTL (with traded value); bhavcopy provides but the spec never claims it.
- **Benchmark constituents** — now also block active share, not just relative monitoring; priority raised.
- **Expense ratio** — resolve the open question in favour of early sourcing: fees are the only zero-variance input; fee-per-unit-active-share is a headline selection metric.
- (Optional) ADV percentile series for conservative DTL (20th-percentile daily traded value rather than 60d mean).

### 5.7 Framing principles (carry into product copy and NL layer)
- Separate **positioning analysis** (what the fund is) from **skill evaluation** (how it has done); hold the latter to the higher evidentiary standard.
- Hold/buy/sell share one scoring engine plus a friction overlay (tax, exit load — asymmetric hurdles) plus a change-detection overlay (fire on change vs hire-time thesis, per Goyal–Wahal, not on raw performance).
- Category prior first: a fund's expected alpha starts at the SPIVA India category base rate net of fees, not at zero.
- Every percentage states its denominator; every comparison names its comparator (benchmark vs peers can flip the adjective).
- LLM groupings are presentation-layer only, sitting on a deterministic layer that forces partition, reconciliation, and persistence.
