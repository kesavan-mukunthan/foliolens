"""Investment protocol and concrete investment types.

Investment — read-only structural protocol: id, source, benchmark, holdings,
returns(freq). All members are @property except ``returns``, a method taking
the requested ``Frequency`` explicitly — no implicit "the" return series, since
an Investment may carry more than one (monthly analytical, daily NAV-basis).

Concrete (step 0): ShareClass (leaf, priced), Fund (prices via a representative ShareClass).
Stubs (step 1+): Stock, Portfolio, Benchmark, Cash.

Panels are computed **eagerly, once, at construction** — by the factories
(:func:`share_class_from_nav`, :func:`benchmark_from_index`) alone. No other
site calls ``monthly_returns``/``to_returns`` to build an Investment's panel;
``returns(freq)`` is a lookup, never a computation.

No I/O here. All concrete types are frozen dataclasses.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .holdings import Holding
from .sources import PricedSource, ReturnSource
from .value_objects import Cashflow, NavSeries, ReturnSeries
from ..returns.calendar import TradingCalendar
from ..returns.convert import to_returns
from ..returns.frequency import Frequency
from ..returns.monthly import monthly_returns


class Investment(Protocol):
    """Read-only structural protocol: everything investable exposes return panels."""

    @property
    def id(self) -> str: ...

    @property
    def source(self) -> ReturnSource: ...

    @property
    def benchmark(self) -> Investment | None: ...

    @property
    def holdings(self) -> tuple[Holding, ...]: ...

    def returns(self, freq: Frequency) -> ReturnSeries: ...


def _panel_lookup(
    investment_id: str, panels: Mapping[Frequency, ReturnSeries], freq: Frequency
) -> ReturnSeries:
    """Shared ``returns(freq)`` body: a dict lookup, never a computation.

    Raises ValueError (never KeyError, never None) naming the investment and
    the missing frequency — a caller asking for a panel that was never built
    fails loud, not with a generic mapping error.
    """
    try:
        return panels[freq]
    except KeyError:
        raise ValueError(
            f"{investment_id!r} has no {freq} panel"
        ) from None


@dataclass(frozen=True)
class ShareClass:
    """One AMFI scheme code — the true priced unit (isin, plan, option).

    Satisfies both Investment and ReturnSource protocols. ``panels`` carries
    every eagerly-computed ``ReturnSeries`` keyed by ``Frequency`` — built once
    by :func:`share_class_from_nav`, never recomputed by ``returns(freq)``.
    """

    id: str
    amfi_code: str
    isin: str
    plan: str    # "direct" | "regular"
    option: str  # "growth" | "idcw"
    source: PricedSource
    panels: Mapping[Frequency, ReturnSeries]
    calendar: TradingCalendar
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

    def returns(self, freq: Frequency) -> ReturnSeries:
        return _panel_lookup(self.id, self.panels, freq)


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

    def returns(self, freq: Frequency) -> ReturnSeries:
        return self.representative.returns(freq)


@dataclass(frozen=True)
class SeriesInvestment:
    """An Investment wrapping a materialised ``ReturnSeries`` directly.

    For return-space series that never pass through a NAV/level stage — the
    risk-free rate (IIM-A 91-day T-bill) is the canonical case. This is the one
    sanctioned non-NAV float entry into the model besides ``ValueIndex``: the
    series is already float64 at birth, so ``returns/convert.py`` does not apply.
    No source/holdings; ``source`` raises to make the absence explicit. Carries
    exactly one frequency's panel — the one ``returns_series`` was built at.
    """

    id: str
    returns_series: ReturnSeries

    def returns(self, freq: Frequency) -> ReturnSeries:
        return _panel_lookup(self.id, {self.returns_series.frequency: self.returns_series}, freq)

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

    Same shape as ShareClass: a PricedSource over the index NavSeries, plus
    eagerly-computed ``panels``. ``id`` carries the canonical index_code (e.g.
    ``NIFTY500TRI``). No holdings, no benchmark of its own by default.
    """

    id: str
    source: PricedSource
    panels: Mapping[Frequency, ReturnSeries]
    calendar: TradingCalendar
    benchmark: Investment | None = None
    holdings: tuple[Holding, ...] = ()

    @property
    def value_series(self) -> NavSeries:
        return self.source.nav

    @property
    def cashflows(self) -> tuple[Cashflow, ...]:
        return ()

    def returns(self, freq: Frequency) -> ReturnSeries:
        return _panel_lookup(self.id, self.panels, freq)


def _eager_panels(nav: NavSeries, cal: TradingCalendar) -> dict[Frequency, ReturnSeries]:
    """Build both panels off ``nav`` — the one computation site for either.

    MONTHLY via :func:`monthly_returns` (calendar-derived month-end resample);
    DAILY via :func:`to_returns` directly. ``to_returns`` raises ValueError on
    fewer than 2 NAV points, so an unbuildable panel fails here, at
    construction — never lazily, at first metric call.
    """
    return {
        Frequency.MONTHLY: monthly_returns(nav, cal),
        Frequency.DAILY: to_returns(nav, frequency=Frequency.DAILY),
    }


def share_class_from_nav(
    id: str,
    nav: NavSeries,
    cal: TradingCalendar,
    *,
    isin: str = "",
    plan: str = "",
    option: str = "",
    benchmark: Investment | None = None,
    holdings: tuple[Holding, ...] = (),
) -> ShareClass:
    """Construct a ``ShareClass`` with both panels eagerly computed off ``nav``.

    The only site that computes a ShareClass's panels — every caller
    constructs through here, never by hand-building ``panels=`` itself.
    """
    return ShareClass(
        id=id,
        amfi_code=nav.amfi_code,
        isin=isin,
        plan=plan,
        option=option,
        source=PricedSource(nav=nav),
        panels=_eager_panels(nav, cal),
        calendar=cal,
        benchmark=benchmark,
        holdings=holdings,
    )


def benchmark_from_index(levels: NavSeries, cal: TradingCalendar) -> Benchmark:
    """Construct a benchmark Investment from an index level NavSeries.

    ``levels.amfi_code`` carries the index_code and becomes the benchmark id.
    The only site that computes a Benchmark's panels.
    """
    return Benchmark(
        id=levels.amfi_code,
        source=PricedSource(nav=levels),
        panels=_eager_panels(levels, cal),
        calendar=cal,
    )


class Cash:
    """Stub: shared leaf over cash-rate index; makes parent weights sum to 1. INR-only."""

    id: str = "CASH"

    def __init__(self) -> None:
        raise NotImplementedError

    def returns(self, freq: Frequency) -> ReturnSeries:
        raise NotImplementedError
