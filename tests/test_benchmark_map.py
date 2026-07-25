"""spec-benchmarks §2 — benchmark_map loader + load_scheme_master join.

Covers the typed loader (validation, duplicate rejection), the joined read's
NULL semantics and category-yardstick resolution, and the gate: Bandhan Flexi
Cap resolves to a benchmark Investment via load_scheme_master with no
special-casing. The committed fixture is also validated as it ships.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from foliolens.benchmark_map import (
    BenchmarkMapRow,
    DEFAULT_BENCHMARK_MAP,
    load_benchmark_map,
)
from foliolens.data_access import DataAccess
from foliolens.ingest.land import land_index
from foliolens.ingest.scheme_master import land_scheme_master, scheme_record
from foliolens.model.investments import Benchmark, benchmark_from_index

_BANDHAN = "118424"


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "benchmark_map.csv"
    p.write_text(body, encoding="utf-8")
    return p


# --- typed loader ----------------------------------------------------------


def test_load_benchmark_map_parses_rows(tmp_path: Path) -> None:
    rows = load_benchmark_map(
        _write(
            tmp_path,
            "amfi_code,benchmark_code,tier\n"
            "118424,BSE500TRI,tier1\n"
            "118424,NIFTY50TRI,alternate\n",
        )
    )
    assert rows == (
        BenchmarkMapRow("118424", "BSE500TRI", "tier1"),
        BenchmarkMapRow("118424", "NIFTY50TRI", "alternate"),
    )


def test_load_benchmark_map_skips_comments_and_blanks(tmp_path: Path) -> None:
    rows = load_benchmark_map(
        _write(
            tmp_path,
            "# a comment\n\namfi_code,benchmark_code,tier\n"
            "# another\n122639,NIFTY500TRI,tier1\n",
        )
    )
    assert rows == (BenchmarkMapRow("122639", "NIFTY500TRI", "tier1"),)


def test_load_benchmark_map_duplicate_amfi_tier_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        load_benchmark_map(
            _write(
                tmp_path,
                "amfi_code,benchmark_code,tier\n"
                "118424,BSE500TRI,tier1\n"
                "118424,NIFTY500TRI,tier1\n",
            )
        )


def test_load_benchmark_map_unknown_tier_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="tier"):
        load_benchmark_map(
            _write(
                tmp_path,
                "amfi_code,benchmark_code,tier\n118424,BSE500TRI,primary\n",
            )
        )


def test_load_benchmark_map_bad_header_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="header"):
        load_benchmark_map(
            _write(tmp_path, "code,bench,tier\n118424,BSE500TRI,tier1\n")
        )


def test_committed_fixture_loads_and_has_bandhan() -> None:
    rows = load_benchmark_map(DEFAULT_BENCHMARK_MAP)
    bandhan = {r.tier: r.benchmark_code for r in rows if r.amfi_code == _BANDHAN}
    assert bandhan == {"tier1": "BSE500TRI", "alternate": "NIFTY50TRI"}
    # Every code encodes TRI — no PRI anywhere (design decision + acceptance §3).
    assert all("TRI" in r.benchmark_code for r in rows)


# --- load_scheme_master join ----------------------------------------------


def _land_master(tmp_path: Path) -> None:
    """Two flexicap direct-growth schemes: Bandhan (curated) + one uncurated."""
    land_scheme_master(
        [
            scheme_record(
                _BANDHAN,
                {
                    "scheme_name": "BANDHAN Flexi Cap Fund-Direct Plan-Growth",
                    "fund_house": "Bandhan Mutual Fund",
                    "scheme_category": "Equity Scheme - Flexi Cap Fund",
                },
            ),
            scheme_record(
                "999999",
                {
                    "scheme_name": "Nobench Flexi Cap Fund - Direct Plan - Growth",
                    "fund_house": "Nobench Mutual Fund",
                    "scheme_category": "Equity Scheme - Flexi Cap Fund",
                },
            ),
        ],
        tmp_path,
    )


def _map(tmp_path: Path) -> Path:
    return _write(
        tmp_path,
        "amfi_code,benchmark_code,tier\n"
        "118424,BSE500TRI,tier1\n"
        "118424,NIFTY50TRI,alternate\n",
    )


def test_join_resolves_bandhan_tier1_and_alternate(tmp_path: Path) -> None:
    _land_master(tmp_path)
    table = DataAccess(tmp_path).load_scheme_master(_map(tmp_path))
    rows = {r["amfi_code"]: r for r in table.to_pylist()}
    b = rows[_BANDHAN]
    assert b["benchmark_code"] == "BSE500TRI"  # tier-1 preferred
    assert b["benchmark_tier"] == "tier1"
    assert b["benchmark_alternate"] == "NIFTY50TRI"
    assert b["category_yardstick"] == "NIFTY500TRI"


def test_join_null_semantics_for_uncurated(tmp_path: Path) -> None:
    _land_master(tmp_path)
    table = DataAccess(tmp_path).load_scheme_master(_map(tmp_path))
    rows = {r["amfi_code"]: r for r in table.to_pylist()}
    u = rows["999999"]
    # Not yet curated -> NULL benchmark, never a silently-defaulted one...
    assert u["benchmark_code"] is None
    assert u["benchmark_tier"] is None
    assert u["benchmark_alternate"] is None
    # ...but still resolvable to the category yardstick.
    assert u["category_yardstick"] == "NIFTY500TRI"


def test_join_tier1_only_scheme(tmp_path: Path) -> None:
    land_scheme_master(
        [
            scheme_record(
                "122639",
                {
                    "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                    "fund_house": "PPFAS Mutual Fund",
                    "scheme_category": "Equity Scheme - Flexi Cap Fund",
                },
            )
        ],
        tmp_path,
    )
    mapping = _write(
        tmp_path,
        "amfi_code,benchmark_code,tier\n122639,NIFTY500TRI,tier1\n",
    )
    row = DataAccess(tmp_path).load_scheme_master(mapping).to_pylist()[0]
    assert row["benchmark_code"] == "NIFTY500TRI"
    assert row["benchmark_tier"] == "tier1"
    assert row["benchmark_alternate"] is None


# --- acceptance §1: Bandhan -> benchmark Investment, no special-casing ------


def test_bandhan_resolves_to_benchmark_investment(tmp_path: Path) -> None:
    _land_master(tmp_path)
    # Land the stated tier-1 index so the resolved code has a series.
    land_index(
        [
            _idx("BSE500TRI", date(2020, 1, 31), "100.000000"),
            _idx("BSE500TRI", date(2020, 2, 29), "102.000000"),
            _idx("BSE500TRI", date(2020, 3, 31), "105.060000"),
        ],
        tmp_path,
    )
    da = DataAccess(tmp_path)
    rows = {r["amfi_code"]: r for r in da.load_scheme_master(_map(tmp_path)).to_pylist()}

    # Generic path — read benchmark_code off the row, build the Investment.
    code = rows[_BANDHAN]["benchmark_code"]
    bench = benchmark_from_index(da.load_index_series(code))
    assert isinstance(bench, Benchmark)
    assert bench.id == "BSE500TRI"
    assert bench.returns.values.dtype.name == "float64"


def _idx(code: str, d: date, level: str):  # type: ignore[no-untyped-def]
    from foliolens.ingest.index_normalise import IndexRecord

    return IndexRecord(code, d, Decimal(level))
