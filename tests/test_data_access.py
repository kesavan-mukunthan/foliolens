"""DataAccess reads against the consolidated nav.parquet fixture.

Covers the per-fund figure-of-record seam (load_nav_series) and the bulk
path-of-scale seam (load_nav_panel), including the decimal128 guarantee.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pyarrow as pa

from foliolens.data_access import DataAccess

FIXTURES = Path(__file__).parent.parent / "fixtures" / "nav_snapshots"

# All 13 frozen fixture codes and their known row counts (see nav.parquet).
ALL_CODES = {
    "103340",
    "108466",
    "114616",
    "118663",
    "119018",
    "120197",
    "120334",
    "120381",
    "120586",
    "120591",
    "120679",
    "120754",
    "122639",
}


def _da() -> DataAccess:
    return DataAccess(FIXTURES)


def test_load_nav_series_known_code() -> None:
    ns = _da().load_nav_series("103340")
    assert ns.amfi_code == "103340"
    assert len(ns) == 6312
    # figures of record stay Decimal — no DOUBLE cast on the consolidated layout
    assert all(isinstance(nav, Decimal) for _, nav in ns.data)


def test_load_nav_panel_all_codes() -> None:
    tbl = _da().load_nav_panel()
    codes = set(tbl.column("amfi_code").to_pylist())
    assert codes == ALL_CODES
    assert tbl.num_rows == 48329


def test_load_nav_panel_filtered() -> None:
    tbl = _da().load_nav_panel(["103340", "108466"])
    codes = set(tbl.column("amfi_code").to_pylist())
    assert codes == {"103340", "108466"}
    assert tbl.num_rows == 6312 + 4444


def test_load_nav_panel_nav_is_decimal128() -> None:
    tbl = _da().load_nav_panel(["103340"])
    nav_type = tbl.schema.field("nav").type
    assert pa.types.is_decimal(nav_type), f"nav must stay decimal, got {nav_type}"
    assert not pa.types.is_floating(nav_type)
