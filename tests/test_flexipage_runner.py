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
from foliolens.report.flexipage.runner import load_universe, run
from foliolens.data_access import DataAccess

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "flexipage-1.schema.json"

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
    assert artifact["schema_version"] == "flexipage-1"
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
# Ranks form a valid permutation over non-null funds (§7)
# ---------------------------------------------------------------------------


def test_ranks_form_valid_distribution_per_metric_window(artifact: dict[str, Any]) -> None:
    for key in RANK_SPECS:
        pcts = [f["ranks"][key]["pct"] for f in artifact["funds"]]
        present = [p for p in pcts if p is not None]
        if not present:
            continue
        assert all(0.0 < p <= 100.0 for p in present)
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
