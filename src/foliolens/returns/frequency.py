"""Declared periodicity of a ``ReturnSeries`` — never inferred from dates.

``periods_per_year`` is a fixed convention per member, not derived from the
calendar: ``DAILY`` is pinned at 252 (the standard trading-day convention),
not ``len(trading_days)`` for any particular year.
"""
from __future__ import annotations

from enum import Enum


class Frequency(Enum):
    MONTHLY = "monthly"
    DAILY = "daily"

    @property
    def periods_per_year(self) -> int:
        return _PERIODS_PER_YEAR[self]


_PERIODS_PER_YEAR: dict[Frequency, int] = {
    Frequency.MONTHLY: 12,
    Frequency.DAILY: 252,
}
