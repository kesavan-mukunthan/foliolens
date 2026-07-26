"""F1 batch runner — flexicap direct-growth universe → ``metrics.json``.

Entry point: ``uv run python -m foliolens.report.flexipage --data-dir PATH --out PATH``

Orchestration only (``spec-flexicap-page §8``: "call, don't reimplement"):
loads the universe via ``data_access.load_scheme_master`` (spec-benchmarks §2),
constructs one ``ShareClass`` Investment per fund off stored NAV (no network —
analytics reads stored parquet only, ``CLAUDE.md``), and calls
``assembly.build_fund_panel`` / ``assembly.assemble_universe`` for every
figure. A fund whose NAV fails to load or whose panel computation raises is
recorded in ``failures`` and skipped — never silently dropped — and the whole
build aborts if failures exceed 10% of the cohort.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa

from foliolens.benchmark_map import (
    CATEGORY_YARDSTICK,
    DEFAULT_BENCHMARK_MAP,
    TIER1,
)
from foliolens.data_access import DataAccess
from foliolens.ingest.iima import rf_investment
from foliolens.model.investments import Benchmark, ShareClass, benchmark_from_index
from foliolens.model.sources import PricedSource

from .assembly import FundPanel, assemble_universe, build_fund_panel

_LOG = logging.getLogger(__name__)

CATEGORY = "flexi_cap"

#: Abort the build if more than this fraction of the cohort fails to load
#: (``spec-flexicap-page §7`` F1 acceptance).
MAX_FAILURE_RATE = 0.10


@dataclass(frozen=True)
class FundLoadFailure:
    """One fund that could not be loaded or panel-built — carried, never dropped."""

    amfi_code: str
    scheme_name: str
    reason: str


@dataclass(frozen=True)
class BuildSummary:
    """Everything a caller needs after a run: the written artifact + the ledger."""

    artifact: dict[str, Any]
    panels: tuple[FundPanel, ...]
    failures: tuple[FundLoadFailure, ...]
    universe_count: int
    as_of: date
    out_path: Path


def load_universe(
    data_access: DataAccess,
    *,
    benchmark_map_path: Path | str = DEFAULT_BENCHMARK_MAP,
) -> pa.Table:
    """The flexicap direct-growth universe (``spec-flexicap-page §1``).

    ``sebi_category == "flexi_cap"``, ``plan == "direct"``, ``option == "growth"``,
    over ``load_scheme_master``'s scheme_master ⟕ benchmark_map join.
    """
    master = data_access.load_scheme_master(benchmark_map_path)
    mask = pa.array(
        [
            category == CATEGORY and plan == "direct" and option == "growth"
            for category, plan, option in zip(
                master.column("sebi_category").to_pylist(),
                master.column("plan").to_pylist(),
                master.column("option").to_pylist(),
            )
        ],
        type=pa.bool_(),
    )
    return master.filter(mask)


def _build_fund_investment(data_access: DataAccess, amfi_code: str) -> ShareClass:
    """One fund's Investment off stored NAV — the existing engine seam.

    ``isin`` is not carried by ``scheme_master`` (spec-benchmarks §1's derived
    columns); left blank rather than fabricated. Not consumed by any metric.
    """
    nav = data_access.load_nav_series(amfi_code)
    return ShareClass(
        id=amfi_code,
        amfi_code=amfi_code,
        isin="",
        plan="direct",
        option="growth",
        source=PricedSource(nav=nav),
    )


def _index_landed(data_access: DataAccess, index_code: str) -> bool:
    """Whether ``index_code`` has any landed level data (``spec-flexicap-page §1``
    tier-fallback check — BSE500TRI has not landed as of this milestone).
    """
    try:
        data_access.load_index_series(index_code)
    except ValueError:
        return False
    return True


def _build_benchmark(data_access: DataAccess, index_code: str) -> Benchmark:
    return benchmark_from_index(data_access.load_index_series(index_code))


def run(
    data_dir: Path,
    out_path: Path,
    *,
    rf_path: Path,
    as_of: date | None = None,
    benchmark_map_path: Path | str = DEFAULT_BENCHMARK_MAP,
) -> BuildSummary:
    """Run the F1 batch end to end and write ``metrics.json``.

    ``as_of`` defaults to the latest last-available-NAV date across the
    successfully-loaded cohort, so every fund's trailing/rolling windows
    anchor to the same date (required for cross-sectional ranks to be
    comparable). Raises if the universe is empty or failures exceed
    :data:`MAX_FAILURE_RATE` of the cohort.
    """
    data_access = DataAccess(data_dir)
    universe = load_universe(data_access, benchmark_map_path=benchmark_map_path)
    rows: list[dict[str, Any]] = universe.to_pylist()
    total = len(rows)
    if total == 0:
        raise ValueError(f"empty {CATEGORY!r} universe — nothing to build")

    rf = rf_investment(rf_path)
    yardstick_code = CATEGORY_YARDSTICK[CATEGORY]
    yardstick = _build_benchmark(data_access, yardstick_code)

    failures: list[FundLoadFailure] = []
    loaded: list[tuple[dict[str, Any], ShareClass]] = []
    for row in rows:
        amfi_code = row["amfi_code"]
        try:
            fund = _build_fund_investment(data_access, amfi_code)
        except Exception as exc:  # noqa: BLE001 - collected, reported, never swallowed
            failures.append(FundLoadFailure(amfi_code, row["scheme_name"], repr(exc)))
            continue
        loaded.append((row, fund))

    if as_of is None:
        last_dates = [fund.source.value_series.data[-1][0] for _, fund in loaded]
        if not last_dates:
            raise ValueError("no fund loaded successfully — cannot infer as_of")
        as_of = max(last_dates)

    tier1_landed_cache: dict[str, bool] = {}
    panels: list[FundPanel] = []
    for row, fund in loaded:
        amfi_code = row["amfi_code"]
        try:
            stated_code = row["benchmark_code"]
            stated_tier = row["benchmark_tier"]
            if stated_tier == TIER1:
                if stated_code not in tier1_landed_cache:
                    tier1_landed_cache[stated_code] = _index_landed(
                        data_access, stated_code
                    )
                tier1_landed = tier1_landed_cache[stated_code]
            else:
                tier1_landed = True  # no tier-1 claim to reconcile; nothing pending
            panel = build_fund_panel(
                amfi_code=amfi_code,
                scheme_name=row["scheme_name"],
                fund_house=row["fund_house"],
                fund=fund,
                rf=rf,
                yardstick=yardstick,
                stated_code=stated_code,
                stated_tier=stated_tier,
                yardstick_code=yardstick_code,
                tier1_landed=tier1_landed,
                as_of=as_of,
            )
        except Exception as exc:  # noqa: BLE001 - collected, reported, never swallowed
            failures.append(FundLoadFailure(amfi_code, row["scheme_name"], repr(exc)))
            continue
        panels.append(panel)

    failure_rate = len(failures) / total
    if failure_rate > MAX_FAILURE_RATE:
        detail = "\n".join(
            f"  {f.amfi_code} {f.scheme_name}: {f.reason}" for f in failures
        )
        raise RuntimeError(
            f"{len(failures)}/{total} funds failed to load "
            f"({failure_rate:.1%} > {MAX_FAILURE_RATE:.0%} threshold) — aborting:\n"
            f"{detail}"
        )

    artifact = assemble_universe(
        panels, as_of=as_of, category=CATEGORY, yardstick_code=yardstick_code
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(artifact, fh, allow_nan=False, indent=2)
        fh.write("\n")

    if failures:
        _LOG.warning(
            "%d/%d funds failed to load: %s",
            len(failures),
            total,
            "; ".join(f"{f.amfi_code} ({f.reason})" for f in failures),
        )

    return BuildSummary(
        artifact=artifact,
        panels=tuple(panels),
        failures=tuple(failures),
        universe_count=total,
        as_of=as_of,
        out_path=out_path,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="F1 batch runner: flexicap direct-growth universe -> metrics.json"
    )
    parser.add_argument("--data-dir", required=True, type=Path, metavar="PATH")
    parser.add_argument("--out", required=True, type=Path, metavar="PATH")
    parser.add_argument(
        "--rf-path",
        required=True,
        type=Path,
        metavar="PATH",
        help=(
            "local IIM-A four-factor monthly CSV (RF column) — never committed; "
            "not licensed for redistribution (CLAUDE.md)"
        ),
    )
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="defaults to the latest last-NAV date across the loaded cohort",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        summary = run(
            args.data_dir, args.out, rf_path=args.rf_path, as_of=args.as_of
        )
    except RuntimeError as exc:
        print(f"BUILD ABORTED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"wrote {summary.out_path}")
    print(
        f"universe: {summary.universe_count} funds, {len(summary.panels)} loaded, "
        f"{len(summary.failures)} failed, as_of={summary.as_of.isoformat()}"
    )
    for f in summary.failures:
        print(f"  FAILED {f.amfi_code} {f.scheme_name}: {f.reason}")


if __name__ == "__main__":
    main()
