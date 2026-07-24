"""spec-benchmarks §3 — index normalisers + land_index + load_index_series.

Synthetic CSVs encode the documented source shapes (niftyindices TRI, BSE TRI).
When the real downloads land, a column/date-format drift is a localised fix in
ingest/index_normalise.py; these tests pin the contract, not the live files.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from foliolens.data_access import DataAccess
from foliolens.ingest.index_normalise import (
    IndexRecord,
    parse_bse_tri,
    parse_niftyindices_tri,
)
from foliolens.ingest.land import land_index
from foliolens.model.investments import Benchmark, Investment, benchmark_from_index

# Mirrors the confirmed niftyindices export: "Date" (not "Index Date"), the gross
# "Total Returns Index" column, and a trailing net-TRI column that must be ignored
# (with "-" in early rows).
_NIFTY_CSV = (
    "Index Name,Date,Total Returns Index,Net Total Return Index\n"
    'NIFTY 500,01 Jan 2020,"12,345.67",-\n'
    'NIFTY 500,31 Jan 2020,"12,400.00",11800.00\n'
    'NIFTY 500,29 Feb 2020,"12,500.50",11890.00\n'
    "\n"  # trailing blank line — must be skipped, not error
)

_BSE_CSV = (
    "Date,Open,High,Low,Close\n"
    '01-01-2020,100,110,99,"12,400.00"\n'
    "31-01-2020,101,111,98,12500.25\n"
)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


# --- parsers ---------------------------------------------------------------


def test_niftyindices_parse(tmp_path: Path) -> None:
    recs = parse_niftyindices_tri(
        _write(tmp_path, "nifty500tri.csv", _NIFTY_CSV), "NIFTY500TRI"
    )
    assert [r.date for r in recs] == [
        date(2020, 1, 1),
        date(2020, 1, 31),
        date(2020, 2, 29),
    ]
    assert all(r.index_code == "NIFTY500TRI" for r in recs)
    assert recs[0].level == Decimal("12345.67")  # thousands separator stripped
    assert all(isinstance(r.level, Decimal) for r in recs)


def test_bse_parse_uses_close(tmp_path: Path) -> None:
    recs = parse_bse_tri(_write(tmp_path, "bse500tri.csv", _BSE_CSV), "BSE500TRI")
    assert [r.level for r in recs] == [Decimal("12400.00"), Decimal("12500.25")]
    assert [r.date for r in recs] == [date(2020, 1, 1), date(2020, 1, 31)]


def test_missing_column_fails_loud(tmp_path: Path) -> None:
    bad = _write(tmp_path, "bad.csv", "Index Name,Index Date\nNIFTY 500,01 Jan 2020\n")
    with pytest.raises(ValueError, match="Total Returns Index"):
        parse_niftyindices_tri(bad, "NIFTY500TRI")


def test_negative_level_fails_loud(tmp_path: Path) -> None:
    bad = _write(
        tmp_path,
        "neg.csv",
        "Date,Open,High,Low,Close\n01-01-2020,1,1,1,-5\n",
    )
    with pytest.raises(ValueError, match="must be > 0"):
        parse_bse_tri(bad, "BSE500TRI")


# --- land + read round-trip ------------------------------------------------


def _records() -> list[IndexRecord]:
    return [
        IndexRecord("NIFTY500TRI", date(2020, 1, 31), Decimal("100.000000")),
        IndexRecord("NIFTY500TRI", date(2020, 2, 29), Decimal("102.000000")),
        IndexRecord("NIFTY500TRI", date(2020, 3, 31), Decimal("105.060000")),
        IndexRecord("BSE500TRI", date(2020, 1, 31), Decimal("200.000000")),
        IndexRecord("BSE500TRI", date(2020, 2, 29), Decimal("204.000000")),
    ]


def test_land_index_roundtrips_as_navseries(tmp_path: Path) -> None:
    land_index(_records(), tmp_path)
    ns = DataAccess(tmp_path).load_index_series("NIFTY500TRI")
    assert ns.amfi_code == "NIFTY500TRI"  # identifier field carries index_code
    assert len(ns) == 3
    assert ns.data[0] == (date(2020, 1, 31), Decimal("100.000000"))
    assert all(isinstance(level, Decimal) for _, level in ns.data)


def test_land_index_level_is_decimal128(tmp_path: Path) -> None:
    path = land_index(_records(), tmp_path)
    level_type = pq.read_table(path).schema.field("level").type  # type: ignore[no-untyped-call]
    assert pa.types.is_decimal(level_type)
    assert not pa.types.is_floating(level_type)


def test_land_index_sorted_and_idempotent(tmp_path: Path) -> None:
    # Reversed input must still land sorted by (index_code, date).
    land_index(list(reversed(_records())), tmp_path)
    first = pq.read_table(tmp_path / "index_nav.parquet").to_pylist()  # type: ignore[no-untyped-call]
    codes = [r["index_code"] for r in first]
    assert codes == sorted(codes)
    # Re-landing the same records overwrites, not appends.
    land_index(_records(), tmp_path)
    second = pq.read_table(tmp_path / "index_nav.parquet")  # type: ignore[no-untyped-call]
    assert second.num_rows == len(_records())


def test_missing_index_code_fails_loud(tmp_path: Path) -> None:
    land_index(_records(), tmp_path)
    with pytest.raises(ValueError, match="no index data"):
        DataAccess(tmp_path).load_index_series("SENSEXTRI")


# --- benchmark Investment --------------------------------------------------


def _check_investment(x: Investment) -> None:
    """Typed gate: mypy rejects if x doesn't structurally satisfy Investment."""


def test_benchmark_returns_monthly_float64(tmp_path: Path) -> None:
    land_index(_records(), tmp_path)
    levels = DataAccess(tmp_path).load_index_series("NIFTY500TRI")
    bench = benchmark_from_index(levels)
    _check_investment(bench)
    assert isinstance(bench, Benchmark)
    assert bench.id == "NIFTY500TRI"
    r = bench.returns
    assert r.values.dtype.name == "float64"
    assert len(r) == 2  # 3 month-ends → 2 returns
