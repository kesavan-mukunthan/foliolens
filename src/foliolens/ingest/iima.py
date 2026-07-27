"""IIM-A factor-library parser — the 91-day T-bill (risk-free) column.

The IIM-A Indian Fama-French-Momentum monthly file carries a risk-free column
(RBI 91-day T-bill). This module extracts *only* that column into a monthly
``ReturnSeries`` and wraps it as a ``SeriesInvestment``. The other factor columns
(MRP/SMB/HML/WML) are out of scope here (spec-factor).

rf is return-space at birth — it never passes through ``returns/convert.py``.
IIM-A publishes monthly returns as *percent*; the parser divides by 100 once.

LICENSING: the IIM-A factor library is NOT licensed for redistribution (derived
from CMIE Prowess). Use as a computation input with citation; never republish the
series as data. See CLAUDE.md.

FILE SHAPE (confirmed against the IIM-A monthly four-factor CSV,
``YYYY-MM_FourFactors_and_Market_Returns_Monthly_SurvivorshipBiasAdjusted.csv``):
    Date,SMB,HML,WML,MF,RF
    1993-10,2.98,2.58,3.01,NA,NA
    1993-11,-9.42,-0.55,12.62,17.62,0.611432097208131
  date column = "Date" (YYYY-MM); rf column = "RF" (monthly percent). Leading
  months carry ``NA`` before the four-factor/rf history begins — those rows are
  skipped, so the rf series starts at the first month with a real RF value.
"""
from __future__ import annotations

import calendar
import csv
import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import numpy as np

from ..model.investments import SeriesInvestment
from ..model.value_objects import ReturnSeries
from ..returns.frequency import Frequency

_MONTH_FORMATS = ("%Y-%m", "%b-%Y", "%b-%y", "%m/%Y", "%Y%m")


def _month_end_date(raw: str) -> datetime.date:
    """Parse an IIM-A month label to the calendar month-end date.

    Monthly returns are anchored to month-end period-end dates (the analytics
    convention). Bare ``YYYYMM`` is handled explicitly; a small set of textual
    formats is tried after.
    """
    text = raw.strip()
    year: int | None = None
    month: int | None = None
    if len(text) == 6 and text.isdigit():
        year, month = int(text[:4]), int(text[4:])
    else:
        for fmt in _MONTH_FORMATS:
            try:
                parsed = datetime.datetime.strptime(text, fmt)
                year, month = parsed.year, parsed.month
                break
            except ValueError:
                continue
    if year is None or month is None or not (1 <= month <= 12):
        raise ValueError(f"unrecognised IIM-A month {raw!r}")
    last_day = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, last_day)


def parse_iima_rf(
    path: Path | str,
    *,
    date_col: str = "Date",
    rf_col: str = "RF",
    as_percent: bool = True,
) -> ReturnSeries:
    """Parse the IIM-A monthly file's risk-free column into a monthly ReturnSeries.

    ``as_percent`` (default True): IIM-A publishes monthly returns in percent, so
    each value is divided by 100. Dates are calendar month-ends, strictly
    ascending; duplicates fail loud. Rows whose RF cell is ``NA`` (leading
    pre-history months) are skipped. Float64 at birth — no convert seam applies.
    """
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"IIM-A: empty file {path}")
        header = [f.strip() for f in reader.fieldnames]
        for col in (date_col, rf_col):
            if col not in header:
                raise ValueError(
                    f"IIM-A: missing column {col!r}; saw {header}"
                )
        stripped = {orig: orig.strip() for orig in reader.fieldnames}
        pairs: list[tuple[datetime.date, float]] = []
        for row in reader:
            clean = {stripped[k]: (v or "") for k, v in row.items() if k is not None}
            date_raw = clean.get(date_col, "").strip()
            rf_raw = clean.get(rf_col, "").strip()
            if not date_raw and not rf_raw:
                continue
            if not rf_raw or rf_raw.upper() == "NA":
                continue  # rf unavailable this month (leading pre-history / gap)
            try:
                value = Decimal(rf_raw)
            except InvalidOperation as exc:
                raise ValueError(f"IIM-A: non-numeric rf {rf_raw!r}") from exc
            if as_percent:
                value = value / Decimal("100")
            pairs.append((_month_end_date(date_raw), float(value)))

    if not pairs:
        raise ValueError(f"IIM-A: no data rows in {path}")

    pairs.sort(key=lambda p: p[0])
    dates = tuple(d for d, _ in pairs)
    if len(set(dates)) != len(dates):
        raise ValueError("IIM-A: duplicate month in rf series")

    return ReturnSeries(
        dates=dates,
        values=np.array([v for _, v in pairs], dtype=np.float64),
        frequency=Frequency.MONTHLY,
    )


def rf_investment(path: Path | str) -> SeriesInvestment:
    """Canonical risk-free Investment: parse the IIM-A file → SeriesInvestment.

    Consumed via the Investment contract (Sharpe/Sortino read ``.returns``); no
    scalar rf ever reaches metrics.
    """
    return SeriesInvestment(id="rf-iima-91d-tbill", returns_series=parse_iima_rf(path))
