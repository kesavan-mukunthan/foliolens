"""mftool client — all mftool calls are isolated here.

Fetches full NAV history by amfi_code and normalises to
(amfi_code, date, nav) with nav as Decimal. Distinguishes holidays/weekends
from missing data; no forward-fill in the raw layer.

Real mftool response shape (verified against live API):
  {
    'fund_house': str,
    'scheme_code': int,
    'scheme_name': str,
    ...
    'data': [{'date': 'DD-MM-YYYY', 'nav': 'NNN.NNNNN'}, ...],  # newest-first
  }
  Returns None for an unknown scheme code.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

from mftool import Mftool  # isolated here; no other module imports mftool

_DATE_FMT = "%d-%m-%Y"


@dataclass(frozen=True)
class NavRecord:
    amfi_code: str
    date: datetime.date
    nav: Decimal


def fetch_nav_history(amfi_code: str) -> dict[str, Any] | None:
    """Call mftool and return its raw response dict, or None if not found.

    This is the only function in the codebase that instantiates Mftool.
    """
    mf = Mftool()
    return cast(dict[str, Any] | None, mf.get_scheme_historical_nav(str(amfi_code)))


def normalise(amfi_code: str, raw: dict[str, Any]) -> list[NavRecord]:
    """Convert a raw mftool response dict to a sorted, de-duplicated NavRecord list.

    Pure function — no network calls. Safe to call in unit tests with
    hand-built dicts.

    Rules applied:
    - date parsed from 'DD-MM-YYYY' to datetime.date
    - nav converted from string to Decimal (no float intermediate)
    - sorted ascending by date
    - duplicate (amfi_code, date) pairs dropped; first occurrence in the raw
      feed is kept (raw is newest-first, so 'first' means the newest nav for
      that date — conservative choice; in practice duplicates are rare)
    - no forward-fill: only dates present in the raw feed appear in output
    """
    seen: set[datetime.date] = set()
    records: list[NavRecord] = []

    for item in raw.get("data", []):
        d = datetime.datetime.strptime(item["date"], _DATE_FMT).date()
        if d in seen:
            continue
        seen.add(d)
        records.append(
            NavRecord(
                amfi_code=str(amfi_code),
                date=d,
                nav=Decimal(item["nav"]),
            )
        )

    records.sort(key=lambda r: r.date)
    return records


def get_nav_history(amfi_code: str) -> list[NavRecord]:
    """Fetch and normalise the full NAV history for one fund.

    Raises ValueError if mftool returns no data for the given code.
    """
    raw = fetch_nav_history(amfi_code)
    if raw is None:
        raise ValueError(f"mftool returned no data for amfi_code={amfi_code!r}")
    return normalise(str(amfi_code), raw)
