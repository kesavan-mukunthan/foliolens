"""Resumable universe NAV landing.

Fetches every AMFI fund from mftool, writing one gzipped raw shard per
fund to data_dir/raw/{amfi_code}.json.gz. An existing shard is skipped —
re-run to resume. Failed codes (network error or None response) are
appended to data_dir/failed_codes.txt.

After shards are present, consolidate() reads them all and calls land()
to produce data_dir/nav.parquet.

CLI: python -m foliolens.ingest.universe --data-dir PATH [--consolidate]
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

_LOG = logging.getLogger(__name__)

_BACKOFF: tuple[float, ...] = (2.0, 8.0, 32.0)


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


def land_universe(
    data_dir: Path,
    *,
    delay_s: float = 0.75,
    max_retries: int = 3,
) -> None:
    """Fetch every AMFI fund NAV and write one gzipped raw shard per fund.

    Existing shards are skipped — re-running resumes where a prior run stopped.
    Failed codes are recorded in data_dir/failed_codes.txt. Never raises.
    """
    codes = list_scheme_codes()
    total = len(codes)
    done = 0
    failed = 0

    for amfi_code in codes:
        shard = _shard_path(data_dir, amfi_code)
        if shard.exists():
            done += 1
            if done % 100 == 0:
                _LOG.info("progress: %d/%d done, %d failed", done, total, failed)
            continue

        time.sleep(delay_s)

        raw: dict[str, Any] | None = None
        last_exc: BaseException | None = None
        for attempt in range(1 + max_retries):
            try:
                raw = fetch_nav_history(amfi_code)
                last_exc = None
                break
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
            _write_shard(shard, raw)

        done += 1
        if done % 100 == 0:
            _LOG.info("progress: %d/%d done, %d failed", done, total, failed)

    _LOG.info("complete: %d/%d done, %d failed", done, total, failed)


def consolidate(data_dir: Path) -> Path:
    """Read all shards in data_dir/raw/ and write data_dir/nav.parquet.

    Shards are processed in amfi_code order. Overwrites any existing nav.parquet.
    """
    shards = sorted((data_dir / "raw").glob("*.json.gz"))
    records = []
    for shard in shards:
        amfi_code = shard.name.removesuffix(".json.gz")
        records.extend(normalise(amfi_code, _read_shard(shard)))
    return land(records, data_dir)


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
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    land_universe(args.data_dir, delay_s=args.delay_s, max_retries=args.max_retries)
    if args.consolidate:
        out = consolidate(args.data_dir)
        print(f"consolidated → {out}")


if __name__ == "__main__":
    main()
