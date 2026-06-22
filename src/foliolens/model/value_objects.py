"""Value objects for the FolioLens domain model.

NavSeries, ReturnSeries, ReturnResult, Cashflow — all frozen, Decimal throughout.
Invariants are enforced on construction; callers never re-check them.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


def _build_nav_data(
    rows: Iterable[tuple[date, Decimal]],
) -> tuple[tuple[date, Decimal], ...]:
    seen: dict[date, Decimal] = {}
    for dt, nav in rows:
        if not isinstance(nav, Decimal):
            raise TypeError(f"nav must be Decimal, got {type(nav).__name__}")
        seen[dt] = nav  # last entry wins on duplicate date
    return tuple(sorted(seen.items()))


@dataclass(frozen=True)
class NavSeries:
    """Sorted, de-duplicated, Decimal NAV series for one AMFI share class."""

    amfi_code: str
    data: tuple[tuple[date, Decimal], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", _build_nav_data(self.data))

    def __len__(self) -> int:
        return len(self.data)

    def as_of(self, dt: date) -> Decimal | None:
        """Last available NAV on or before dt; None if no such entry exists."""
        result: Decimal | None = None
        for d, nav in self.data:  # sorted ascending
            if d <= dt:
                result = nav
            else:
                break
        return result

    def month_end(self) -> NavSeries:
        """Derived series: last available NAV on or before each calendar month-end.

        No look-ahead — the selected date is always within its calendar month.
        Incomplete leading/trailing months are included (not skipped here;
        the caller may filter by start/end date as needed).
        """
        if not self.data:
            return NavSeries(self.amfi_code, ())
        # data is sorted ascending; later entries in the same month overwrite earlier ones
        monthly: dict[tuple[int, int], tuple[date, Decimal]] = {}
        for dt, nav in self.data:
            monthly[(dt.year, dt.month)] = (dt, nav)
        return NavSeries(self.amfi_code, tuple(monthly.values()))

    def between(self, start: date, end: date) -> NavSeries:
        """Slice to [start, end] inclusive."""
        return NavSeries(
            self.amfi_code,
            tuple((d, nav) for d, nav in self.data if start <= d <= end),
        )


@dataclass(frozen=True)
class ReturnSeries:
    """Periodic returns indexed by period-end date, plus a base level (default 100)."""

    data: tuple[tuple[date, Decimal], ...]
    base: Decimal = Decimal("100")

    def __post_init__(self) -> None:
        for _, r in self.data:
            if not isinstance(r, Decimal):
                raise TypeError(f"return value must be Decimal, got {type(r).__name__}")


@dataclass(frozen=True)
class ReturnResult:
    """Scalar return with full provenance for reconciliation and reporting."""

    value: Decimal
    period: str          # "1Y" | "3Y" | "5Y" | "SI"
    start_date: date
    end_date: date
    start_nav: Decimal
    end_nav: Decimal
    method: str          # "absolute" | "CAGR"
    days: int


@dataclass(frozen=True)
class Cashflow:
    """Signed cashflow: investor-out = negative, investor-in = positive.

    Terminal value is the final inflow. Used only in HeldSource (step 1+).
    """

    date: date
    amount: Decimal
