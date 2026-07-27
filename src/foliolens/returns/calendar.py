"""Trading-calendar derivation from cross-sectional NAV publication.

There is no independently published Indian mutual-fund trading calendar in
scope here — instead the calendar is *derived* from the NAV panel itself: a
date counts as a trading day when a majority of the funds active on that date
actually published a NAV. This is what lets month-end resolution reject a
non-trading last-calendar-day (e.g. a weekend) without an external holiday
list.
"""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import pyarrow as pa


@dataclass(frozen=True)
class TradingCalendar:
    """The set of dates a majority of the active universe published a NAV on."""

    days: frozenset[date]

    def last_trading_day(self, year: int, month: int) -> date | None:
        """The latest trading day in ``year``/``month``, or ``None`` if none exist."""
        month_days = [d for d in self.days if d.year == year and d.month == month]
        return max(month_days) if month_days else None


def derive_calendar(panel: pa.Table, amfi_codes: Sequence[str]) -> TradingCalendar:
    """Derive the trading calendar from a (amfi_code, date, ...) NAV panel.

    A scheme is *active* on date ``d`` iff ``min <= d <= max`` of its own NAV
    dates (schemes absent from ``panel`` are never active, so they never
    inflate the denominator). ``d`` is a trading day iff the number of schemes
    that actually published a NAV that day ("publishers") is at least
    ``ceil(0.5 * active)`` and at least 1 — a majority-publish rule, so a
    single stale/holdout fund publishing alone on a market holiday does not
    manufacture a trading day.
    """
    wanted = set(amfi_codes)
    dates_by_code: dict[str, list[date]] = defaultdict(list)
    for code, d in zip(
        panel.column("amfi_code").to_pylist(), panel.column("date").to_pylist()
    ):
        if code in wanted:
            dates_by_code[code].append(d)

    active_ranges = [(min(ds), max(ds)) for ds in dates_by_code.values()]

    publishers_by_date: dict[date, int] = defaultdict(int)
    for ds in dates_by_code.values():
        for d in ds:
            publishers_by_date[d] += 1

    trading_days: set[date] = set()
    for d, publishers in publishers_by_date.items():
        active = sum(1 for lo, hi in active_ranges if lo <= d <= hi)
        if publishers >= 1 and publishers >= math.ceil(0.5 * active):
            trading_days.add(d)

    return TradingCalendar(days=frozenset(trading_days))
