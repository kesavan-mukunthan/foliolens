# spec-scale — universe ingestion at scale

Status: ingestion sections (§1–§6) are the FL-ING-1 contract. §7 (GCS
swap, scheduled jobs) is queued for the after-F block and is recorded
here as scope, not contract.

## §1 Two-mechanism NAV design

Steady-state freshness and universe discovery come from AMFI's daily
NAVAll.txt — one file, every scheme AMFI prices, latest NAV + ISINs.
mfapi (via mftool) is used selectively, in exactly two cases:
first-sight backfill of a newly discovered scheme's full history, and
deliberate correction refetches (AMC restatements). There is no runtime
source selection: sources are fixed per pipeline stage and meet only in
the panel union (§4). Decided 2026-07; recorded here per the
live-repo-is-source-of-truth rule.

## §2 navall module contract (src/foliolens/ingest/navall.py)

- fetch_navall(date: date | None) -> str: one GET; current file when
  date is None, historical file via AMFI's date parameter otherwise.
  Raises on any network fault (never returns None for flakiness —
  same stance as fetch_nav_history).
- land_navall_raw(text, date, data_dir) -> Path: writes
  daily/YYYYMMDD.txt.gz verbatim. LAND-ONCE: an existing dated file is
  never overwritten by default; catch-up fetches absent dates only.
  force=True moves the prior file to
  daily/YYYYMMDD.txt.gz.superseded-<UTC-timestamp> and logs the event.
  Landed dailies are evidence, same contract as raw shards.
- parse_navall(text) -> list[NavRecord]: pure function; semicolon
  format; nav parsed straight to Decimal, no float intermediate;
  non-scheme lines (section headers, blanks) skipped.
- new_codes(data_dir, parsed) -> set[str]: codes present in the parsed
  file with no shard in raw/. Feeds land_universe as its code list.
  NAVAll is the universe primitive; fetch_scheme_codes is retired from
  the landing path (retained only if a cross-check is later wanted).

Verify-at-fixture (observed file wins over this spec): historical
retention depth, and format drift in old vintages. If observed files
disagree with §2, amend this spec in the implementation PR.

## §3 Panel assembly

consolidate() gains a union step. merge_panel(shard_records,
daily_records) -> list[NavRecord]: union keyed (amfi_code, date).
A key present once passes through. A key present in both layers with
equal nav deduplicates silently. With differing nav: latest-landed
wins, and the override is logged (§4) — silence in either direction is
prohibited. This generalises normalise()'s within-shard duplicate rule
(newest occurrence kept) across layers.

## §4 Override log

Append-only CSV in the data dir (overrides.csv), one row per differing
(code, date): amfi_code, date, nav_kept, nav_overridden, source_kept,
source_overridden, landed_at_kept, landed_at_overridden, run_id.
Equal-value dedups are not logged. Every rebuild reports the override
count; steady-state expectation is zero except following a correction
refetch, which is when the log is the restatement record.

## §5 land() backup

land() moves an existing nav.parquet to nav.parquet.bak-<UTC-timestamp>
before writing. The no-rewrite-without-backup rule moves from runsheet
procedure into code. .bak files are user-owned; nothing deletes them.

## §6 Failure taxonomy (universe.py)

failed_codes entries split by reason into transient (exception:
network/timeout — retried automatically on the next run) and
validated-absent (mftool returned None on HTTP 200 — skipped on resume,
as today; retry only via retry_failed=True). A scheduled run must
neither hammer dead codes nor abandon live ones after one bad night.

## §7 Queued scope (after-F, not FL-ING-1)

GCS as parquet home behind DataAccess; nightly Cloud Run Job +
Cloud Scheduler for the NAVAll append (WSL2 cron acceptable as an
explicitly temporary stopgap); correction runsheet written on first
need per the pending-instructions convention; mfapi-vs-NAVAll active
audit (FL-DQ-3 candidate); incremental parquet append (full rebuild
stands until it hurts).
