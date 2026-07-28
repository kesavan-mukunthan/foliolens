"""Benchmark calendar derivation — the yardstick's own trading calendar.

A fund-industry convention (many AMCs publish a NAV dated 31 March, the
fiscal year-end, even on a day the exchange has no session) can make the
equity cohort's derived ``TradingCalendar`` (majority-publish rule over fund
NAVs) treat 31 March as a trading day no benchmark index ever actually traded
on. Building the benchmark's monthly panel under that cohort calendar then
silently drops March from the panel — the index has no level dated on the
day the calendar insists is March's last trading day — and, by
``monthly_returns``'s adjacent-month rule, cascades to drop April's return
too (paired against February, a two-month gap). This was found in production
against fund 118955/120046/120843/148404's residual B1 identity violations:
the real NIFTY500TRI yardstick is missing 2024/2025/2026 March+April from its
monthly panel under the shared cohort calendar.

(a) mechanism, reproduced on a synthetic fixture: a benchmark built under the
    cohort calendar drops March every year; the same benchmark, built under a
    calendar derived from its own published dates
    (``returns.calendar.calendar_from_dates``), keeps every March and emits a
    complete 12-month panel per full calendar year (only the still-
    accumulating trailing month is absent, per ``month_end``'s own
    completeness rule).
(b) ``report.flexipage.runner._build_benchmark`` — the runner's actual
    benchmark factory — must resolve the benchmark's calendar from the
    index's own dates, never take the shared cohort calendar.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from foliolens.data_access import DataAccess
from foliolens.model.investments import benchmark_from_index
from foliolens.model.value_objects import NavSeries, ReturnSeries
from foliolens.report.flexipage.runner import _build_benchmark
from foliolens.returns.calendar import calendar_from_dates, derive_calendar
from foliolens.returns.frequency import Frequency

#: Years the synthetic fixture spans; the fiscal-year-end quirk is injected
#: into every one of them, mirroring the production finding (March+April
#: absent in 2024, 2025, *and* 2026).
_FISCAL_QUIRK_YEARS = (2024, 2025, 2026)

_START = date(2024, 1, 1)
#: A still-accumulating trailing month (no July NAV yet) — mirrors the
#: existing convention in tests/invariants/test_month_end.py.
_END = date(2026, 6, 19)

_COHORT_CODES = ("SYNF1", "SYNF2", "SYNF3")
_INDEX_CODE = "SYN500TRI"


def _daily_dates(start: date, end: date, *, skip: frozenset[date] = frozenset()) -> list[date]:
    out: list[date] = []
    d = start
    while d <= end:
        if d not in skip:
            out.append(d)
        d += timedelta(days=1)
    return out


def _fund_cohort_panel() -> pa.Table:
    """Three synthetic funds publishing a NAV every calendar day, including
    31 March every year — the AMC fiscal-year-end book-closing convention
    (~7,000-8,000 funds industry-wide carry a 31 March NAV in the real
    parquet, verified against the production dataset) — so
    ``derive_calendar``'s majority-publish rule picks up 31 March as a
    cohort trading day.
    """
    amfi_codes: list[str] = []
    dates: list[date] = []
    for code in _COHORT_CODES:
        for d in _daily_dates(_START, _END):
            amfi_codes.append(code)
            dates.append(d)
    return pa.table({"amfi_code": amfi_codes, "date": dates})


def _index_level_series() -> NavSeries:
    """A synthetic benchmark index level series with no session on 31 March
    of any year — the real NIFTY500TRI's own actual behaviour (verified
    against the production dataset: its last trading day in March is the
    28th/28th/30th in 2024/2025/2026, never the 31st).
    """
    skip = frozenset(date(y, 3, 31) for y in _FISCAL_QUIRK_YEARS)
    dates = _daily_dates(_START, _END, skip=skip)
    data = tuple((d, Decimal("100") + Decimal(i)) for i, d in enumerate(dates))
    return NavSeries(amfi_code=_INDEX_CODE, data=data)


def _year_months(rs: ReturnSeries) -> dict[int, set[int]]:
    out: dict[int, set[int]] = {}
    for d in rs.dates:
        out.setdefault(d.year, set()).add(d.month)
    return out


# ---------------------------------------------------------------------------
# (a) Mechanism: cohort calendar vs. the benchmark's own-dates calendar
# ---------------------------------------------------------------------------


def test_benchmark_under_cohort_calendar_drops_march() -> None:
    """RED evidence: built under the cohort's calendar — which the fiscal-
    year-end quirk makes believe 31 March is a trading day every year — the
    benchmark's monthly panel is missing March. The index has no level dated
    on the day the cohort calendar insists is March's last trading day, so
    ``month_end`` never emits that month.
    """
    cohort_cal = derive_calendar(_fund_cohort_panel(), list(_COHORT_CODES))
    levels = _index_level_series()

    benchmark = benchmark_from_index(levels, cohort_cal)
    months = _year_months(benchmark.returns(Frequency.MONTHLY))

    assert 3 not in months[2024]
    assert 3 not in months[2025]


def test_benchmark_under_own_dates_calendar_keeps_every_march() -> None:
    """The fix target: derived from the index's own published dates, its
    calendar agrees with itself on March's last trading day (the 28th, not
    the 31st) — every March survives, and each full calendar year emits a
    complete 12-month panel; only 2024's January (no December 2023 in this
    fixture to diff the first return against — an ordinary first-month
    edge case, not a rejection) and the still-accumulating trailing month
    (2026-06, no July level yet) are absent.
    """
    levels = _index_level_series()
    own_cal = calendar_from_dates(d for d, _ in levels.data)

    benchmark = benchmark_from_index(levels, own_cal)
    months = _year_months(benchmark.returns(Frequency.MONTHLY))

    assert months[2024] == set(range(2, 13))  # no Jan: no prior month-end in this fixture
    assert months[2025] == set(range(1, 13))
    assert months[2026] == {1, 2, 3, 4, 5}


# ---------------------------------------------------------------------------
# (b) The runner's actual factory must self-derive, never take the cohort's
# ---------------------------------------------------------------------------


def _write_index_parquet(tmp_path: Path) -> DataAccess:
    levels = _index_level_series()
    table = pa.table(
        {
            "index_code": [_INDEX_CODE] * len(levels.data),
            "date": [d for d, _ in levels.data],
            "level": [str(v) for _, v in levels.data],
        }
    )
    pq.write_table(table, tmp_path / "index_nav.parquet")
    return DataAccess(tmp_path)


def test_build_benchmark_resolves_its_own_calendar_not_the_cohort(tmp_path: Path) -> None:
    """``_build_benchmark`` must derive the yardstick's calendar from its own
    dates — never take the shared cohort calendar and pass it straight
    through, which (per the mechanism above) silently drops March every year.
    """
    cohort_cal = derive_calendar(_fund_cohort_panel(), list(_COHORT_CODES))
    data_access = _write_index_parquet(tmp_path)

    benchmark = _build_benchmark(data_access, _INDEX_CODE, cohort_cal)
    months = _year_months(benchmark.returns(Frequency.MONTHLY))

    assert 3 in months[2024]
    assert 3 in months[2025]
