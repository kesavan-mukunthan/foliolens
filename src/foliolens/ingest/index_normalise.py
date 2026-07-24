"""Per-source normalisers for benchmark index levels (TRI only).

Two manual-download sources, two file shapes, one output record:
``IndexRecord(index_code, date, level: Decimal)`` — a figure of record, landed
like NAV (Decimal on the path of record; no float here). The caller supplies the
canonical ``index_code`` (e.g. ``NIFTY500TRI``): each downloaded file is one
index, and name strings on the source vary ("Nifty 500" vs "NIFTY 500"), so the
code is passed in rather than parsed — deterministic and TRI-explicit.

Both parsers take a local file (no scraping; both sites are bot-protected) and
fail loud on a schema they do not recognise rather than silently mis-parse.

EXPECTED FILE SHAPES (verify against the real downloads; adjust here if they
differ — a column-name/date-format change is localised to this module):

- niftyindices.com TRI historical export (confirmed against a NIFTY 500 pull):
    Index Name,Date,Total Returns Index,Net Total Return Index
    NIFTY 500,01 Jan 1995,1000.00,-
  level column = "Total Returns Index" (the GROSS TRI — spec basis); the trailing
  "Net Total Return Index" (net-of-tax, "-" in early rows) is ignored. Date column
  is "Date" (older exports used "Index Date"; both accepted), format DD Mon YYYY.

- bseindia.com index historical export (TRI variant selected explicitly):
    Date,Open,High,Low,Close
    01-01-2020,...,...,...,"12,400.00"
  level column = "Close"; date = "Date" (DD-MM-YYYY). No index-name column.
"""
from __future__ import annotations

import csv
import datetime
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Date formats tried in order per source. Kept small and explicit — a silent
# wrong-format parse is worse than a loud failure naming the cell.
_NIFTY_DATE_FORMATS = ("%d %b %Y", "%d-%b-%Y", "%d-%m-%Y")
_BSE_DATE_FORMATS = ("%d-%m-%Y", "%d %b %Y", "%d-%b-%Y", "%d/%m/%Y")


@dataclass(frozen=True)
class IndexRecord:
    """One benchmark index level — a figure of record, Decimal throughout."""

    index_code: str
    date: datetime.date
    level: Decimal


def _parse_date(raw: str, formats: tuple[str, ...]) -> datetime.date:
    text = raw.strip()
    for fmt in formats:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(
        f"unrecognised date {raw!r}; tried {', '.join(formats)}"
    )


def _parse_level(raw: str) -> Decimal:
    # Source exports quote thousands-separated numbers ("12,345.67").
    text = raw.strip().replace(",", "")
    if not text:
        raise ValueError("empty level cell")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"non-numeric level {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"index level must be > 0, got {value}")
    return value


def _require_columns(header: list[str], needed: tuple[str, ...], source: str) -> None:
    present = {h.strip() for h in header}
    missing = [c for c in needed if c not in present]
    if missing:
        raise ValueError(
            f"{source}: missing expected column(s) {missing}; saw {header}"
        )


def _parse_two_column(
    path: Path,
    index_code: str,
    *,
    date_cols: tuple[str, ...],
    level_col: str,
    date_formats: tuple[str, ...],
    source: str,
) -> list[IndexRecord]:
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"{source}: empty file {path}")
        header = [f.strip() for f in reader.fieldnames]
        _require_columns(header, (level_col,), source)
        # The date header varies across exports ("Date" vs "Index Date"); accept
        # the first candidate present, fail loud if none is.
        present = {h.strip() for h in header}
        date_col = next((c for c in date_cols if c in present), None)
        if date_col is None:
            raise ValueError(
                f"{source}: no date column among {list(date_cols)}; saw {header}"
            )
        # Re-key rows on stripped headers so trailing-space column names still match.
        stripped = {orig: orig.strip() for orig in reader.fieldnames}
        records: list[IndexRecord] = []
        for row in reader:
            clean = {stripped[k]: (v or "") for k, v in row.items() if k is not None}
            date_raw = clean.get(date_col, "").strip()
            level_raw = clean.get(level_col, "").strip()
            if not date_raw and not level_raw:
                continue  # skip blank trailing lines
            records.append(
                IndexRecord(
                    index_code=index_code,
                    date=_parse_date(date_raw, date_formats),
                    level=_parse_level(level_raw),
                )
            )
    if not records:
        raise ValueError(f"{source}: no data rows in {path}")
    return records


def parse_niftyindices_tri(path: Path | str, index_code: str) -> list[IndexRecord]:
    """Parse a niftyindices.com TRI historical export into IndexRecords.

    ``index_code`` is the canonical TRI code for the file (e.g. ``NIFTY500TRI``).
    """
    return _parse_two_column(
        Path(path),
        index_code,
        date_cols=("Date", "Index Date"),
        level_col="Total Returns Index",
        date_formats=_NIFTY_DATE_FORMATS,
        source="niftyindices",
    )


def parse_bse_tri(path: Path | str, index_code: str) -> list[IndexRecord]:
    """Parse a bseindia.com index historical export (TRI variant) into IndexRecords.

    The BSE export carries no index-name column, so ``index_code`` (e.g.
    ``BSE500TRI``) is always supplied by the caller. Level = the Close column.
    """
    return _parse_two_column(
        Path(path),
        index_code,
        date_cols=("Date",),
        level_col="Close",
        date_formats=_BSE_DATE_FORMATS,
        source="bse",
    )
