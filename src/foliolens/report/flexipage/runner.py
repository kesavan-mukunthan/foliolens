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

Every fund's ``commentary`` is assembled as ``null`` (F4 writes it, not this
module); a plain rebuild therefore orphans any commentary already generated
against the previous artifact. ``--carry-commentary <previous-metrics.json>``
closes that gap by copying each fund's commentary block from the previous
artifact by ``amfi_code`` (:func:`_carry_forward_commentary`), skipping a
block whose ``prompt_version`` is stale so a prompt bump forces regeneration.
The idempotent refresh sequence this pairs with (spec-flexicap-page §5):
``runner --carry-commentary prev.json`` (carries unchanged funds forward) →
``commentary --only-missing`` (generates only the still-null funds — no API
call for the carried ones) → ``render``.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import pyarrow as pa

from foliolens.benchmark_map import (
    CATEGORY_YARDSTICK,
    DEFAULT_BENCHMARK_MAP,
    TIER1,
)
from foliolens.data_access import DATA_DIR_ENV_VAR, DataAccess, default_data_dir
from foliolens.ingest.iima import rf_investment
from foliolens.model.investments import Benchmark, ShareClass, benchmark_from_index, share_class_from_nav
from foliolens.model.value_objects import NavSeries
from foliolens.returns.calendar import TradingCalendar, calendar_from_dates
from foliolens.returns.frequency import Frequency
from foliolens.returns.monthly import month_end
from foliolens.validation.identities import IdentityViolation, check_identities

from .assembly import (
    FundPanel,
    assemble_universe,
    build_fund_panel,
    build_rf_disclosure,
)
from .commentary import PROMPT_VERSION

_LOG = logging.getLogger(__name__)

CATEGORY = "flexi_cap"

#: Abort the build if more than this fraction of the cohort fails to load
#: (``spec-flexicap-page §7`` F1 acceptance).
MAX_FAILURE_RATE = 0.10

#: Interior-anomaly guard thresholds (``spec-flexicap-page §7`` F1 addition):
#: a corrupted splice in a manually-combined source file produced a phantom
#: +33% day at a chunk boundary once already — endpoint and continuity checks
#: cannot catch an interior basis break, so every loaded index series is
#: walked point-to-point before it feeds any computation.
DAY_OVER_DAY_MAX_ABS_CHANGE = 0.15
MONTH_OVER_MONTH_MAX_ABS_CHANGE = 0.25

#: Checks apply only on/after this date. Real Indian-market single-session
#: moves reached roughly ±18% around the 2004 election-result crash and the
#: 2008-09 GFC — both before this cutoff — and the market has not moved that
#: far in one session since, so ±15% cleanly separates a corrupted splice
#: from genuine historical volatility without false-positiving on those two
#: real extremes.
ANOMALY_CHECK_START_DATE = date(2010, 1, 1)


class IdentityCheckError(RuntimeError):
    """One or more funds' assembled metrics fail a B1 identity cross-check.

    Fails the whole build loud, listing every violation — never a warn-and-
    continue mode, never a bypass flag (a violation means the artifact is
    about to publish a Sharpe/IR/alpha that could not have come from its own
    reported return/vol/beta/tracking-error, the exact class of bug the
    pre-fix site shipped once already; see ``validation/identities.py``).
    """


def _format_violations(violations: list[IdentityViolation]) -> str:
    return "\n".join(
        f"  {v.amfi_code} {v.window} {v.identity}: reported={v.lhs:.6f} "
        f"predicted={v.rhs:.6f} gap={v.gap:.6f}"
        for v in violations
    )


class IndexAnomalyError(RuntimeError):
    """A landed index series has an interior level break past the guard's cutoff.

    Deliberately **not** a ``ValueError`` subclass: ``_index_landed``'s
    ``except ValueError`` is its "not landed" probe and must never swallow a
    real data-quality abort — this always propagates out of ``run()``.
    """


