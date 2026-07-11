"""Test-only synthetic investments satisfying the Investment protocol without I/O."""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date

import numpy as np

from foliolens.model.holdings import Holding
from foliolens.model.investments import Investment
from foliolens.model.sources import ReturnSource
from foliolens.model.value_objects import ReturnSeries


@dataclass(frozen=True)
class FixedReturnsInvestment:
    """Frozen dataclass satisfying the Investment protocol; no NAV, no I/O."""

    id: str
    returns_series: ReturnSeries

    @property
    def returns(self) -> ReturnSeries:
        return self.returns_series

    @property
    def benchmark(self) -> Investment | None:
        return None

    @property
    def holdings(self) -> tuple[Holding, ...]:
        return ()

    @property
    def source(self) -> ReturnSource:
        raise NotImplementedError


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def rf_investment() -> FixedReturnsInvestment:
    """Risk-free fixture: 36 monthly period-end dates, constant 6% p.a. monthly return."""
    monthly_r = (1.06) ** (1 / 12) - 1
    dates = tuple(
        _month_end(2023 + (m - 1) // 12, (m - 1) % 12 + 1) for m in range(1, 37)
    )
    values = np.full(36, monthly_r, dtype=np.float64)
    return FixedReturnsInvestment(
        id="rf-fixture",
        returns_series=ReturnSeries(dates=dates, values=values),
    )
