"""Value objects for the FolioLens domain model.

NavSeries, ReturnResult, Cashflow — figures of record, Decimal throughout.
ReturnSeries and ValueIndex — path of scale, float64 per-period data with a
Decimal base anchor only. Invariants are enforced on construction; callers
never re-check them.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import numpy as np


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


@dataclass(frozen=True, eq=False)
class ReturnSeries:
    """Periodic returns (float64, path of scale) indexed by period-end date.

    Per-period data is float64 — never Decimal. Only ``base`` (a level anchor,
    default 100) stays Decimal; a return series + base reconstructs a ValueIndex.
    ``values`` is coerced to a read-only float64 array on construction.
    """

    dates: tuple[date, ...]
    values: np.ndarray
    base: Decimal = Decimal("100")

    def __post_init__(self) -> None:
        values = np.asarray(self.values, dtype=np.float64)
        if values.dtype != np.float64:
            raise TypeError(f"values must be float64, got {values.dtype}")
        if len(self.dates) != len(values):
            raise ValueError(
                f"dates/values length mismatch: {len(self.dates)} != {len(values)}"
            )
        if any(a >= b for a, b in zip(self.dates, self.dates[1:])):
            raise ValueError("dates must be strictly ascending")
        values.flags.writeable = False
        object.__setattr__(self, "values", values)

    def __len__(self) -> int:
        return len(self.dates)


@dataclass(frozen=True, eq=False)
class ValueIndex:
    """Float-backed synthetic level series (base·Π(1+r)) — the dual of NavSeries.

    Explicitly NOT a NavSeries: no amfi_code, no month-end rule, never reconciled
    against stored NAV. It is a derived view on the path of scale; reconstruction
    round-trips return *ratios*, never NAV levels (levels rebase to the base).
    ``levels`` is coerced to a read-only float64 array on construction.
    """

    dates: tuple[date, ...]
    levels: np.ndarray

    def __post_init__(self) -> None:
        levels = np.asarray(self.levels, dtype=np.float64)
        if levels.dtype != np.float64:
            raise TypeError(f"levels must be float64, got {levels.dtype}")
        if len(self.dates) != len(levels):
            raise ValueError(
                f"dates/levels length mismatch: {len(self.dates)} != {len(levels)}"
            )
        if any(a >= b for a, b in zip(self.dates, self.dates[1:])):
            raise ValueError("dates must be strictly ascending")
        levels.flags.writeable = False
        object.__setattr__(self, "levels", levels)

    def __len__(self) -> int:
        return len(self.dates)


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