def _validate_index_series(index_code: str, series: NavSeries) -> None:
    """Fail loud on an interior day-over-day or month-over-month level break.

    Walks the series once point-to-point (never resampled/smoothed away), so
    a single corrupted row at any interior position is caught even though
    both its neighbours look individually plausible. The month-over-month leg
    derives its own single-series calendar off ``series``' own dates — this is
    a pre-computation data-quality gate on the index alone, decoupled from the
    equity cohort's shared calendar (which the index's Benchmark panel uses
    once it is actually constructed).
    """
    data = series.data
    for (prev_date, prev_level), (curr_date, curr_level) in zip(data, data[1:]):
        if curr_date < ANOMALY_CHECK_START_DATE or prev_level == 0:
            continue
        change = float(curr_level / prev_level - 1)
        if abs(change) > DAY_OVER_DAY_MAX_ABS_CHANGE:
            raise IndexAnomalyError(
                f"{index_code}: day-over-day change of {change:+.1%} on "
                f"{curr_date.isoformat()} ({prev_level} on {prev_date.isoformat()} -> "
                f"{curr_level}) exceeds the ±{DAY_OVER_DAY_MAX_ABS_CHANGE:.0%} guard"
            )

    month_ends = month_end(series, calendar_from_dates(d for d, _ in data)).data
    for (prev_date, prev_level), (curr_date, curr_level) in zip(
        month_ends, month_ends[1:]
    ):
        if curr_date < ANOMALY_CHECK_START_DATE or prev_level == 0:
            continue
        change = float(curr_level / prev_level - 1)
        if abs(change) > MONTH_OVER_MONTH_MAX_ABS_CHANGE:
            raise IndexAnomalyError(
                f"{index_code}: month-over-month change of {change:+.1%} at "
                f"{curr_date.isoformat()} ({prev_level} on {prev_date.isoformat()} -> "
                f"{curr_level}) exceeds the ±{MONTH_OVER_MONTH_MAX_ABS_CHANGE:.0%} guard"
            )


def _load_index_series_checked(data_access: DataAccess, index_code: str) -> NavSeries:
    """The only path to index level data in this module — validated on load."""
    series = data_access.load_index_series(index_code)
    _validate_index_series(index_code, series)
    return series


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
    carried_commentary: int = 0


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


def _build_fund_investment(
    data_access: DataAccess, amfi_code: str, cal: TradingCalendar
) -> ShareClass:
    """One fund's Investment off stored NAV, panels built eagerly via ``cal``.

    ``cal`` is the one equity-cohort calendar derived once per run and shared
    across every fund (and the benchmark) — never derived per fund. ``isin``
    is not carried by ``scheme_master`` (spec-benchmarks §1's derived
    columns); left blank rather than fabricated. Not consumed by any metric.
    """
    nav = data_access.load_nav_series(amfi_code)
    return share_class_from_nav(
        amfi_code, nav, cal, isin="", plan="direct", option="growth"
    )


def _index_landed(data_access: DataAccess, index_code: str) -> bool:
    """Whether ``index_code`` has any landed level data (``spec-flexicap-page §1``
    tier-fallback check — BSE500TRI has not landed as of this milestone).

    Only catches "no data" (``ValueError``); an ``IndexAnomalyError`` from the
    interior-break guard is never a "not landed" signal and always propagates.
    """
    try:
        _load_index_series_checked(data_access, index_code)
    except ValueError:
        return False
    return True


