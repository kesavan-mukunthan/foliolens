"""Resumable universe NAV landing.

Fetches every AMFI fund from mftool, writing one gzipped raw shard per
fund to data_dir/raw/{amfi_code}.json.gz. An existing shard is skipped —
re-run to resume. Failed codes (network error or None response) are
appended to data_dir/failed_codes.txt.

After shards are present, consolidate() reads them all and calls land()
to produce data_dir/nav.parquet.

CLI: python -m foliolens.ingest.universe --data-dir PATH [--consolidate]
     python -m foliolens.ingest.universe --data-dir PATH --shard i/N  (parallel worker)
"""
from __future__ import annotations

import gzip
import json
import logging
import time
from pathlib import Path
from typing import Any, cast

from .land import land
from .mftool_client import fetch_nav_history, fetch_scheme_codes, normalise
from .scheme_master import SchemeMasterRecord, land_scheme_master, scheme_record

_LOG = logging.getLogger(__name__)

_BACKOFF: tuple[float, ...] = (2.0, 8.0, 32.0)

# A None response gets one cheap retry rather than the exception ladder above —
# see the rationale in land_universe's fetch loop.
_NONE_RETRIES = 1
_NONE_BACKOFF_S = 2.0


def list_scheme_codes() -> list[str]:
    """Sorted, de-duplicated AMFI scheme codes from mftool."""
    return fetch_scheme_codes()


def _shard_path(data_dir: Path, amfi_code: str) -> Path:
    return data_dir / "raw" / f"{amfi_code}.json.gz"


