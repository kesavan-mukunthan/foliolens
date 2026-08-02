# Working board

Authoritative working state between sessions. Updated by rider commits as
items land. Newer than project memory; older than an open PR — when this
file and an open PR disagree, the PR wins.

_Last updated: 2026-08-02 (PR 54 merged)._

## In flight

(none — next: FL-IO-1, queue item 1)

## Queue (fire order; one slot per landed item)

1. **FL-IO-1** — decimal128 assertion at read (`data_access.py`). Gates the
   GCS move. Sonnet-cloud OK.
2. **FL-ING-1** — incremental ingest keyed (code, date) + failed_codes
   split transient/permanent. Gates scheduled jobs. Opus.
3. **F-TER stages 1–2** — after stage-0 confirmation. Opus; backfill local.
4. **FL-CAL-3** — sub-year returns point-to-point via the return engine. Opus.
5. **FL-CAL-4** — calendar provenance in artifact + widened derivation base
   for thin cohorts.
6. **FL-ART-1** — `as_of` required in `build_metrics`; single-fund default
   moves to the caller.
7. **FL-TOOL-1** — `[tool.ruff]` config + resulting cleanup. **Last, alone**
   (repo-wide diff; conflicts with everything open).

## After F (agreed order)

Docs pass (full spec reconciliation) → multi-category (large-cap first;
benchmark curation is the real per-category work; FL-DQ-2 gates debt) +
category landing page → GCS move (FL-IO-1 first; repoint the DataAccess
seam; Drive stays cold copy) → scheduled jobs (Cloud Run Jobs + Scheduler;
the publish job runs the full gate — identities + reconciliation — before
any push; niftyindices stays local unless probed otherwise).

## Standing rules (chat-derived, now written down)

- Live repo before design (CLAUDE.md inventory rule); project-mounted docs
  are stale scratch.
- Manifests carry exact branch names but cloud runs suffix them
  (`claude/…-xxxxxx`) — get the real name from the PR page; unauthenticated
  API lookups rate-limit on shared egress IPs.
- Red tests before fixes; no tolerance widens without adjudication; STOP
  conditions are terminal, not pauses (F-TER stage 0 in particular).
- Nothing rewrites the local parquet without a current backup; every merge
  is a human click (review-required protection).
- Model split: runsheet-flavoured tasks Sonnet, design-surface tasks Opus.
- Runsheets in `docs/runsheets/` are pending instructions; each is deleted,
  and its board line moved to Done, by the PR that closes its item.

## Loose ends (no deadline)

- Manager-tenure CSV — 39 rows, hand-curated, source-dated.
- IIM-A H1-2026 rf refresh when published (carry-forward self-heals; cap 12
  months, escalated disclosure past 6).
- Fixture enrichment with 119718 at next re-freeze (FL-FIX-1).
- Docs riders: inception-date contract paragraph rides F-TER stage 1.
- Commentary v6: prompt rule — no aggregated percentile claims unless every
  covered figure matches (149450 finding); optional 149450 re-roll rides
  any local sitting.

## Done

- **FL-DQ-2** — hole-month audit closed 2026-08-02. Artifact:
  `docs/audits/hole-months-2026-08.csv`. 3,711 hole-months across 228/7,913
  funds. All 228 upstream (fetch_side = 0). Step-5 spot-check (seed=42,
  n=12): 10 still-absent, 2 API timeouts, 0 now-present — threshold not
  triggered. Local (shard corpus is the classification evidence).
  FL-ledger open/closed convention (rides this PR): FL backlog lines in
  SCOPE.md are origin records and are never edited; live status lives on
  this board. An FL item is open while its queue line exists here; the PR
  that lands it deletes the queue line and writes the Done entry — same
  discipline as runsheet deletion.
- **E — commentary v5 + publish + scheme-master rebuild** — closed
  2026-07-30 on review acceptance; site commit `fc48f79`; 38/39 populated
  (120492 deterministic); scheme-master inception 100%/0 violations.
- **F-TER stage 0** — closed 2026-07-30, `OBSERVED`:
  `docs/ter-aaum-source-verification-2026-07.md`. Local re-run (real AMFI
  files) supersedes the cloud sandbox's egress-blocked `[INDEXED]` attempt
  and overturns two of its claims — scheme-level (`amfi_code`) AAUM *is*
  sourceable from AMFI's central page (per-AMC selection, not a separate
  "individual AMC" page), and that page is quarterly, not monthly. Also
  found: TER disclosed daily, and every TER file's footer disclaimer is
  static post-2026 boilerplate regardless of the file's own regime — never
  infer methodology from the footer. Open items before Stage 1: re-run the
  lost scheme-wise dropdown-label probe, confirm a missing AAUM industry
  quarter, decide the AAUM per-AMC ingestion shape, and keep/discard the
  10 extra TER months pulled beyond stage-0 scope. Adjudicated post-close:
  AAUM = per-AMC scheme-wise quarterly, aaum.parquet(amfi_code, quarter,
  aaum), universe AMCs only; industry file not ingested; 10 extra TER
  months kept for stage-2 fixtures/backfill; dropdown probe + missing
  industry quarter fold into stage 2; browser-automation acquisitions
  must report selections before session end.
