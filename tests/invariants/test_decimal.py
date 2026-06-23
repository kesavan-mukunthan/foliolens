"""Invariants: decimal128 roundtrip and no-float in return values."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from foliolens.data_access import DataAccess
from foliolens.ingest.land import land
from foliolens.ingest.mftool_client import NavRecord
from foliolens.model.sources import PricedSource
from foliolens.model.value_objects import NavSeries
from foliolens.returns.engine import period_return


def _records(amfi_code: str) -> list[NavRecord]:
    return [
        NavRecord(amfi_code=amfi_code, date=date(2020, 1, 2), nav=Decimal("50.123456")),
        NavRecord(amfi_code=amfi_code, date=date(2021, 1, 4), nav=Decimal("60.234567")),
        NavRecord(amfi_code=amfi_code, date=date(2022, 1, 3), nav=Decimal("72.345678")),
        NavRecord(amfi_code=amfi_code, date=date(2023, 1, 2), nav=Decimal("86.456789")),
        NavRecord(amfi_code=amfi_code, date=date(2024, 1, 2), nav=Decimal("95.567890")),
        NavRecord(amfi_code=amfi_code, date=date(2025, 1, 2), nav=Decimal("105.678901")),
    ]


def test_decimal_roundtrip(tmp_path: Path) -> None:
    """decimal128 parquet must load back as Decimal with exact equality — no DOUBLE cast."""
    recs = _records("111111")
    land(recs, tmp_path)

    da = DataAccess(tmp_path)
    ns = da.load_nav_series("111111")

    assert len(ns) == len(recs)
    for _, nav in ns.data:
        assert isinstance(nav, Decimal), f"expected Decimal, got {type(nav).__name__}"

    # exact values — any DOUBLE conversion would introduce rounding error
    assert ns.data[0][1] == Decimal("50.123456")
    assert ns.data[-1][1] == Decimal("105.678901")


def test_no_float_in_returns(tmp_path: Path) -> None:
    """Engine return values are Decimal, not float."""
    recs = _records("222222")
    land(recs, tmp_path)

    da = DataAccess(tmp_path)
    ns = da.load_nav_series("222222")
    source = PricedSource(nav=ns)

    result = period_return(source, "1Y", date(2025, 1, 2))

    assert isinstance(result.value, Decimal), f"value is {type(result.value).__name__}"
    assert isinstance(result.start_nav, Decimal)
    assert isinstance(result.end_nav, Decimal)
