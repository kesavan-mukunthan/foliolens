# spec-benchmarks — Benchmark (TRI), scheme master, and risk-free ingestion

**Status:** ready for build; runs in parallel with spec-analytics §2–§5. Unblocks spec-analytics §6 and §7's peer universe.
**Executor:** Claude Code on Sonnet 4.6. All sub-steps Haiku-safe except §4 validation.
**Conventions:** see `CLAUDE.md`. Do not restate or override.
**Architecture:** ingestion writes, analysis reads via `data_access`; Decimal until `returns/convert.py`.

## Objective
Deliver three things so benchmark-relative metrics (spec-analytics §6) and the
peer universe (§7) consume them through existing contracts:
1. **Index levels** (TRI only) — figures of record, Decimal, landed like NAV.
2. **Scheme master** — universe-scale fund metadata derived from backfill shards.
3. **rf** — IIM-A 91-day T-bill monthly return series, wrapped as an Investment.

## Design decisions (settled — do not re-open)
- **Benchmark identity includes return variant.** TRI only; PRI is never
  ingested. `index_code` embeds the variant (`BSE500TRI`, `NIFTY500TRI`,
  `NIFTY50TRI`).
- **A fund without a benchmark is ontologically invalid** (SEBI two-tier
  mandate). `Fund.benchmark` stays `Investment | None` for construction over
  partial curation, but `None` means *mapping not yet curated*, never *has no
  benchmark*. Benchmark-relative metrics fail loud on `None`; no default is
  ever silently applied.
- **Fund→benchmark mapping is a curated fixture.** No machine-readable source
  exists (AMC SID/factsheets only). `fixtures/benchmark_map.csv`:
  `amfi_code, benchmark_code, tier` (`tier ∈ {tier1, alternate}`). Hand-built
  per cohort; flexicap first (~40 schemes). Note the flexicap category splits
  between BSE 500 TRI and NIFTY 500 TRI by AMC — one index per category is
  wrong by construction.
- **Storage separates provenance; the read joins.** Machine-derived
  `scheme_master.parquet` and hand-curated `benchmark_map.csv` are separate
  artifacts (different update mechanics, error modes, audit trails). The
  canonical metadata surface is the join, exposed as one read
  (`load_scheme_master`); consumers never see the two files.
- **Scheme master is derived from backfill shards** during `consolidate()` —
  each `{amfi_code}.json.gz` retains the full mftool response (scheme_name,
  fund_house, category). No refetch. Plan/option parsed from scheme names by
  convention regex; unparsed rows flagged NULL, never guessed.
- **Separate index dataset, same pattern.** `index_nav.parquet`
  (`index_code, date, level decimal128(18,6)`), single sorted file. Never
  mixed into fund `nav.parquet`.
- **`NavSeries` is reused for index levels**, identifier field carrying
  `index_code`. No new series type; renaming to `series_code` is a possible
  future refactor, not part of this spec.
- **Benchmark = `Investment` with `PricedSource(index NavSeries)`** —
  `.returns` works unchanged via `to_returns(levels.month_end())`.
- **rf is a return series, not a level series.** IIM-A publishes returns; it
  never passes through `to_returns`. Promote the test-fixture pattern to
  `model/`: `SeriesInvestment` wrapping a materialised `ReturnSeries`. This is
  the one sanctioned non-NAV float entry besides `ValueIndex`; document at the
  class.
- **Sourcing is manual-download-first.** niftyindices.com (NIFTY TRI) and
  bseindia.com archives (BSE 500 TRI): saved CSV → normaliser → land. Scraper
  automation out of scope; both sites are bot-protected.
- **No index-fund-NAV proxies** (embeds tracking drag).

## In scope
- `scheme_master.parquet` derivation in `consolidate()`:
  `amfi_code, scheme_name, fund_house, scheme_category` (raw AMFI string),
  `sebi_category` (normalised, e.g. `flexi_cap`), `plan`, `option`.
- `fixtures/benchmark_map.csv` (flexicap cohort) + typed loader; duplicate
  `(amfi_code, tier)` rejected.
- `data_access.load_scheme_master() -> pa.Table` — scheme_master ⟕
  benchmark_map on `amfi_code`; adds `benchmark_code`, `benchmark_tier`;
  NULL benchmark_code = not yet curated.
- `ingest/index_normalise.py` — per-source parsers (niftyindices CSV, BSE
  archive CSV) → `IndexRecord(index_code, date, level: Decimal)`.
- `land_index(records) -> index_nav.parquet` (sibling of `land`).
- `data_access.load_index_series(index_code) -> NavSeries`.
- Benchmark `Investment` construction; `SeriesInvestment` for rf; canonical
  `rf_investment()` accessor in `src` (tests swap to the same class).
- IIM-A parser: 91-day T-bill column → monthly `ReturnSeries` (float64 at
  birth; the convert seam does not apply — already return-space).
- Validation: computed 1Y/3Y/5Y index CAGRs vs NSE/BSE published figures,
  ≤ 10 bps (same discipline as the fund return engine).

## Out of scope — do not build
- Scheduled/automated index or metadata fetch (later ops spec).
- PRI variants; any non-TRI series.
- Factor columns beyond rf (MRP/SMB/HML/WML) — spec-factor.
- Benchmark-relative metrics — spec-analytics §6.
- Universe-wide benchmark_map coverage — grows cohort by cohort.
- Expense ratio, AUM, or any other metadata field not listed above.

## Sub-steps (≈ one 45-min session each)
- **§1 Scheme master** — derive from shards in `consolidate()`; category
  normaliser + plan/option name parser (flagged, not guessed). *Accept:*
  row per shard; known flexicap schemes classify `flexi_cap`; unparsed
  plan/option are NULL not wrong.
- **§2 Mapping fixture + joined read** — `benchmark_map.csv` for flexicap
  cohort hand-verified against AMC factsheets (Bandhan Flexi Cap →
  `BSE500TRI` tier1, `NIFTY50TRI` alternate); loader; `load_scheme_master`
  join. *Accept:* round-trips; duplicates rejected; NULL semantics correct.
- **§3 Index landing** — normalisers for both source CSV shapes;
  `land_index`. *Accept:* decimal128 end-to-end; idempotent overwrite;
  sorted (index_code, date).
- **§4 Read + validate** — `load_index_series`; benchmark Investment;
  own-vs-published CAGR on BSE 500 TRI and NIFTY 500 TRI. *Accept:* ≤ 10 bps;
  `.returns` yields monthly float64 series.
- **§5 rf** — IIM-A parse → monthly rf `ReturnSeries`; `SeriesInvestment`
  promoted from test fixture; `rf_investment()` in src. *Accept:* typed;
  consumed via Investment contract; fixtures swapped to same class.

## Acceptance — the gate
1. Bandhan Flexi Cap resolves to a benchmark Investment via
   `load_scheme_master` with no special-casing.
2. Index CAGRs reconcile with published ≤ 10 bps.
3. No PRI anywhere; TRI encoded in every `index_code`.
4. rf reaches metrics only as an `Investment`; no scalar rf.
5. `nav.parquet` untouched; scheme_master derivation makes no network calls.

## Executor guards
- Missing mapping fails loud; never default a benchmark.
- No Decimal→float outside `returns/convert.py` except the documented rf entry.
- Parsers take local files. One-time locally-run acquisition aids are permitted outside the pipeline (see SCOPE acquisition-aid amendment); no scraping in pipeline code, no scheduled/CI fetching.
- Name-parse ambiguity → NULL + flag, never a guess.

## Dependencies
None new. (openpyxl only if the IIM-A file is xlsx.)
