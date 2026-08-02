"""Tests for the FL-DQ-2 hole-month audit module.

No network; no production parquet. Derive-holes tests use a small synthetic
nav.parquet built in-memory. Classify tests use the committed fixture shards.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from foliolens.audit.hole_months import (
    Hole,
    classify,
    count_shard_rows_in_month,
    derive_holes,
    load_shard,
)
from foliolens.ingest.mftool_client import normalise

FIXTURES = Path(__file__).parent / "fixtures" / "hole_months"
UPSTREAM_FIXTURE = FIXTURES / "111987_upstream.json.gz"
FETCH_SIDE_FIXTURE = FIXTURES / "synthetic_111987_fetch_side.json.gz"

# --------------------------------------------------------------------------- #
# Helper: build a minimal nav.parquet in a temp directory
# --------------------------------------------------------------------------- #

_NAV_SCHEMA = pa.schema(
    [
        pa.field("amfi_code", pa.string()),
        pa.field("date", pa.date32()),
        pa.field("nav", pa.decimal128(18, 6)),
    ]
)


def _build_nav_parquet(rows: list[tuple[str, str, str]], dest: Path) -> Path:
    """Write (amfi_code, YYYY-MM-DD, nav_str) rows to dest/nav.parquet."""
    import datetime
    from decimal import Decimal

    amfi_codes = [r[0] for r in rows]
    dates = [datetime.date.fromisoformat(r[1]) for r in rows]
    navs = [Decimal(r[2]) for r in rows]

    table = pa.table(
        {"amfi_code": amfi_codes, "date": dates, "nav": navs},
        schema=_NAV_SCHEMA,
    )
    out = dest / "nav.parquet"
    pq.write_table(table, out)
    return out


# --------------------------------------------------------------------------- #
# derive_holes — synthetic parquet tests
# --------------------------------------------------------------------------- #


def test_derive_holes_empty_when_no_interior_gaps():
    """A fund with contiguous months has no holes."""
    # Fund A: Jan-Mar 2022 — no gap, only 2 interior months (Feb 2022)
    rows = [
        ("A", "2022-01-15", "10.0"),
        ("A", "2022-02-15", "10.1"),
        ("A", "2022-03-15", "10.2"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        nav_path = _build_nav_parquet(rows, Path(tmp))
        holes = derive_holes(nav_path)
    assert holes == [], f"expected no holes, got {holes}"


def test_derive_holes_detects_single_interior_gap():
    """A fund missing a single interior month returns exactly that hole."""
    # Fund B: Jan 2022, then Mar 2022 — February 2022 is a hole
    rows = [
        ("B", "2022-01-15", "10.0"),
        ("B", "2022-03-15", "10.2"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        nav_path = _build_nav_parquet(rows, Path(tmp))
        holes = derive_holes(nav_path)
    assert len(holes) == 1
    assert holes[0] == Hole(amfi_code="B", month=(2022, 2))


def test_derive_holes_excludes_edge_months():
    """The month of first_date and the month of last_date are not holes."""
    # Fund C: only Jan and Mar 2022. Feb is interior → hole.
    # But Jan (first month) and Mar (last month) are edge months — never holes.
    rows = [
        ("C", "2022-01-31", "10.0"),
        ("C", "2022-03-01", "10.1"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        nav_path = _build_nav_parquet(rows, Path(tmp))
        holes = derive_holes(nav_path)
    assert len(holes) == 1
    assert holes[0].month == (2022, 2)


def test_derive_holes_multiple_consecutive_gaps():
    """Multiple consecutive missing months are each reported as a separate Hole."""
    rows = [
        ("D", "2022-01-10", "10.0"),
        ("D", "2022-05-10", "10.5"),  # Feb, Mar, Apr are holes
    ]
    with tempfile.TemporaryDirectory() as tmp:
        nav_path = _build_nav_parquet(rows, Path(tmp))
        holes = derive_holes(nav_path)
    months = [h.month for h in holes if h.amfi_code == "D"]
    assert set(months) == {(2022, 2), (2022, 3), (2022, 4)}


def test_derive_holes_multi_fund():
    """Holes are reported per fund; a fund with no gap contributes nothing."""
    rows = [
        ("E", "2022-01-10", "10.0"),
        ("E", "2022-03-10", "10.2"),  # Feb hole
        ("F", "2022-01-10", "10.0"),
        ("F", "2022-02-10", "10.1"),  # no hole
    ]
    with tempfile.TemporaryDirectory() as tmp:
        nav_path = _build_nav_parquet(rows, Path(tmp))
        holes = derive_holes(nav_path)
    e_holes = [h for h in holes if h.amfi_code == "E"]
    f_holes = [h for h in holes if h.amfi_code == "F"]
    assert len(e_holes) == 1
    assert e_holes[0].month == (2022, 2)
    assert f_holes == []


# --------------------------------------------------------------------------- #
# classify — fixture-based tests
# --------------------------------------------------------------------------- #


def test_classify_upstream_fixture():
    """Real upstream fixture: shard has no rows for the hole month (2011-03)."""
    payload = load_shard(UPSTREAM_FIXTURE)
    hole = Hole(amfi_code="111987", month=(2011, 3))
    assert classify(hole, payload) == "upstream"


def test_classify_fetch_side_fixture():
    """Synthetic fetch_side fixture: shard has rows for the hole month (2011-03)."""
    payload = load_shard(FETCH_SIDE_FIXTURE)
    hole = Hole(amfi_code="111987", month=(2011, 3))
    assert classify(hole, payload) == "fetch_side"


def test_classify_upstream_adjacent_months_have_data():
    """Upstream fixture: months flanking the hole do have shard rows."""
    payload = load_shard(UPSTREAM_FIXTURE)
    assert count_shard_rows_in_month(payload, (2011, 2)) > 0, "Feb 2011 should have rows"
    assert count_shard_rows_in_month(payload, (2011, 4)) > 0, "Apr 2011 should have rows"
    assert count_shard_rows_in_month(payload, (2011, 3)) == 0, "Mar 2011 should have 0 rows"


def test_classify_fetch_side_fixture_has_three_march_rows():
    """Synthetic fixture carries the 3 injected March 2011 rows."""
    payload = load_shard(FETCH_SIDE_FIXTURE)
    assert count_shard_rows_in_month(payload, (2011, 3)) == 3


# --------------------------------------------------------------------------- #
# Duplicate-date reasoning: why fetch_side cannot be explained by normalise()
# --------------------------------------------------------------------------- #


def test_normalise_dedup_cannot_vacate_a_month():
    """Prove that normalise()'s duplicate-date drop cannot explain a whole-month gap.

    Scenario: shard has two entries for 15-Mar-2011 (a duplicate date within
    the same month). normalise() drops the second one — but one record remains,
    so the month is NOT vacated. A hole month with a shard row is always a
    defect, never explained by dedup.
    """
    raw = {
        "data": [
            # newest-first: two identical dates in March 2011
            {"date": "15-03-2011", "nav": "10.85000"},
            {"date": "15-03-2011", "nav": "10.84000"},  # duplicate — will be dropped
            {"date": "14-02-2011", "nav": "10.82560"},
        ]
    }
    records = normalise("111987", raw)
    mar_records = [r for r in records if r.date.year == 2011 and r.date.month == 3]
    assert len(mar_records) == 1, (
        "after dedup, the one kept record still occupies March 2011 — "
        "the month is not vacated, so a shard row in the hole month is a defect"
    )


def test_normalise_dedup_removes_exact_date_duplicates():
    """normalise() retains the first occurrence of a duplicate date (newest in raw feed)."""
    raw = {
        "data": [
            {"date": "15-03-2011", "nav": "10.85000"},  # kept (first = newest)
            {"date": "15-03-2011", "nav": "10.84000"},  # dropped
        ]
    }
    records = normalise("111987", raw)
    assert len(records) == 1
    from decimal import Decimal
    assert records[0].nav == Decimal("10.85000"), "first occurrence (newest) is kept"


def test_classify_empty_shard_is_upstream():
    """A shard with an empty data list classifies any hole as upstream."""
    hole = Hole(amfi_code="111987", month=(2011, 3))
    assert classify(hole, {"data": []}) == "upstream"
    assert classify(hole, {}) == "upstream"