def _build_benchmark(
    data_access: DataAccess, index_code: str, cal: TradingCalendar  # noqa: ARG001
) -> Benchmark:
    """The category yardstick's Investment, panels built off *its own*
    trading calendar — derived from the index's own published dates, never
    the shared equity-cohort ``cal``.

    Many AMCs publish a NAV dated 31 March (the fiscal year-end) even on a
    day the exchange has no session; the cohort calendar's majority-publish
    rule over fund NAVs then treats 31 March as a trading day no benchmark
    index ever actually traded on. Passing that calendar straight through to
    :func:`~foliolens.model.investments.benchmark_from_index` silently drops
    March — the index has no level dated on the day the cohort calendar
    insists is March's last trading day — and, by ``monthly_returns``'s
    adjacent-month rule, cascades to drop April too (found in production:
    NIFTY500TRI's monthly panel missing 2024/2025/2026 March+April under the
    shared cohort calendar, thinning several funds' tracking-error overlap
    and surfacing as B1 IR identity violations). See
    ``tests/invariants/test_benchmark_calendar.py`` for the reproduction.

    ``cal`` is accepted but unused — kept so every call site in this module
    still threads the one cohort calendar through uniformly; the benchmark
    is the one Investment in the run whose own calendar diverges from it.
    """
    levels = _load_index_series_checked(data_access, index_code)
    own_cal = calendar_from_dates(d for d, _ in levels.data)
    return benchmark_from_index(levels, own_cal)


def _carry_forward_commentary(artifact: dict[str, Any], previous_path: Path) -> int:
    """Copy each fund's commentary block from ``previous_path``'s artifact by
    ``amfi_code`` — the half of idempotent rebuild that makes ``commentary
    --only-missing`` useful, since this runner otherwise writes every fund's
    ``commentary: null`` on every build (spec-flexicap-page §5).

    A block is carried only when its ``prompt_version`` matches the current
    :data:`foliolens.report.flexipage.commentary.PROMPT_VERSION` — a stale-
    version block is dropped (stays ``null``, already the assembled default),
    so a prompt bump naturally forces regeneration rather than silently
    carrying commentary written under a superseded contract. A fund absent
    from the previous artifact (new to the universe) also stays ``null``.
    Returns the number of funds carried.
    """
    previous = json.loads(previous_path.read_text(encoding="utf-8"))
    previous_by_code: dict[str, Any] = {
        f["amfi_code"]: f.get("commentary") for f in previous["funds"]
    }

    carried = 0
    for fund in artifact["funds"]:
        commentary = previous_by_code.get(fund["amfi_code"])
        if commentary is not None and commentary.get("prompt_version") == PROMPT_VERSION:
            fund["commentary"] = commentary
            carried += 1
    return carried


