"""Hole-month audit — detect and classify internal zero-NAV months.

An *internal* zero-NAV month for a fund is a calendar month (year, month) that:
- falls strictly between the fund's first and last NAV dates in nav.parquet
  (exclusive of the edge months containing those dates), AND
- contains zero NAV observations in nav.parquet.

Each hole is classified against the raw shard (raw/{amfi_code}.json.gz):

- ``'upstream'``   — the shard itself has zero rows dated in that month.
                     AMFI/mfapi published nothing; the gap is source-side.
- ``'fetch_side'`` — the shard has >= 1 row in that month but nav.parquet
                     does not; consolidation dropped data that existed in
                     the source. Any fetch_side hit is a defect finding:
                     normalise()'s duplicate-date drop cannot explain it,
                     because same-date duplicates share a date and cannot
                     vacate an entire calendar month that had a dated row.
"""
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import duckdb

Classification = Literal["upstream", "fetch_side"]

# Upper bound on the spine generation window — extend as the panel ages.
_SPINE_END = "DATE '2030-12-01'"


@dataclass(frozen=True)
class Hole:
    """One internal zero-NAV month for one fund."""

    amfi_code: str
    month: tuple[int, int]  # (year, calendar_month_number)


def derive_holes(nav_path: Path) -> list[Hole]:
    """Return every internal zero-NAV calendar month across all funds.

    *Internal* = the month falls strictly inside (first_date, last_date) for
    that fund, exclusive of the edge months. A month is present when at least
    one NAV row in nav.parquet is dated within it.

    Anchor (production panel, D-phase): distinct funds with >= 1 hole must
    land in [220, 236]. Outside that range the caller should treat the result
    as an adjudication point, not a silent discrepancy.
    """
    nav_str = str(nav_path)
    con = duckdb.connect()

    sql = f"""
    WITH fund_bounds AS (
        SELECT amfi_code, MIN(date) AS first_date, MAX(date) AS last_date
        FROM read_parquet(?) GROUP BY amfi_code
    ),
    fund_months AS (
        SELECT DISTINCT amfi_code, YEAR(date) AS yr, MONTH(date) AS mo
        FROM read_parquet(?)
    ),
    spine AS (
        SELECT amfi_code, YEAR(spine_date) AS yr, MONTH(spine_date) AS mo
        FROM fund_bounds
        CROSS JOIN (
            SELECT gs AS spine_date
            FROM generate_series(DATE '1995-01-01', {_SPINE_END}, INTERVAL '1 month') t(gs)
        ) g
        WHERE spine_date > date_trunc('month', first_date)
          AND spine_date < date_trunc('month', last_date)
    )
    SELECT s.amfi_code, s.yr, s.mo
    FROM spine s
    LEFT JOIN fund_months fm USING (amfi_code, yr, mo)
    WHERE fm.amfi_code IS NULL
    ORDER BY s.amfi_code, s.yr, s.mo
    """
    rows = con.execute(sql, [nav_str, nav_str]).fetchall()
    return [
        Hole(amfi_code=str(code), month=(int(yr), int(mo))) for code, yr, mo in rows
    ]


def classify(hole: Hole, shard_payload: dict[str, Any]) -> Classification:
    """Classify one hole as ``'upstream'`` or ``'fetch_side'``.

    ``shard_payload`` is the raw dict from ``raw/{amfi_code}.json.gz``:
    ``{'data': [{'date': 'DD-MM-YYYY', 'nav': '...'}, ...], ...}``.

    - If the shard contains zero rows whose date falls in ``hole.month``:
      ``'upstream'`` — the data never existed in the source feed.
    - If the shard contains >= 1 such row: ``'fetch_side'`` — the source had
      the data but our consolidation dropped it.  A fetch_side result is always
      a defect; see the module docstring for the duplicate-date argument.
    """
    yr, mo = hole.month
    mo_str = f"{mo:02d}"
    yr_str = str(yr)
    for row in shard_payload.get("data", []):
        date_str: str = row["date"]  # DD-MM-YYYY
        if date_str[3:5] == mo_str and date_str[6:] == yr_str:
            return "fetch_side"
    return "upstream"


def load_shard(shard_path: Path) -> dict[str, Any]:
    """Load a raw shard ``.json.gz`` and return the parsed dict."""
    with gzip.open(shard_path, "rt", encoding="utf-8") as f:
        return dict(json.load(f))


def count_shard_rows_in_month(
    shard_payload: dict[str, Any], month: tuple[int, int]
) -> int:
    """Count rows in shard_payload whose date falls in the given (year, month)."""
    yr, mo = month
    mo_str = f"{mo:02d}"
    yr_str = str(yr)
    return sum(
        1
        for row in shard_payload.get("data", [])
        if row["date"][3:5] == mo_str and row["date"][6:] == yr_str
    )
