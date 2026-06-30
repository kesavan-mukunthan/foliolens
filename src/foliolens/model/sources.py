"""Return source strategies.

ReturnSource — protocol (structural interface): value_series + cashflows.
PricedSource — concrete, for investments with an observed price/NAV series.
HeldSource, BlendSource — stubs; implemented at step 1+/2+.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .value_objects import Cashflow, NavSeries


@runtime_checkable
class ReturnSource(Protocol):
    """Every return-producing investment exposes a price series and (optionally) cashflows."""

    @property
    def value_series(self) -> NavSeries: ...

    @property
    def cashflows(self) -> tuple[Cashflow, ...]: ...


@dataclass(frozen=True)
class PricedSource:
    """Return source for investments with their own observed NAV/price series (TWR)."""

    nav: NavSeries

    @property
    def value_series(self) -> NavSeries:
        return self.nav

    @property
    def cashflows(self) -> tuple[Cashflow, ...]:
        return ()


class HeldSource:
    """Stub: MWR/XIRR on value_series + cashflows. Implemented at step 1+."""

    @property
    def value_series(self) -> NavSeries:
        raise NotImplementedError

    @property
    def cashflows(self) -> tuple[Cashflow, ...]:
        raise NotImplementedError


class BlendSource:
    """Stub: blend(holdings, weights) with no own price series. Implemented at step 2+."""

    @property
    def value_series(self) -> NavSeries:
        raise NotImplementedError

    @property
    def cashflows(self) -> tuple[Cashflow, ...]:
        raise NotImplementedError
