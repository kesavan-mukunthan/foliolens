"""Unit tests for the mftool_client normaliser.

No network: all tests operate on hand-built dicts passed to normalise().
The conftest _no_network fixture guards against accidental live calls.
"""
import datetime
from decimal import Decimal

import pytest

from foliolens.ingest.mftool_client import NavRecord, normalise


CODE = "120586"


def _raw(*entries: tuple[str, str]) -> dict:
    """Build a minimal raw dict in mftool's shape from (date_str, nav_str) pairs."""
    return {"data": [{"date": d, "nav": n} for d, n in entries]}


def test_normalise_sorts_ascending():
    raw = _raw(
        ("15-06-2026", "100.5000"),
        ("13-06-2026", "99.0000"),
        ("14-06-2026", "99.8000"),
    )
    result = normalise(CODE, raw)
    dates = [r.date for r in result]
    assert dates == sorted(dates), "records must be sorted ascending by date"


def test_normalise_drops_duplicate_date():
    raw = _raw(
        ("15-06-2026", "100.5000"),
        ("15-06-2026", "101.0000"),  # duplicate date — second dropped
        ("14-06-2026", "99.8000"),
    )
    result = normalise(CODE, raw)
    date_15 = datetime.date(2026, 6, 15)
    assert len(result) == 2
    assert sum(1 for r in result if r.date == date_15) == 1, \
        "duplicate (amfi_code, date) must be de-duplicated to one row"


def test_normalise_nav_is_decimal():
    raw = _raw(("15-06-2026", "118.70000"))
    result = normalise(CODE, raw)
    assert len(result) == 1
    assert isinstance(result[0].nav, Decimal), "nav must be Decimal, not float"
    assert result[0].nav == Decimal("118.70000")


def test_normalise_amfi_code_is_string():
    raw = _raw(("15-06-2026", "118.70000"))
    result = normalise(CODE, raw)
    assert isinstance(result[0].amfi_code, str)


def test_normalise_date_is_date_object():
    raw = _raw(("15-06-2026", "118.70000"))
    result = normalise(CODE, raw)
    assert isinstance(result[0].date, datetime.date)
    assert result[0].date == datetime.date(2026, 6, 15)


def test_normalise_empty_data():
    result = normalise(CODE, {"data": []})
    assert result == []


def test_normalise_no_forward_fill():
    """Gaps between dates are preserved — no fabricated rows."""
    raw = _raw(
        ("17-06-2026", "102.0000"),
        ("13-06-2026", "99.0000"),  # 14, 15, 16 are absent (weekend/holiday)
    )
    result = normalise(CODE, raw)
    assert len(result) == 2, "only dates present in raw feed should appear"
    assert result[0].date == datetime.date(2026, 6, 13)
    assert result[1].date == datetime.date(2026, 6, 17)
