"""F1 end-to-end runner test — synthetic 3-fund mini-universe.

Exercises the full pipeline (load -> compute -> assemble -> write) against a
frozen synthetic fixture built at test time: no network, no real fund data
(``CLAUDE.md`` / ``tests/TESTS.md``: fixtures only). Covers the F1 acceptance
surface (``specs/spec-flexicap-page.md §7``): schema validation, every
universe fund present, ranks form a valid permutation over non-null funds,
null-propagation for a young fund, and no NaN/Inf anywhere in the written
JSON.
"""
from __future__ import annotations

import csv
import json
import math
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import jsonschema
import numpy as np
import pytest

from foliolens.ingest.index_normalise import IndexRecord
from foliolens.ingest.land import land, land_index
from foliolens.ingest.mftool_client import NavRecord
from foliolens.ingest.scheme_master import SchemeMasterRecord, land_scheme_master
from foliolens.report.flexipage.assembly import RANK_SPECS
from foliolens.report.flexipage.commentary import PROMPT_VERSION
from foliolens.report.flexipage.commentary import run as run_commentary
from foliolens.report.flexipage.runner import (
    IdentityCheckError,
    IndexAnomalyError,
    load_universe,
    run,
)
from foliolens.data_access import DataAccess
from foliolens.returns.monthly import monthly_returns

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "flexipage-3.schema.json"

_START = date(2018, 6, 30)
_MATURE_DAYS = 8 * 365  # ~8 years daily -> 96 monthly points; full 5Y panels
_YOUNG_START = date(2025, 11, 1)
_YOUNG_DAYS = 250  # ~8 months -> nulls for every 1Y/3Y/5Y window


def _daily_series(
    start: date, n_days: int, *, seed: int, drift: float = 0.0003, vol: float = 0.01
) -> list[tuple[date, Decimal]]:
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n_days)
    levels = 100.0 * np.cumprod(1.0 + rets)
    return [
        (start + timedelta(days=i), Decimal(str(round(float(lv), 6))))
        for i, lv in enumerate(levels)
    ]


def _write_benchmark_map(path: Path, rows: list[tuple[str, str, str]]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["amfi_code", "benchmark_code", "tier"])
        for r in rows:
            w.writerow(r)


