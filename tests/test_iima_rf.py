"""spec-benchmarks §5 — IIM-A 91-day T-bill parse → rf ReturnSeries / Investment.

CSV mirrors the confirmed IIM-A monthly four-factor shape (header
``Date,SMB,HML,WML,MF,RF``; Date=YYYY-MM; RF in percent; leading months carry
``NA``). rf is return-space at birth — no NAV, no convert seam.
"""
from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from foliolens.ingest.iima import (
    RF_EXTENSION_CAP_MONTHS,
    RfExtension,
    extend_rf,
    parse_iima_rf,
    rf_investment,
)
from foliolens.model.investments import Investment, SeriesInvestment
from foliolens.model.value_objects import ReturnSeries
from foliolens.returns.frequency import Frequency

_IIMA_CSV = (
    "Date,SMB,HML,WML,MF,RF\n"
    "1993-10,2.98,2.58,3.01,NA,NA\n"  # leading pre-history row — RF=NA, skipped
    "2020-01,3.21,-0.44,1.10,0.88,0.50\n"
    "2020-02,-1.05,0.30,-0.20,0.11,0.48\n"
    "2020-03,-8.40,1.20,-2.10,0.40,0.45\n"
)


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "iima_monthly.csv"
    p.write_text(body, encoding="utf-8")
    return p


def test_parse_percent_to_decimal_fraction(tmp_path: Path) -> None:
    rs = parse_iima_rf(_write(tmp_path, _IIMA_CSV))
    # 0.50 percent -> 0.005 as a fraction
    assert rs.values[0] == pytest.approx(0.005)
    assert rs.values[2] == pytest.approx(0.0045)


def test_na_rows_skipped_series_starts_at_first_real_rf(tmp_path: Path) -> None:
    rs = parse_iima_rf(_write(tmp_path, _IIMA_CSV))
    # 1993-10 RF=NA is dropped; series begins at 2020-01.
    assert len(rs) == 3
    assert rs.dates[0] == date(2020, 1, 31)


def test_parse_month_end_dates(tmp_path: Path) -> None:
    rs = parse_iima_rf(_write(tmp_path, _IIMA_CSV))
    assert rs.dates == (date(2020, 1, 31), date(2020, 2, 29), date(2020, 3, 31))


def test_parse_dtype_float64(tmp_path: Path) -> None:
    rs = parse_iima_rf(_write(tmp_path, _IIMA_CSV))
    assert rs.values.dtype == np.float64


def test_missing_rf_column_fails_loud(tmp_path: Path) -> None:
    bad = _write(tmp_path, "Date,SMB\n2020-01,0.3\n")
    with pytest.raises(ValueError, match="RF"):
        parse_iima_rf(bad)


def test_duplicate_month_fails_loud(tmp_path: Path) -> None:
    dup = _write(tmp_path, "Date,RF\n2020-01,0.5\n2020-01,0.6\n")
    with pytest.raises(ValueError, match="duplicate month"):
        parse_iima_rf(dup)


def _check_investment(x: Investment) -> None:
    """Typed gate: mypy rejects if x doesn't structurally satisfy Investment."""


def test_rf_investment_satisfies_protocol(tmp_path: Path) -> None:
    rf = rf_investment(_write(tmp_path, _IIMA_CSV))
    _check_investment(rf)
    assert isinstance(rf, SeriesInvestment)
    assert rf.benchmark is None
    assert rf.holdings == ()
    assert rf.returns(Frequency.MONTHLY).values.dtype == np.float64


# ---------------------------------------------------------------------------
# extend_rf — rf carry-forward (D2d)
# ---------------------------------------------------------------------------


def _monthly_rf(n: int, *, start_year: int = 2025, start_month: int = 1) -> ReturnSeries:
    dates = []
    year, month = start_year, start_month
    for _ in range(n):
        dates.append(date(year, month, calendar.monthrange(year, month)[1]))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return ReturnSeries(
        dates=tuple(dates),
        values=np.linspace(0.003, 0.003 + 0.0001 * (n - 1), n),
        frequency=Frequency.MONTHLY,
    )


def test_through_covered_month_returns_unchanged_and_none() -> None:
    rf = _monthly_rf(12, start_year=2025, start_month=1)  # last month 2025-12
    through = date(2025, 12, 15)  # same month as last published

    extended, extension = extend_rf(rf, through)

    assert extended is rf
    assert extension is None


def test_extends_three_months_at_carried_value() -> None:
    rf = _monthly_rf(12, start_year=2025, start_month=1)  # last month 2025-12
    last_value = float(rf.values[-1])
    through = date(2026, 3, 31)

    extended, extension = extend_rf(rf, through)

    assert len(extended) == 15
    new_dates = extended.dates[12:]
    assert new_dates == (date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31))
    assert all(v == pytest.approx(last_value) for v in extended.values[12:])
    # Original published values are untouched.
    assert np.array_equal(extended.values[:12], rf.values)
    assert extension == RfExtension(
        last_published=date(2025, 12, 31),
        extended_through=date(2026, 3, 31),
        n_extended=3,
        carried_monthly_value=last_value,
    )


def test_boundary_twelve_months_succeeds() -> None:
    rf = _monthly_rf(12, start_year=2025, start_month=1)  # last month 2025-12
    through = date(2026, 12, 31)  # exactly RF_EXTENSION_CAP_MONTHS out

    extended, extension = extend_rf(rf, through)

    assert extension is not None
    assert extension.n_extended == RF_EXTENSION_CAP_MONTHS == 12
    assert extended.dates[-1] == date(2026, 12, 31)


def test_beyond_cap_raises_naming_last_published_requested_and_cap() -> None:
    rf = _monthly_rf(12, start_year=2025, start_month=1)  # last month 2025-12
    through = date(2027, 1, 31)  # 13 months out

    with pytest.raises(ValueError, match="2025-12-31") as exc_info:
        extend_rf(rf, through)

    message = str(exc_info.value)
    assert "2027-01-31" in message
    assert "12" in message