def run(
    data_dir: Path,
    out_path: Path,
    *,
    rf_path: Path,
    as_of: date | None = None,
    benchmark_map_path: Path | str = DEFAULT_BENCHMARK_MAP,
    carry_commentary_path: Path | None = None,
) -> BuildSummary:
    """Run the F1 batch end to end and write ``metrics.json``.

    ``as_of`` defaults to the latest calendar month-end emitted by at least
    half of the successfully-loaded cohort's MONTHLY panels (never a raw
    last-NAV date, and never per-fund) — the shared anchor every fund's
    fixed-window metrics (sub-year returns, YTD, 1Y/3Y/5Y) are measured
    against (``spec-analytics``: common anchoring). A fund whose panel does
    not reach that date emits ``null`` for those metrics rather than
    silently falling back to its own last month — see
    ``analytics.artifact.build_metrics`` and
    ``report.flexipage.assembly._relative_scalar`` /
    ``_alpha_for_window``, which apply the anchor. Raises if the universe is
    empty, no fund loads, no month-end reaches the 50% threshold, or
    failures exceed :data:`MAX_FAILURE_RATE` of the cohort.

    ``carry_commentary_path``, when given, points at a previous build's
    ``metrics.json``; matching-version commentary blocks are copied onto the
    freshly-assembled artifact by ``amfi_code`` before it's written
    (:func:`_carry_forward_commentary`) — see the module docstring for the
    full refresh sequence.
    """
    data_access = DataAccess(data_dir)
    universe = load_universe(data_access, benchmark_map_path=benchmark_map_path)
    rows: list[dict[str, Any]] = universe.to_pylist()
    total = len(rows)
    if total == 0:
        raise ValueError(f"empty {CATEGORY!r} universe — nothing to build")

    # One equity-cohort trading calendar for the whole run — derived once over
    # every fund in the universe, then passed unchanged to every factory call
    # (funds and the benchmark alike). Never derived per fund.
    cohort_codes = [row["amfi_code"] for row in rows]
    cal = data_access.derive_trading_calendar(cohort_codes)

    rf = rf_investment(rf_path)
    yardstick_code = CATEGORY_YARDSTICK[CATEGORY]
    yardstick = _build_benchmark(data_access, yardstick_code, cal)

    failures: list[FundLoadFailure] = []
    loaded: list[tuple[dict[str, Any], ShareClass]] = []
    for row in rows:
        amfi_code = row["amfi_code"]
        try:
            fund = _build_fund_investment(data_access, amfi_code, cal)
        except Exception as exc:  # noqa: BLE001 - collected, reported, never swallowed
            failures.append(FundLoadFailure(amfi_code, row["scheme_name"], repr(exc)))
            continue
        loaded.append((row, fund))

    if as_of is None:
        if not loaded:
            raise ValueError("no fund loaded successfully — cannot infer as_of")
        month_end_counts: dict[date, int] = {}
        for _, fund in loaded:
            for d in fund.returns(Frequency.MONTHLY).dates:
                month_end_counts[d] = month_end_counts.get(d, 0) + 1
        threshold = 0.5 * len(loaded)
        qualifying = [d for d, count in month_end_counts.items() if count >= threshold]
        if not qualifying:
            raise ValueError(
                "no calendar month-end is emitted by >= 50% of the loaded cohort "
                "— cannot infer as_of"
            )
        as_of = max(qualifying)

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
        panels,
        as_of=as_of,
        category=CATEGORY,
        yardstick_code=yardstick_code,
        rf_disclosure=build_rf_disclosure(rf, as_of),
    )

    violations: list[IdentityViolation] = []
    for fund_entry in cast("list[dict[str, Any]]", artifact["funds"]):
        violations.extend(check_identities(fund_entry))
    if violations:
        raise IdentityCheckError(
            f"{len(violations)} identity violation(s) detected — aborting:\n"
            f"{_format_violations(violations)}"
        )

    carried_commentary = 0
    if carry_commentary_path is not None:
        carried_commentary = _carry_forward_commentary(artifact, carry_commentary_path)

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
        carried_commentary=carried_commentary,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="F1 batch runner: flexicap direct-growth universe -> metrics.json"
    )
    parser.add_argument(
        "--data-dir",
        required=False,
        default=None,
        type=Path,
        metavar="PATH",
        help=f"defaults to ${DATA_DIR_ENV_VAR} if set",
    )
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
    parser.add_argument(
        "--carry-commentary",
        dest="carry_commentary",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "previous metrics.json -- matching-version commentary blocks are "
            "copied onto the freshly-assembled artifact by amfi_code before "
            "it's written; stale-version or absent funds stay null"
        ),
    )
    args = parser.parse_args(argv)

    data_dir = args.data_dir or default_data_dir()
    if data_dir is None:
        parser.error(f"--data-dir is required (or set ${DATA_DIR_ENV_VAR})")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        summary = run(
            data_dir,
            args.out,
            rf_path=args.rf_path,
            as_of=args.as_of,
            carry_commentary_path=args.carry_commentary,
        )
    except RuntimeError as exc:
        print(f"BUILD ABORTED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"wrote {summary.out_path}")
    print(
        f"universe: {summary.universe_count} funds, {len(summary.panels)} loaded, "
        f"{len(summary.failures)} failed, as_of={summary.as_of.isoformat()}"
    )
    if args.carry_commentary is not None:
        print(f"commentary carried forward: {summary.carried_commentary}")
    for f in summary.failures:
        print(f"  FAILED {f.amfi_code} {f.scheme_name}: {f.reason}")


if __name__ == "__main__":
    main()