def _write_rf_csv(path: Path, start: date, end: date, *, monthly_pct: float = 0.5) -> None:
    months: list[date] = []
    d = date(start.year, start.month, 1)
    while d <= end:
        months.append(d)
        d = date(d.year + (d.month // 12), (d.month % 12) + 1, 1)
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Date", "SMB", "HML", "WML", "MF", "RF"])
        for m in months:
            w.writerow([m.strftime("%Y-%m"), "0.1", "0.1", "0.1", "0.5", f"{monthly_pct}"])


@pytest.fixture()
def universe(tmp_path: Path) -> dict[str, Path]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    nav_records: list[NavRecord] = []
    for code, seed in (("AAAA01", 1), ("BBBB02", 2)):
        for d, nav in _daily_series(_START, _MATURE_DAYS, seed=seed):
            nav_records.append(NavRecord(amfi_code=code, date=d, nav=nav))
    for d, nav in _daily_series(_YOUNG_START, _YOUNG_DAYS, seed=3):
        nav_records.append(NavRecord(amfi_code="CCCC03", date=d, nav=nav))
    land(nav_records, data_dir)

    scheme_records = [
        SchemeMasterRecord(
            amfi_code="AAAA01",
            scheme_name="Alpha Flexi Cap Fund - Direct Plan - Growth",
            fund_house="Alpha Mutual Fund",
            scheme_category="Equity Scheme - Flexi Cap Fund",
            sebi_category="flexi_cap",
            plan="direct",
            option="growth",
        ),
        SchemeMasterRecord(
            amfi_code="BBBB02",
            scheme_name="Beta Flexi Cap Fund - Direct - Growth",
            fund_house="Beta Mutual Fund",
            scheme_category="Equity Scheme - Flexi Cap Fund",
            sebi_category="flexi_cap",
            plan="direct",
            option="growth",
        ),
        SchemeMasterRecord(
            amfi_code="CCCC03",
            scheme_name="Gamma Flexi Cap Fund - Direct Plan - Growth",
            fund_house="Gamma Mutual Fund",
            scheme_category="Equity Scheme - Flexi Cap Fund",
            sebi_category="flexi_cap",
            plan="direct",
            option="growth",
        ),
        # Excluded by the universe filter (§1): wrong category / wrong plan.
        SchemeMasterRecord(
            amfi_code="DDDD04",
            scheme_name="Alpha Large Cap Fund - Direct Plan - Growth",
            fund_house="Alpha Mutual Fund",
            scheme_category="Equity Scheme - Large Cap Fund",
            sebi_category="large_cap",
            plan="direct",
            option="growth",
        ),
        SchemeMasterRecord(
            amfi_code="EEEE05",
            scheme_name="Alpha Flexi Cap Fund - Regular Plan - Growth",
            fund_house="Alpha Mutual Fund",
            scheme_category="Equity Scheme - Flexi Cap Fund",
            sebi_category="flexi_cap",
            plan="regular",
            option="growth",
        ),
    ]
    land_scheme_master(scheme_records, data_dir)

    # Yardstick (NIFTY500TRI) + alternate (NIFTY50TRI) landed; stated tier-1
    # (BSE500TRI) deliberately NOT landed -> exercises the tier-fallback path.
    index_records: list[IndexRecord] = []
    for code, seed in (("NIFTY500TRI", 10), ("NIFTY50TRI", 11)):
        for d, level in _daily_series(_START, _MATURE_DAYS, seed=seed, vol=0.008):
            index_records.append(IndexRecord(index_code=code, date=d, level=level))
    land_index(index_records, data_dir)

    benchmark_map_path = tmp_path / "benchmark_map.csv"
    _write_benchmark_map(
        benchmark_map_path,
        [
            ("AAAA01", "BSE500TRI", "tier1"),
            ("AAAA01", "NIFTY50TRI", "alternate"),
            ("BBBB02", "NIFTY500TRI", "tier1"),
            # CCCC03 deliberately uncurated -> stated benchmark is null.
        ],
    )

    rf_path = tmp_path / "iima_rf.csv"
    _write_rf_csv(rf_path, _START, _START + timedelta(days=_MATURE_DAYS + 60))

    return {
        "data_dir": data_dir,
        "benchmark_map_path": benchmark_map_path,
        "rf_path": rf_path,
    }


@pytest.fixture()
def artifact(tmp_path: Path, universe: dict[str, Path]) -> dict[str, Any]:
    out_path = tmp_path / "out" / "metrics.json"
    run(
        universe["data_dir"],
        out_path,
        rf_path=universe["rf_path"],
        benchmark_map_path=universe["benchmark_map_path"],
    )
    with out_path.open() as fh:
        return json.load(fh)  # type: ignore[no-any-return]


def _fund(artifact: dict[str, Any], amfi_code: str) -> dict[str, Any]:
    return next(f for f in artifact["funds"] if f["amfi_code"] == amfi_code)


# ---------------------------------------------------------------------------
# Universe filter
# ---------------------------------------------------------------------------


def test_universe_filter_excludes_wrong_category_and_plan(
    universe: dict[str, Path],
) -> None:
    data_access = DataAccess(universe["data_dir"])
    table = load_universe(data_access, benchmark_map_path=universe["benchmark_map_path"])
    assert set(table.column("amfi_code").to_pylist()) == {"AAAA01", "BBBB02", "CCCC03"}


# ---------------------------------------------------------------------------
# End-to-end shape + schema
# ---------------------------------------------------------------------------


def test_runner_writes_valid_schema(artifact: dict[str, Any]) -> None:
    with SCHEMA_PATH.open() as fh:
        schema = json.load(fh)
    jsonschema.validate(artifact, schema)


def test_every_universe_fund_present(artifact: dict[str, Any]) -> None:
    assert artifact["universe"]["count"] == 3
    codes = {f["amfi_code"] for f in artifact["funds"]}
    assert codes == {"AAAA01", "BBBB02", "CCCC03"}


def test_schema_version_and_yardstick(artifact: dict[str, Any]) -> None:
    assert artifact["schema_version"] == "flexipage-3"
    assert artifact["universe"]["yardstick"] == "NIFTY500TRI"
    for f in artifact["funds"]:
        assert f["benchmark"]["yardstick"] == "NIFTY500TRI"


# ---------------------------------------------------------------------------
# Tier-fallback annotation (§1)
# ---------------------------------------------------------------------------


def test_tier_fallback_when_stated_tier1_not_landed(artifact: dict[str, Any]) -> None:
    alpha = _fund(artifact, "AAAA01")
    assert alpha["benchmark"]["stated"] == "BSE500TRI"
    assert alpha["benchmark"]["tier"] == "alternate-pending-tier1"


def test_no_fallback_when_stated_tier1_landed(artifact: dict[str, Any]) -> None:
    beta = _fund(artifact, "BBBB02")
    assert beta["benchmark"]["stated"] == "NIFTY500TRI"
    assert beta["benchmark"]["tier"] == "tier1"


def test_uncurated_benchmark_is_null(artifact: dict[str, Any]) -> None:
    gamma = _fund(artifact, "CCCC03")
    assert gamma["benchmark"]["stated"] is None
    assert gamma["benchmark"]["tier"] is None


# ---------------------------------------------------------------------------
# Young-fund null propagation
# ---------------------------------------------------------------------------


def test_young_fund_windows_null_not_error(artifact: dict[str, Any]) -> None:
    gamma = _fund(artifact, "CCCC03")
    for label in ("1Y", "3Y", "5Y"):
        assert gamma["metrics"][f"return_{label}"] is None
        assert gamma["metrics"][f"volatility_{label}"] is None
    for year in ("2023", "2024"):
        assert gamma["calendar_years"][year] is None
    # A partial 2025 (Nov-Dec) still has one monthly return in-window -> not null.
    assert gamma["calendar_years"]["2025"] is not None


def test_mature_funds_have_full_5y_panel(artifact: dict[str, Any]) -> None:
    for code in ("AAAA01", "BBBB02"):
        f = _fund(artifact, code)
        assert f["metrics"]["return_5Y"] is not None
        assert len(f["rolling"]["rolling_return_5Y"]) >= 1


# ---------------------------------------------------------------------------
# Chart-only ``series`` block (spec-flexicap-page §4): growth-of-10k +
# underwater — month-end grain, visual-grade float, never a figure of record.
# ---------------------------------------------------------------------------


def test_growth_of_10k_present_with_matched_fund_and_yardstick_lengths(
    artifact: dict[str, Any],
) -> None:
    for code in ("AAAA01", "BBBB02", "CCCC03"):
        f = _fund(artifact, code)
        block = f["series"]["growth_10k"]
        assert block is not None
        assert len(block["fund"]) >= 1
        assert len(block["fund"]) == len(block["yardstick"])
        assert [p["date"] for p in block["fund"]] == [p["date"] for p in block["yardstick"]]
        # Both legs rebase off the same ₹10,000 anchor before the first
        # period's return is applied — a genuine side-by-side, not two
        # independently-based curves.
        for point in (*block["fund"], *block["yardstick"]):
            assert point["value"] > 0.0


def test_underwater_series_present_and_non_positive(artifact: dict[str, Any]) -> None:
    for code in ("AAAA01", "BBBB02", "CCCC03"):
        f = _fund(artifact, code)
        underwater = f["series"]["underwater"]
        assert len(underwater) >= 1
        assert all(point["value"] <= 0.0 for point in underwater)


def test_rolling_sharpe_rank_history_present_for_mature_funds(
    artifact: dict[str, Any],
) -> None:
    for code in ("AAAA01", "BBBB02"):
        f = _fund(artifact, code)
        assert len(f["ranks"]["sharpe_3Y"]["history"]) >= 1


def test_rolling_sharpe_rank_history_empty_for_young_fund(
    artifact: dict[str, Any],
) -> None:
    gamma = _fund(artifact, "CCCC03")
    assert gamma["ranks"]["sharpe_3Y"]["history"] == []


# ---------------------------------------------------------------------------
# Ranks form a valid permutation over non-null funds (§7)
# ---------------------------------------------------------------------------


def test_ranks_form_valid_distribution_per_metric_window(artifact: dict[str, Any]) -> None:
    """Display convention is lower-is-better (amendment 1): the best fund's
    ``pct`` is ``100/n_ranked`` (≈1 for a large cohort), the worst is 100 —
    the flip of ``analytics/peer.py``'s own higher-is-better direction,
    applied once in ``assemble_universe``.
    """
    for key in RANK_SPECS:
        pcts = [f["ranks"][key]["pct"] for f in artifact["funds"]]
        present = [p for p in pcts if p is not None]
        if not present:
            continue
        n = len(present)
        assert all(0.0 < p <= 100.0 for p in present)
        assert min(present) == pytest.approx(100.0 / n)
        assert max(present) == pytest.approx(100.0)


def test_rank_history_present_for_backed_metric_windows(artifact: dict[str, Any]) -> None:
    mature = _fund(artifact, "AAAA01")
    assert len(mature["ranks"]["return_1Y"]["history"]) >= 1
    # No rolling panel backs volatility -> explicit empty history, never fabricated.
    assert mature["ranks"]["volatility_1Y"]["history"] == []


# ---------------------------------------------------------------------------
# JSON round-trip + no NaN/Inf anywhere
# ---------------------------------------------------------------------------


def test_json_round_trips(tmp_path: Path, universe: dict[str, Path]) -> None:
    out_path = tmp_path / "out2" / "metrics.json"
    run(
        universe["data_dir"],
        out_path,
        rf_path=universe["rf_path"],
        benchmark_map_path=universe["benchmark_map_path"],
    )
    text = out_path.read_text()
    reparsed = json.loads(text)
    assert json.loads(json.dumps(reparsed)) == reparsed


def _iter_numbers(value: object) -> Iterator[float]:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_numbers(v)
    elif isinstance(value, list):
        for v in value:
            yield from _iter_numbers(v)


def test_no_nan_or_inf_anywhere(artifact: dict[str, Any]) -> None:
    for n in _iter_numbers(artifact):
        assert math.isfinite(n)


def test_commentary_is_null_placeholder(artifact: dict[str, Any]) -> None:
    for f in artifact["funds"]:
        assert f["commentary"] is None


# ---------------------------------------------------------------------------
# --carry-commentary: idempotent rebuild (spec-flexicap-page §5)
# ---------------------------------------------------------------------------


def _commentary_block(text: str, prompt_version: str) -> dict[str, Any]:
    return {
        "text": text,
        "model": "claude-sonnet-4-6",
        "prompt_version": prompt_version,
        "generated_at": "2026-01-01T00:00:00+00:00",
    }


def test_carry_commentary_copies_matching_drops_stale_new_fund_stays_null(
    tmp_path: Path, universe: dict[str, Path]
) -> None:
    """AAAA01's block matches the current prompt version -> carried. BBBB02's
    is a stale version -> dropped (stays null, forcing regeneration). CCCC03
    is absent from the previous artifact entirely (a fund new to the
    universe) -> stays null.
    """
    previous_path = tmp_path / "previous_metrics.json"
    previous_path.write_text(
        json.dumps(
            {
                "schema_version": "flexipage-1",
                "as_of": "2020-01-01",
                "universe": {
                    "category": "flexi_cap",
                    "count": 2,
                    "yardstick": "NIFTY500TRI",
                    "aggregates": {},
                },
                "funds": [
                    {
                        "amfi_code": "AAAA01",
                        "commentary": _commentary_block("Alpha carried.", PROMPT_VERSION),
                    },
                    {
                        "amfi_code": "BBBB02",
                        "commentary": _commentary_block("Beta stale.", "commentary-v3"),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    out_path = tmp_path / "out" / "metrics.json"
    summary = run(
        universe["data_dir"],
        out_path,
        rf_path=universe["rf_path"],
        benchmark_map_path=universe["benchmark_map_path"],
        carry_commentary_path=previous_path,
    )
    assert summary.carried_commentary == 1

    with out_path.open() as fh:
        written = json.load(fh)
    aaaa = _fund(written, "AAAA01")
    bbbb = _fund(written, "BBBB02")
    cccc = _fund(written, "CCCC03")
    assert aaaa["commentary"] == _commentary_block("Alpha carried.", PROMPT_VERSION)
    assert bbbb["commentary"] is None
    assert cccc["commentary"] is None


def test_no_carry_commentary_path_leaves_everything_null(
    tmp_path: Path, universe: dict[str, Path]
) -> None:
    out_path = tmp_path / "out" / "metrics.json"
    summary = run(
        universe["data_dir"],
        out_path,
        rf_path=universe["rf_path"],
        benchmark_map_path=universe["benchmark_map_path"],
    )
    assert summary.carried_commentary == 0


# ---------------------------------------------------------------------------
# End-to-end: carry-forward + --only-missing -> zero API calls when nothing
# changed (spec-flexicap-page §5, §7-F4 acceptance).
# ---------------------------------------------------------------------------


#: No digits anywhere, so no numeral token can ever be "fabricated" against
#: any payload -- this is a stand-in for a real, validated model response,
#: not a fixture under test in its own right.
_GENERIC_CLEAN_COMMENTARY = (
    "The fund's trailing performance sits close to the category benchmark "
    "across recent history, with volatility and drawdown broadly in line "
    "with peers in the same cohort under review this cycle for this fund "
    "and its comparators across the period considered here overall in the "
    "underlying data set available for this analysis without exception, "
    "and none of the figures supplied point toward any particularly "
    "distinctive reading worth calling out ahead of the rest.\n\n"
    "Rolling and percentile-rank behaviour shows no marked divergence from "
    "the broader peer group across the windows supplied, and no single "
    "period stands out as distinctive relative to the rest of the cohort "
    "under the same comparison basis used consistently throughout this "
    "commentary today, leaving a broadly unremarkable overall picture for "
    "this fund among its peers in the wider comparison set considered."
)


def test_carry_then_only_missing_makes_zero_api_calls(
    tmp_path: Path, universe: dict[str, Path]
) -> None:
    first_path = tmp_path / "out" / "metrics_v1.json"
    run(
        universe["data_dir"],
        first_path,
        rf_path=universe["rf_path"],
        benchmark_map_path=universe["benchmark_map_path"],
    )

    def stub(system: str, messages: list[dict[str, str]]) -> str:
        return _GENERIC_CLEAN_COMMENTARY

    first_summary = run_commentary(first_path, transport=stub)
    assert first_summary.failed == 0
    assert first_summary.generated == first_summary.total

    second_path = tmp_path / "out" / "metrics_v2.json"
    run(
        universe["data_dir"],
        second_path,
        rf_path=universe["rf_path"],
        benchmark_map_path=universe["benchmark_map_path"],
        carry_commentary_path=first_path,
    )

    def never_call(system: str, messages: list[dict[str, str]]) -> str:
        raise AssertionError("the API must never be called -- nothing changed")

    second_summary = run_commentary(second_path, transport=never_call, only_missing=True)
    assert second_summary.generated == 0
    assert second_summary.failed == 0
    assert second_summary.skipped_populated == second_summary.total


# ---------------------------------------------------------------------------
# Index-level anomaly guard (§7 F1 addition): a corrupted splice in a
# manually-combined source file produced a phantom +33% day at a chunk
# boundary in the real data once already — endpoint/continuity checks can't
# catch an interior basis break, so the runner validates every loaded index
# series point-to-point before it feeds any computation.
# ---------------------------------------------------------------------------


def test_index_anomaly_aborts_build(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    nav_records = [
        NavRecord(amfi_code="AAAA01", date=d, nav=nav)
        for d, nav in _daily_series(_START, _MATURE_DAYS, seed=1)
    ]
    land(nav_records, data_dir)

    land_scheme_master(
        [
            SchemeMasterRecord(
                amfi_code="AAAA01",
                scheme_name="Alpha Flexi Cap Fund - Direct Plan - Growth",
                fund_house="Alpha Mutual Fund",
                scheme_category="Equity Scheme - Flexi Cap Fund",
                sebi_category="flexi_cap",
                plan="direct",
                option="growth",
            )
        ],
        data_dir,
    )

    # The category yardstick (NIFTY500TRI) with one corrupted interior day:
    # a lone +33% splice, otherwise an unremarkable ~0.8% daily-vol walk.
    levels = _daily_series(_START, _MATURE_DAYS, seed=10, vol=0.008)
    bad_date, bad_level = levels[100]
    spiked = (bad_level * Decimal("1.33")).quantize(Decimal("0.000001"))
    levels[100] = (bad_date, spiked)
    index_records = [
        IndexRecord(index_code="NIFTY500TRI", date=d, level=level) for d, level in levels
    ]
    land_index(index_records, data_dir)

    benchmark_map_path = tmp_path / "benchmark_map.csv"
    _write_benchmark_map(benchmark_map_path, [])

    rf_path = tmp_path / "iima_rf.csv"
    _write_rf_csv(rf_path, _START, _START + timedelta(days=_MATURE_DAYS + 60))

    with pytest.raises(IndexAnomalyError) as exc_info:
        run(
            data_dir,
            tmp_path / "out" / "metrics.json",
            rf_path=rf_path,
            benchmark_map_path=benchmark_map_path,
        )

    message = str(exc_info.value)
    assert "NIFTY500TRI" in message
    assert bad_date.isoformat() in message


# ---------------------------------------------------------------------------
# Common anchoring (spec-analytics): a stale fund's fixed-window metrics
# null out rather than silently anchoring to its own (earlier) last month;
# the fresh fund's anchor is the cohort as_of, not its own last month either
# (though for this 2-fund cohort they coincide, since the fresh fund's last
# month is exactly the latest month reaching the >=50% threshold).
# ---------------------------------------------------------------------------


def test_stale_fund_windows_null_fresh_fund_anchors_to_cohort_as_of(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    stale_days = _MATURE_DAYS - 60  # ~2 months short of the fresh fund

    nav_records = [
        NavRecord(amfi_code="FRESH01", date=d, nav=nav)
        for d, nav in _daily_series(_START, _MATURE_DAYS, seed=1)
    ]
    nav_records += [
        NavRecord(amfi_code="STALE02", date=d, nav=nav)
        for d, nav in _daily_series(_START, stale_days, seed=2)
    ]
    land(nav_records, data_dir)

    land_scheme_master(
        [
            SchemeMasterRecord(
                amfi_code="FRESH01",
                scheme_name="Fresh Flexi Cap Fund - Direct Plan - Growth",
                fund_house="Fresh Mutual Fund",
                scheme_category="Equity Scheme - Flexi Cap Fund",
                sebi_category="flexi_cap",
                plan="direct",
                option="growth",
            ),
            SchemeMasterRecord(
                amfi_code="STALE02",
                scheme_name="Stale Flexi Cap Fund - Direct Plan - Growth",
                fund_house="Stale Mutual Fund",
                scheme_category="Equity Scheme - Flexi Cap Fund",
                sebi_category="flexi_cap",
                plan="direct",
                option="growth",
            ),
        ],
        data_dir,
    )

    index_records = [
        IndexRecord(index_code="NIFTY500TRI", date=d, level=level)
        for d, level in _daily_series(_START, _MATURE_DAYS, seed=10, vol=0.008)
    ]
    land_index(index_records, data_dir)

    benchmark_map_path = tmp_path / "benchmark_map.csv"
    _write_benchmark_map(benchmark_map_path, [])

    rf_path = tmp_path / "iima_rf.csv"
    _write_rf_csv(rf_path, _START, _START + timedelta(days=_MATURE_DAYS + 60))

    out_path = tmp_path / "out" / "metrics.json"
    summary = run(
        data_dir,
        out_path,
        rf_path=rf_path,
        benchmark_map_path=benchmark_map_path,
    )

    # Independently derive FRESH01's own last emitted month (single-fund
    # calendar) — with only 2 funds, the >=50% threshold is met by 1 fund
    # alone, so the cohort as_of is the *later* of the two funds' own last
    # months, which is FRESH01's.
    da = DataAccess(data_dir)
    fresh_nav = da.load_nav_series("FRESH01")
    fresh_cal = da.derive_trading_calendar(["FRESH01"])
    fresh_last_month = monthly_returns(fresh_nav, fresh_cal).dates[-1]
    assert summary.as_of == fresh_last_month

    with out_path.open() as fh:
        artifact = json.load(fh)
    fresh = _fund(artifact, "FRESH01")
    stale = _fund(artifact, "STALE02")

    for label in ("1Y", "3Y", "5Y"):
        assert stale["metrics"][f"volatility_{label}"] is None
        assert stale["metrics"][f"sharpe_{label}"] is None
        assert fresh["metrics"][f"volatility_{label}"] is not None
        assert fresh["metrics"][f"sharpe_{label}"] is not None


# ---------------------------------------------------------------------------
# B1 — identity checker wired into the runner (validation/identities.py):
# every fund row is cross-checked after assembly, before write; a violation
# aborts the whole build, no bypass.
# ---------------------------------------------------------------------------


def test_b1_fresh_zero_violations_on_fixture_universe(
    tmp_path: Path, universe: dict[str, Path]
) -> None:
    """B1-fresh acceptance: the fixture-universe run should produce zero
    identity violations. If this is red, it is reported verbatim (below) —
    never made to pass by loosening ``validation/identities.py``'s tolerances
    or adjusting this fixture.
    """
    out_path = tmp_path / "out" / "metrics.json"
    try:
        run(
            universe["data_dir"],
            out_path,
            rf_path=universe["rf_path"],
            benchmark_map_path=universe["benchmark_map_path"],
        )
    except IdentityCheckError as exc:
        pytest.fail(
            "B1-fresh is RED on the fixture universe -- reporting the "
            f"violating rows verbatim, per spec (not adjusted):\n{exc}"
        )


def test_identity_violation_flips_sharpe_sign_aborts_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, universe: dict[str, Path]
) -> None:
    """B1-wiring acceptance: patch one assembled value (flip a fund's
    ``sharpe_1Y`` sign, chosen because the sharpe identity holds cleanly on
    this fixture at baseline — unlike alpha, see
    ``test_b1_fresh_zero_violations_on_fixture_universe``) and assert the
    build raises, listing that fund/window/identity.
    """
    import foliolens.report.flexipage.runner as runner_module

    real_assemble_universe = runner_module.assemble_universe
    target_code = "AAAA01"

    def _corrupted_assemble_universe(panels: Any, **kwargs: Any) -> dict[str, Any]:
        result = real_assemble_universe(panels, **kwargs)
        fund = next(f for f in result["funds"] if f["amfi_code"] == target_code)
        sharpe = fund["metrics"]["sharpe_1Y"]
        assert sharpe is not None  # the mature fixture fund always has this
        fund["metrics"]["sharpe_1Y"] = -sharpe
        return result

    monkeypatch.setattr(runner_module, "assemble_universe", _corrupted_assemble_universe)

    out_path = tmp_path / "out" / "metrics.json"
    with pytest.raises(IdentityCheckError) as exc_info:
        run(
            universe["data_dir"],
            out_path,
            rf_path=universe["rf_path"],
            benchmark_map_path=universe["benchmark_map_path"],
        )
    message = str(exc_info.value)
    assert target_code in message
    assert "sharpe" in message
    assert "1Y" in message
