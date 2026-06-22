"""Entity protocol and concrete entity types.

Entity — structural protocol: id, source, benchmark, holdings, returns.
Concrete (step 0): ShareClass (leaf, priced), Fund (prices via a representative ShareClass).
Stubs (step 1+): Stock, Portfolio, Benchmark, Cash.

No I/O here. All types are frozen dataclasses or plain stubs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from .holdings import Holding
from .sources import PricedSource, ReturnSource
from .value_objects import Cashflow, NavSeries, ReturnSeries


class Entity(Protocol):
    """Structural protocol: everything investable exposes a return series."""

    id: str
    source: ReturnSource
    benchmark: Entity | None
    holdings: tuple[Holding, ...]

    @property
    def returns(self) -> ReturnSeries: ...


@dataclass(frozen=True)
class ShareClass:
    """One AMFI scheme code — the true priced unit (isin, plan, option).

    Satisfies both Entity and ReturnSource protocols.
    Returns are computed by the engine (step 0.5); declared here, not implemented.
    """

    id: str
    amfi_code: str
    isin: str
    plan: str    # "direct" | "regular"
    option: str  # "growth" | "idcw"
    source: PricedSource
    benchmark: Entity | None = None
    holdings: tuple[Holding, ...] = field(default_factory=tuple)

    # --- ReturnSource protocol surface ---

    @property
    def value_series(self) -> NavSeries:
        return self.source.nav

    @property
    def cashflows(self) -> tuple[Cashflow, ...]:
        return ()

    def sharpe(self) -> Decimal:
        raise NotImplementedError

    def max_drawdown(self) -> Decimal:
        raise NotImplementedError

    def volatility(self) -> Decimal:
        raise NotImplementedError

    # --- Entity protocol surface ---

    @property
    def returns(self) -> ReturnSeries:
        raise NotImplementedError


@dataclass(frozen=True)
class Fund:
    """Strategy entity; groups share classes + benchmark.

    Prices via a representative ShareClass NAV — never via holdings.
    """

    id: str
    name: str
    representative: ShareClass
    benchmark: Entity | None = None
    holdings: tuple[Holding, ...] = field(default_factory=tuple)

    @property
    def source(self) -> PricedSource:
        return self.representative.source

    @property
    def value_series(self) -> NavSeries:
        return self.representative.value_series

    @property
    def cashflows(self) -> tuple[Cashflow, ...]:
        return ()

    def sharpe(self) -> Decimal:
        raise NotImplementedError

    def max_drawdown(self) -> Decimal:
        raise NotImplementedError

    def volatility(self) -> Decimal:
        raise NotImplementedError

    @property
    def returns(self) -> ReturnSeries:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Stubs — contract is stable; logic implemented in later steps
# ---------------------------------------------------------------------------


class Stock:
    """Stub: leaf entity priced via TRI. Implemented at step 3+."""

    def __init__(self) -> None:
        raise NotImplementedError


class Portfolio:
    """Stub: composite entity (BlendSource or HeldSource). Implemented at step 1+."""

    def __init__(self) -> None:
        raise NotImplementedError


class Benchmark:
    """Stub: priced via TRI; identical behaviour to Fund. Implemented at step 2+."""

    def __init__(self) -> None:
        raise NotImplementedError


class Cash:
    """Stub: shared leaf over cash-rate index; makes parent weights sum to 1. INR-only."""

    id: str = "CASH"

    def __init__(self) -> None:
        raise NotImplementedError
