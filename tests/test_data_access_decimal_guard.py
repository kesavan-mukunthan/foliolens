"""FL-IO-1 — decimal128 guard at read.

data_access must refuse to serve NAV/index data whose parquet physical type
is not decimal128(18, 6). Silent float64 degradation of the figures of
record (pandas rewrite, storage round-trip, future writer bug) becomes an
immediate located crash at first read, not a downstream precision finding.

Schema-only assertion — fixtures here are built directly with pyarrow
(never via the production land()/land_index() writers, which already write
correct decimal128) so a bad type can be injected deliberately.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from foliolens.data_access import DataAccess, DecimalTypeError

_DATES = [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)]


def _write_nav_parquet(
    dest: Path, *, nav_type: pa.DataType | None = pa.decimal128(18, 6)
) -> Path:
    """Write a minimal nav.parquet; nav_type=None omits the nav column."""
    fields = {
        "amfi_code": pa.array(["100000"] * len(_DATES), type=pa.string()),
        "date": pa.array(_DATES, type=pa.date32()),
    }
    if nav_type is not None:
        if pa.types.is_decimal(nav_type):
            scale = nav_type.scale
            fields["nav"] = pa.array(
                [Decimal(f"{100 + i}").quantize(Decimal(1).scaleb(-scale)) for i in range(len(_DATES))],
                type=nav_type,
            )
        else:
            fields["nav"] = pa.array(
                [100.0 + i for i in range(len(_DATES))], type=nav_type
            )
    table = pa.table(fields)
    out = dest / "nav.parquet"
    pq.write_table(table, out)
    return out


def _write_index_parquet(
    dest: Path, *, level_type: pa.DataType = pa.decimal128(18, 6)
) -> Path:
    fields = {
        "index_code": pa.array(["NIFTY500TRI"] * len(_DATES), type=pa.string()),
        "date": pa.array(_DATES, type=pa.date32()),
    }
    if pa.types.is_decimal(level_type):
        scale = level_type.scale
        fields["level"] = pa.array(
            [Decimal(f"{100 + i}").quantize(Decimal(1).scaleb(-scale)) for i in range(len(_DATES))],
            type=level_type,
        )
    else:
        fields["level"] = pa.array(
            [100.0 + i for i in range(len(_DATES))], type=level_type
        )
    table = pa.table(fields)
    out = dest / "index_nav.parquet"
    pq.write_table(table, out)
    return out


# ---------------------------------------------------------------------------
# float64 nav -> every nav reader raises
# ---------------------------------------------------------------------------


def test_load_nav_series_rejects_float64_nav(tmp_path: Path) -> None:
    _write_nav_parquet(tmp_path, nav_type=pa.float64())
    da = DataAccess(tmp_path)
    with pytest.raises(DecimalTypeError) as exc_info:
        da.load_nav_series("100000")
    msg = str(exc_info.value)
    assert str(tmp_path / "nav.parquet") in msg
    assert "float" in msg
    assert "decimal128(18, 6)" in msg


def test_load_nav_panel_rejects_float64_nav(tmp_path: Path) -> None:
    _write_nav_parquet(tmp_path, nav_type=pa.float64())
    da = DataAccess(tmp_path)
    with pytest.raises(DecimalTypeError) as exc_info:
        da.load_nav_panel()
    msg = str(exc_info.value)
    assert str(tmp_path / "nav.parquet") in msg
    assert "float" in msg
    assert "decimal128(18, 6)" in msg


def test_derive_trading_calendar_rejects_float64_nav(tmp_path: Path) -> None:
    _write_nav_parquet(tmp_path, nav_type=pa.float64())
    da = DataAccess(tmp_path)
    with pytest.raises(DecimalTypeError) as exc_info:
        da.derive_trading_calendar(["100000"])
    msg = str(exc_info.value)
    assert str(tmp_path / "nav.parquet") in msg
    assert "float" in msg
    assert "decimal128(18, 6)" in msg


# ---------------------------------------------------------------------------
# float64 level -> load_index_series raises
# ---------------------------------------------------------------------------


def test_load_index_series_rejects_float64_level(tmp_path: Path) -> None:
    _write_index_parquet(tmp_path, level_type=pa.float64())
    da = DataAccess(tmp_path)
    with pytest.raises(DecimalTypeError) as exc_info:
        da.load_index_series("NIFTY500TRI")
    msg = str(exc_info.value)
    assert str(tmp_path / "index_nav.parquet") in msg
    assert "float" in msg
    assert "decimal128(18, 6)" in msg


# ---------------------------------------------------------------------------
# wrong precision/scale decimal -> also raises (precision AND scale checked)
# ---------------------------------------------------------------------------


def test_load_nav_series_rejects_wrong_decimal_scale(tmp_path: Path) -> None:
    _write_nav_parquet(tmp_path, nav_type=pa.decimal128(18, 2))
    da = DataAccess(tmp_path)
    with pytest.raises(DecimalTypeError) as exc_info:
        da.load_nav_series("100000")
    assert "decimal128(18, 6)" in str(exc_info.value)


# ---------------------------------------------------------------------------
# missing column -> raises
# ---------------------------------------------------------------------------


def test_load_nav_series_rejects_missing_nav_column(tmp_path: Path) -> None:
    _write_nav_parquet(tmp_path, nav_type=None)
    da = DataAccess(tmp_path)
    with pytest.raises(DecimalTypeError) as exc_info:
        da.load_nav_series("100000")
    msg = str(exc_info.value)
    assert str(tmp_path / "nav.parquet") in msg
    assert "nav" in msg


def test_load_index_series_rejects_missing_level_column(tmp_path: Path) -> None:
    table = pa.table(
        {
            "index_code": pa.array(["NIFTY500TRI"] * len(_DATES), type=pa.string()),
            "date": pa.array(_DATES, type=pa.date32()),
        }
    )
    pq.write_table(table, tmp_path / "index_nav.parquet")
    da = DataAccess(tmp_path)
    with pytest.raises(DecimalTypeError) as exc_info:
        da.load_index_series("NIFTY500TRI")
    msg = str(exc_info.value)
    assert str(tmp_path / "index_nav.parquet") in msg
    assert "level" in msg


# ---------------------------------------------------------------------------
# correct files -> readers succeed (existing behaviour untouched)
# ---------------------------------------------------------------------------


def test_load_nav_series_succeeds_on_correct_decimal(tmp_path: Path) -> None:
    _write_nav_parquet(tmp_path)
    da = DataAccess(tmp_path)
    ns = da.load_nav_series("100000")
    assert len(ns) == len(_DATES)


def test_load_index_series_succeeds_on_correct_decimal(tmp_path: Path) -> None:
    _write_index_parquet(tmp_path)
    da = DataAccess(tmp_path)
    ns = da.load_index_series("NIFTY500TRI")
    assert len(ns) == len(_DATES)


def test_load_nav_panel_succeeds_on_correct_decimal(tmp_path: Path) -> None:
    _write_nav_parquet(tmp_path)
    da = DataAccess(tmp_path)
    tbl = da.load_nav_panel()
    assert tbl.num_rows == len(_DATES)


def test_derive_trading_calendar_succeeds_on_correct_decimal(tmp_path: Path) -> None:
    _write_nav_parquet(tmp_path)
    da = DataAccess(tmp_path)
    cal = da.derive_trading_calendar(["100000"])
    assert cal is not None


# ---------------------------------------------------------------------------
# memoisation: second read of a verified file does not re-read schema
# ---------------------------------------------------------------------------


def test_decimal_check_memoised_per_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_nav_parquet(tmp_path)
    da = DataAccess(tmp_path)

    da.load_nav_series("100000")  # first read: schema is verified and cached

    call_count = 0
    real_read_schema = pq.read_schema

    def _counting_read_schema(path: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        return real_read_schema(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "foliolens.data_access.pq.read_schema", _counting_read_schema
    )

    da.load_nav_series("100000")  # second read on the same instance/path
    da.load_nav_panel()

    assert call_count == 0, "verified path must not trigger a second read_schema call"


def test_decimal_check_not_memoised_across_instances(tmp_path: Path) -> None:
    _write_nav_parquet(tmp_path, nav_type=pa.float64())

    DataAccess(tmp_path)  # construction alone must stay legal (no file scan)

    with pytest.raises(DecimalTypeError):
        DataAccess(tmp_path).load_nav_series("100000")
