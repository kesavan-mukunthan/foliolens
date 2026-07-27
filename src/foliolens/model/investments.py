"""Investment protocol and concrete investment types.

Investment — read-only structural protocol: id, source, benchmark, holdings, returns.
All members are @property so that frozen-dataclass fields and computed properties
both satisfy it without a read-write attribute mismatch.

Concrete (step 0): ShareClass (leaf, priced), Fund (prices via a representative ShareClass).
Stubs (step 1+): Stock, Portfolio, Benchmark, Cash.

No I/O here. All concrete types are frozen dataclasses.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Protocol

from .holdings import Holding
from .sources import PricedSource, ReturnSource
from .value_objects import Cashflow, NavSeries, ReturnSeries
from ..returns.convert import to_returns
from ..returns.frequency import Frequency


class Investment(Protocol):
    """Read-only structural protocol: everything investable exposes a return series."""

    @property
    def id(self) -> str: ...

    @property
    def source(self) -> ReturnSource: ...

    @property
    def benchmark(self) -> Investment | None: ...

    @property
    def holdings(self) -> tuple[Holding, ...]: ...

    @property
    def returns(self) -> ReturnSeries: ...


@dataclass(frozen=True)
class ShareClass:
    """One AMFI scheme code — the true priced unit (isin, plan, option).

    Satisfies both Investment and ReturnSource protocols.
    Returns are computed by the engine (step 0.5); declared here, not implemented.
    """

    id: str
    amfi_code: str
    isin: str
    plan: str    # "direct" | "regular"
    option: str  # "growth" | "idcw"
    source: PricedSource
    benchmark: Investment | None = None
    holdings: tuple[Holding, ...] = ()

    # --- ReturnSource protocol surface ---

    @property
    def value_series(self) -> NavSeries:
        return self.source.nav

    @property
    def cashflows(self) -> tuple[Cashflow, ...]:
        return ()

    # --- Investment protocol surface ---

    @cached_property
    def returns(self) -> ReturnSeries:
        return to_returns(self.source.nav.month_end(), frequency=Frequency.MONTHLY)


@dataclass(frozen=True)
class Fund:
    """Strategy investment; groups share classes + benchmark.

    Prices via a representative ShareClass NAV — never via holdings.
    source is a computed property to match Investment's read-only @property protocol.
    """

    id: str
    name: str
    representative: ShareClass
    benchmark: Investment | None = None
    holdings: tuple[Holding, ...] = ()

    @property
    def source(self) -> PricedSource:
        return self.representative.source

    @property
    def value_series(self) -> NavSeries:
        return self.representative.value_series

    @property
    def cashflows(self) -> tuple[Cashflow, ...]:
        return ()

    @property
    def returns(self) -> ReturnSeries:
        return self.representative.returns


@dataclass(frozen=True)
class SeriesInvestment:
    """An Investment wrapping a materialised monthly ``ReturnSeries`` directly.

    For return-space series that never pass through a NAV/level stage — the
    risk-free rate (IIM-A 91-day T-bill) is the canonical case. This is the one
    sanctioned non-NAV float entry into the model besides ``ValueIndex``: the
    series is already float64 at birth, so ``returns/convert.py`` does not apply.
    No source/holdings; ``source`` raises to make the absence explicit.
    """

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
        raise NotImplementedError("SeriesInvestment has no ReturnSource; it is return-space")


# ---------------------------------------------------------------------------
# Stubs — contract is stable; logic implemented in later steps
# ---------------------------------------------------------------------------


class Stock:
    """Stub: leaf investment priced via TRI. Implemented at step 3+."""

    def __init__(self) -> None:
        raise NotImplementedError


class Portfolio:
    """Stub: composite investment (BlendSource or HeldSource). Implemented at step 1+."""

    def __init__(self) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class Benchmark:
    """A benchmark index priced via its TRI level series (never PRI).

    Same shape as ShareClass: a PricedSource over the index NavSeries, so
    ``.returns`` is ``to_returns(levels.month_end())`` unchanged. ``id`` carries
    the canonical index_code (e.g. ``NIFTY500TRI``). No holdings, no benchmark of
    its own by default.
    """

    id: str
    source: PricedSource
    benchmark: Investment | None = None
    holdings: tuple[Holding, ...] = ()

    @property
    def value_series(self) -> NavSeries:
        return self.source.nav

    @property
    def cashflows(self) -> tuple[Cashflow, ...]:
        return ()

    @cached_property
    def returns(self) -> ReturnSeries:
        return to_returns(self.source.nav.month_end(), frequency=Frequency.MONTHLY)


def benchmark_from_index(levels: NavSeries) -> Benchmark:
    """Construct a benchmark Investment from an index level NavSeries.

    ``levels.amfi_code`` carries the index_code and becomes the benchmark id.
    """
    return Benchmark(id=levels.amfi_code, source=PricedSource(nav=levels))


class Cash:
    """Stub: shared leaf over cash-rate index; makes parent weights sum to 1. INR-only."""

    id: str = "CASH"

    def __init__(self) -> None:
        raise NotImplementedError
