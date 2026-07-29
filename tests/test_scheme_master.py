"""spec-benchmarks §1 — scheme master derivation from backfill shards.

Category normaliser + plan/option name parser (flagged NULL, never guessed);
``scheme_record`` per shard; ``land_scheme_master`` round-trip; and the
``consolidate()`` integration that derives nav + scheme_master in one pass.
Scheme names are the real AMFI strings observed in the universe shards.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from datetime import date

from foliolens.ingest.scheme_master import (
    SchemeMasterRecord,
    land_scheme_master,
    normalise_category,
    parse_inception_date,
    parse_option,
    parse_plan,
    scheme_record,
)
from foliolens.ingest.universe import consolidate


# --- category normaliser ---------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Equity Scheme - Flexi Cap Fund", "flexi_cap"),
        ("Equity Scheme - Large Cap Fund", "large_cap"),
        ("Equity Scheme - Large & Mid Cap Fund", "large_mid_cap"),
        ("Equity Scheme - Mid Cap Fund", "mid_cap"),
        ("Equity Scheme - ELSS", "elss"),
        ("Debt Scheme - Liquid Fund", "liquid"),
        ("Other Scheme - FoF Domestic", "fof_domestic"),
        ("Other Scheme - Index Funds", "index"),
        ("Income/Debt Oriented Schemes - Liquid Fund", "liquid"),
        ("IDF", "idf"),
    ],
)
def test_normalise_category(raw: str, expected: str) -> None:
    assert normalise_category(raw) == expected


def test_normalise_category_blank_is_none() -> None:
    assert normalise_category("") is None
    assert normalise_category(None) is None
    assert normalise_category("   ") is None


# --- plan parser -----------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [
        ("BANDHAN Flexi Cap Fund-Direct Plan-Growth", "direct"),
        ("CANARA ROBECO FLEXICAP FUND - DIRECT PLAN - GROWTH OPTION", "direct"),
        ("JM Flexicap Fund (Direct) - Growth Option", "direct"),
        ("Kotak Flexicap Fund - Growth - Direct", "direct"),
        ("BANDHAN Flexi Cap Fund - Regular Plan - Growth", "regular"),
        ("Bajaj Finserv Flexi Cap Fund -Regular Plan-Growth", "regular"),
        # No plan token in the name -> NULL, not guessed.
        ("Franklin India Flexi Cap Fund - Growth", None),
        ("ICICI Prudential Flexicap Fund - Growth", None),
    ],
)
def test_parse_plan(name: str, expected: str | None) -> None:
    assert parse_plan(name) == expected


# --- option parser ---------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [
        ("BANDHAN Flexi Cap Fund-Direct Plan-Growth", "growth"),
        ("Franklin India Flexi Cap Fund - Growth", "growth"),
        ("BANDHAN Flexi Cap Fund - Regular Plan - IDCW", "idcw"),
        ("Sundaram Flexicap Fund Direct Plan IDCW Reinvestment", "idcw"),
        # Legacy "Dividend" label and the fully-spelled IDCW phrase.
        ("UTI MMF - Regular Plan - Flexi Dividend Option", "idcw"),
        (
            "TATA Flexi Cap Fund Direct Plan - Reinvestment of Income "
            "Distribution cum capital withdrawal option",
            "idcw",
        ),
        # No option token -> NULL.
        ("Some Fund - Direct Plan", None),
    ],
)
def test_parse_option(name: str, expected: str | None) -> None:
    assert parse_option(name) == expected


# --- inception_date parser (Manifest F-INC) --------------------------------
#
# No mftool response fixture is committed in this repo, so the field name is
# verified here against a *recorded* mftool ``get_scheme_details`` payload
# (mftool 3.3: ``scheme_start_date`` is a ``{'date': 'DD-MM-YYYY', 'nav': ...}``
# object, synthesised as the oldest NAV entry). Confirming the same field name
# on a live response is left as a local follow-up (the universe backfill shards
# come from the NAV-history endpoint, which does not itself carry the field).


def test_parse_inception_date_from_recorded_scheme_details() -> None:
    # A recorded mftool get_scheme_details payload shape for amfi_code 118424.
    recorded = {
        "fund_house": "Bandhan Mutual Fund",
        "scheme_type": "Open Ended Schemes",
        "scheme_category": "Equity Scheme - Flexi Cap Fund",
        "scheme_code": 118424,
        "scheme_name": "BANDHAN Flexi Cap Fund-Direct Plan-Growth",
        "scheme_start_date": {"date": "28-09-2005", "nav": "10.00000"},
    }
    assert parse_inception_date(recorded) == date(2005, 9, 28)


def test_parse_inception_date_accepts_plain_string() -> None:
    assert parse_inception_date({"scheme_start_date": "01-01-2013"}) == date(2013, 1, 1)


@pytest.mark.parametrize(
    "raw",
    [
        {},  # field entirely absent
        {"scheme_start_date": None},
        {"scheme_start_date": ""},
        {"scheme_start_date": {"date": "", "nav": "10.0"}},
        {"scheme_start_date": {"nav": "10.0"}},  # dict without a date key
        {"scheme_start_date": "not-a-date"},
        {"scheme_start_date": "2013-01-01"},  # wrong (ISO) format, not DD-MM-YYYY
    ],
)
def test_parse_inception_date_null_tolerant(raw: dict[str, Any]) -> None:
    # A missing / empty / unparseable inception is "unknown" (None), never
    # fabricated and never raised.
    assert parse_inception_date(raw) is None


# --- scheme_record ---------------------------------------------------------


def _raw(**kw: Any) -> dict[str, Any]:
    base = {
        "scheme_name": "BANDHAN Flexi Cap Fund-Direct Plan-Growth",
        "fund_house": "Bandhan Mutual Fund",
        "scheme_category": "Equity Scheme - Flexi Cap Fund",
        "scheme_code": 118424,
    }
    base.update(kw)
    return base


def test_scheme_record_classifies_flexicap() -> None:
    rec = scheme_record("118424", _raw())
    assert rec == SchemeMasterRecord(
        amfi_code="118424",
        scheme_name="BANDHAN Flexi Cap Fund-Direct Plan-Growth",
        fund_house="Bandhan Mutual Fund",
        scheme_category="Equity Scheme - Flexi Cap Fund",
        sebi_category="flexi_cap",
        plan="direct",
        option="growth",
    )


def test_scheme_record_unparsed_plan_is_null_not_wrong() -> None:
    # "Franklin India Flexi Cap Fund - Growth" names no plan: plan must be NULL,
    # option still resolves to growth.
    rec = scheme_record(
        "118535",
        _raw(scheme_name="Franklin India Flexi Cap Fund - Growth"),
    )
    assert rec.plan is None
    assert rec.option == "growth"
    assert rec.sebi_category == "flexi_cap"


def test_scheme_record_category_from_field_not_name() -> None:
    # A "Flexi IDCW" in the name is an IDCW frequency, not a flexi-cap category:
    # sebi_category keys off scheme_category, so this is credit_risk, not flexi_cap.
    rec = scheme_record(
        "136302",
        _raw(
            scheme_name="UTI Credit Risk Fund - Direct Plan - Flexi IDCW",
            scheme_category="Debt Scheme - Credit Risk Fund",
        ),
    )
    assert rec.sebi_category == "credit_risk"
    assert rec.option == "idcw"


def test_scheme_record_reads_inception_when_present() -> None:
    rec = scheme_record(
        "118424",
        _raw(scheme_start_date={"date": "28-09-2005", "nav": "10.00000"}),
    )
    assert rec.inception_date == date(2005, 9, 28)


def test_scheme_record_inception_null_when_absent() -> None:
    # The default _raw() carries no scheme_start_date -> inception is unknown.
    assert scheme_record("118424", _raw()).inception_date is None


# --- land round-trip -------------------------------------------------------


def _records() -> list[SchemeMasterRecord]:
    return [
        scheme_record("118424", _raw()),
        scheme_record(
            "118535",
            _raw(scheme_name="Franklin India Flexi Cap Fund - Direct - Growth"),
        ),
    ]


def test_land_scheme_master_roundtrip(tmp_path: Path) -> None:
    path = land_scheme_master(list(reversed(_records())), tmp_path)
    table = pq.read_table(path)  # type: ignore[no-untyped-call]
    assert table.num_rows == 2
    # Sorted by amfi_code regardless of input order.
    assert table.column("amfi_code").to_pylist() == ["118424", "118535"]
    assert table.column("sebi_category").to_pylist() == ["flexi_cap", "flexi_cap"]
    # Every column is a string except inception_date, which is a parquet date32
    # (nullable columns hold real nulls, exercised in
    # test_land_scheme_master_holds_real_nulls).
    assert all(
        pa.types.is_string(f.type)
        for f in table.schema
        if f.name != "inception_date"
    )
    assert pa.types.is_date(table.schema.field("inception_date").type)


def test_land_scheme_master_holds_real_nulls(tmp_path: Path) -> None:
    rec = scheme_record(
        "999999",
        _raw(scheme_name="Mystery Fund", scheme_category=""),
    )
    path = land_scheme_master([rec], tmp_path)
    row = pq.read_table(path).to_pylist()[0]  # type: ignore[no-untyped-call]
    assert row["sebi_category"] is None
    assert row["plan"] is None
    assert row["option"] is None
    assert row["inception_date"] is None


def test_land_scheme_master_roundtrips_inception_date(tmp_path: Path) -> None:
    # A date survives parquet write -> read as a datetime.date (date32 column);
    # a null inception coexists in the same column.
    records = [
        scheme_record(
            "118424",
            _raw(scheme_start_date={"date": "28-09-2005", "nav": "10.0"}),
        ),
        scheme_record("999999", _raw(scheme_name="Mystery Fund")),  # no inception
    ]
    path = land_scheme_master(records, tmp_path)
    by_code = {r["amfi_code"]: r for r in pq.read_table(path).to_pylist()}  # type: ignore[no-untyped-call]
    assert by_code["118424"]["inception_date"] == date(2005, 9, 28)
    assert by_code["999999"]["inception_date"] is None


def test_land_scheme_master_empty_fails_loud(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no scheme_master records"):
        land_scheme_master([], tmp_path)


# --- consolidate integration ----------------------------------------------


def _write_shard(data_dir: Path, code: str, raw: dict[str, Any]) -> None:
    raw = {**raw, "data": [{"date": "31-01-2020", "nav": "10.00000"}]}
    p = data_dir / "raw" / f"{code}.json.gz"
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump(raw, fh)


def test_consolidate_derives_scheme_master_row_per_shard(tmp_path: Path) -> None:
    _write_shard(tmp_path, "118424", _raw())
    _write_shard(
        tmp_path,
        "118535",
        _raw(scheme_name="Franklin India Flexi Cap Fund - Growth"),
    )
    consolidate(tmp_path)

    assert (tmp_path / "nav.parquet").exists()
    master = pq.read_table(tmp_path / "scheme_master.parquet")  # type: ignore[no-untyped-call]
    assert master.num_rows == 2  # one row per shard
    by_code = {r["amfi_code"]: r for r in master.to_pylist()}
    assert by_code["118424"]["sebi_category"] == "flexi_cap"
    assert by_code["118424"]["plan"] == "direct"
    # Franklin names no plan -> NULL, not guessed.
    assert by_code["118535"]["plan"] is None
    assert by_code["118535"]["option"] == "growth"
