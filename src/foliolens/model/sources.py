"""Return source strategies.

ReturnSource — protocol (structural interface): value_series + cashflows.
PricedSource — concrete, for entities with an observed price/NAV series.
HeldSource, BlendSource — stubs; implemented at step 1+/2+.

Risk-metric methods (sharpe, max_drawdown, volatility) are protocol surface only
until step 2; all concrete sources raise NotImplementedError for now.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from .value_objects import Cashflow, NavSeries


@runtime_checkable
class ReturnSource(Protocol):
    """Every return-producing entity exposes a price series and (optionally) cashflows."""

    @property
    def value_series(self) -> NavSeries: ...

    @property
    def cashflows(self) -> tuple[Cashflow, ...]: ...

    def sharpe(self) -> Decimal: ...

    def max_drawdown(self) -> Decimal: ...

    def volatility(self) -> Decimal: ...


@dataclass(frozen=True)
class PricedSource:
    """Return source for entities with their own observed NAV/price series (TWR)."""

    nav: NavSeries

    @property
    def value_series(self) -> NavSeries:
        return self.nav

    @property
    def cashflows(self) -> tuple[Cashflow, ...]:
        return ()

    def sharpe(self) -> Decimal:
        raise NotImplementedError

    def max_drawdown(self) -> Decimal:
        raise NotImplementedError

    def volatility(self) -> Decimal:
        raise NotImplementedError


class HeldSource:
    """Stub: MWR/XIRR on value_series + cashflows. Implemented at step 1+."""

    @property
    def value_series(self) -> NavSeries:
        raise NotImplementedError

    @property
    def cashflows(self) -> tuple[Cashflow, ...]:
        raise NotImplementedError

    def sharpe(self) -> Decimal:
        raise NotImplementedError

    def max_drawdown(self) -> Decimal:
        raise NotImplementedError

    def volatility(self) -> Decimal:
        raise NotImplementedError


class BlendSource:
    """Stub: blend(holdings, weights) with no own price series. Implemented at step 2+."""

    @property
    def value_series(self) -> NavSeries:
        raise NotImplementedError

    @property
    def cashflows(self) -> tuple[Cashflow, ...]:
        raise NotImplementedError

    def sharpe(self) -> Decimal:
        raise NotImplementedError

    def max_drawdown(self) -> Decimal:
        raise NotImplementedError

    def volatility(self) -> Decimal:
        raise NotImplementedError