def _write_shard(path: Path, raw: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(raw, f)


def _read_shard(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return cast(dict[str, Any], json.load(f))


def _append_failed(data_dir: Path, amfi_code: str, reason: str) -> None:
    with open(data_dir / "failed_codes.txt", "a") as f:
        f.write(f"{amfi_code}\t{reason}\n")


def _read_failed(data_dir: Path) -> set[str]:
    """Codes already recorded as failed by a previous run.

    Most failures are wound-up or merged schemes that AMFI's historical-NAV
    endpoint does not serve at all, so re-attempting them costs the full retry
    backoff to re-learn the same answer. They are part of the resume state;
    ``retry_failed=True`` forces a fresh attempt.
    """
    path = data_dir / "failed_codes.txt"
    if not path.exists():
        return set()
    return {
        line.split("\t", 1)[0].strip()
        for line in path.read_text().splitlines()
        if line.strip()
    }


def land_universe(
    data_dir: Path,
    *,
    delay_s: float = 0.75,
    max_retries: int = 3,
    shard: tuple[int, int] | None = None,
    retry_failed: bool = False,
) -> None:
    """Fetch every AMFI fund NAV and write one gzipped raw shard per fund.

    Existing shards are skipped — re-running resumes where a prior run stopped.
    Failed codes are recorded in data_dir/failed_codes.txt. Never raises.

    ``shard`` partitions the code list for parallel workers: ``(i, n)`` runs
    worker ``i`` of ``n`` (0-indexed), taking every ``n``-th code (``codes[i::n]``).
    Workers write disjoint shards into the same data_dir safely.
    """
    codes = list_scheme_codes()
    if shard is not None:
        i, n = shard
        codes = codes[i::n]
    already_failed: set[str] = set() if retry_failed else _read_failed(data_dir)
    if already_failed:
        _LOG.info("skipping %d previously-failed codes", len(already_failed))
    total = len(codes)
    done = 0
    failed = 0

    for amfi_code in codes:
        shard_path = _shard_path(data_dir, amfi_code)
        if shard_path.exists() or amfi_code in already_failed:
            done += 1
            if done % 100 == 0:
                _LOG.info("progress: %d/%d done, %d failed", done, total, failed)
            continue

        time.sleep(delay_s)

        raw: dict[str, Any] | None = None
        last_exc: BaseException | None = None
        none_attempts = 0
        for attempt in range(1 + max_retries):
            try:
                raw = fetch_nav_history(amfi_code)
                last_exc = None
                if raw is not None:
                    break
                # None now means a *validated* absent scheme: fetch_nav_history
                # only returns None on an HTTP-200 response carrying empty data,
                # and raises (not None) on any network/timeout fault, so a None
                # here is a stable per-code verdict rather than swallowed flakiness.
                # (An earlier comment claimed "roughly half the universe is dead,
                # 0/10 recover" — that was contaminated by a client bug that turned
                # transient failures and an empty scheme-index into blanket None
                # verdicts; a 40/40 resample of the affected codes was fully live.)
                # One cheap retry still covers a borderline empty-then-populated
                # response without paying the full exception backoff ladder.
                none_attempts += 1
                if none_attempts > _NONE_RETRIES:
                    break
                time.sleep(_NONE_BACKOFF_S)
                continue
            except Exception as exc:
                last_exc = exc
            if attempt < max_retries:
                time.sleep(_BACKOFF[min(attempt, len(_BACKOFF) - 1)])

        if last_exc is not None:
            _append_failed(data_dir, amfi_code, f"exception: {last_exc!r}")
            failed += 1
        elif raw is None:
            _append_failed(data_dir, amfi_code, "mftool returned None")
            failed += 1
        else:
            _write_shard(shard_path, raw)

        done += 1
        if done % 100 == 0:
            _LOG.info("progress: %d/%d done, %d failed", done, total, failed)

    _LOG.info("complete: %d/%d done, %d failed", done, total, failed)


def consolidate(data_dir: Path) -> Path:
    """Read all shards in data_dir/raw/ and write nav + scheme_master parquet.

    Each shard is read once and feeds two derivations in the same pass:
    ``nav.parquet`` (the figure-of-record NAV panel) and
    ``scheme_master.parquet`` (one metadata row per shard — no refetch). Shards
    are processed in amfi_code order. Overwrites any existing files.
    Returns the nav.parquet path.
    """
    shards = sorted((data_dir / "raw").glob("*.json.gz"))
    records = []
    scheme_records: list[SchemeMasterRecord] = []
    for shard in shards:
        amfi_code = shard.name.removesuffix(".json.gz")
        raw = _read_shard(shard)
        records.extend(normalise(amfi_code, raw))
        scheme_records.append(scheme_record(amfi_code, raw))
    nav_path = land(records, data_dir)
    master_path = land_scheme_master(scheme_records, data_dir)
    _LOG.info("scheme_master → %s (%d rows)", master_path, len(scheme_records))
    return nav_path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Land universe NAV shards from mftool."
    )
    parser.add_argument("--data-dir", required=True, type=Path, metavar="PATH")
    parser.add_argument(
        "--consolidate",
        action="store_true",
        help="run consolidate() after fetching",
    )
    parser.add_argument("--delay-s", type=float, default=0.75, metavar="SECS")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument(
        "--shard",
        metavar="i/N",
        help="run worker i of N (1-based), taking every N-th code; for parallel runs",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="re-attempt codes in failed_codes.txt (skipped by default on resume)",
    )
    args = parser.parse_args()

    shard: tuple[int, int] | None = None
    if args.shard is not None:
        i_str, n_str = args.shard.split("/")
        i, n = int(i_str), int(n_str)
        if not (1 <= i <= n):
            parser.error(f"--shard i/N requires 1 <= i <= N, got {args.shard}")
        shard = (i - 1, n)  # CLI is 1-based; land_universe is 0-based

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    land_universe(
        args.data_dir,
        delay_s=args.delay_s,
        max_retries=args.max_retries,
        shard=shard,
        retry_failed=args.retry_failed,
    )
    if args.consolidate:
        if shard is not None:
            # Consolidation must see every worker's shards — run it once, separately,
            # after all workers finish, not inside a single sharded worker.
            _LOG.info("--shard set: skipping consolidate; run it once after all workers finish")
        else:
            out = consolidate(args.data_dir)
            print(f"consolidated → {out}")


if __name__ == "__main__":
    main()
