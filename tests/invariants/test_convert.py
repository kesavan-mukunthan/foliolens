"""Invariant tests for the Decimal→float conversion seam (returns/convert.py).

Gates enforced here:
  - to_returns produces the expected float returns on a known NavSeries
  - Round-trip: to_index(to_returns(nav)) reproduces consecutive return ratios
    (never NAV levels — the index rebases to base 100)
  - ReturnSeries rejects non-float64 dtype, mismatched lengths, unsorted dates
  - ValueIndex has no amfi_code — it is explicitly not a NavSeries
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np
import pytest

from foliolens.model.value_objects import NavSeries, ReturnSeries, ValueIndex
from foliolens.returns.convert import simple_return, to_index, to_returns


def _nav(*rows: tuple[date, Decimal]) -> NavSeries:
    return NavSeries(amfi_code="999999", data=rows)


# ---------------------------------------------------------------------------
# to_returns — known values
# ---------------------------------------------------------------------------


def test_to_returns_known_values() -> None:
    nav = _nav(
        (date(2024, 1, 31), Decimal("100.00")),
        (date(2024, 2, 29), Decimal("110.00")),
        (date(2024, 3, 31), Decimal("99.00")),
    )
    rs = to_returns(nav)
    assert rs.dates == (date(2024, 2, 29), date(2024, 3, 31))
    assert rs.values.dtype == np.float64
    # 110/100 - 1 = 0.10 ; 99/110 - 1 = -0.10
    np.testing.assert_allclose(rs.values, [0.10, -0.10], rtol=1e-12)
    assert rs.base == Decimal("100")


def test_simple_return_rejects_nonpositive_start() -> None:
    with pytest.raises(ValueError):
        simple_return(Decimal("0"), Decimal("100"))
    with pytest.raises(ValueError):
        simple_return(Decimal("-1"), Decimal("100"))


def test_to_returns_requires_two_points() -> None:
    with pytest.raises(ValueError):
        to_returns(_nav((date(2024, 1, 31), Decimal("100.00"))))


def test_to_returns_rejects_nonpositive_nav() -> None:
    with pytest.raises(ValueError):
        to_returns(
            _nav(
                (date(2024, 1, 31), Decimal("0.00")),
                (date(2024, 2, 29), Decimal("110.00")),
            )
        )


def test_to_returns_rejects_nonpositive_final_nav() -> None:
    # Terminal NAV is only ever an end, so it must be guarded explicitly.
    with pytest.raises(ValueError):
        to_returns(
            _nav(
                (date(2024, 1, 31), Decimal("100.00")),
                (date(2024, 2, 29), Decimal("0.00")),
            )
        )


# ---------------------------------------------------------------------------
# Round-trip — ratios, never NAV levels
# ---------------------------------------------------------------------------


def test_roundtrip_reproduces_ratios_not_levels() -> None:
    nav = _nav(
        (date(2024, 1, 31), Decimal("123.45")),
        (date(2024, 2, 29), Decimal("130.00")),
        (date(2024, 3, 31), Decimal("128.20")),
        (date(2024, 4, 30), Decimal("140.75")),
    )
    idx = to_index(to_returns(nav))

    nav_values = [float(v) for _, v in nav.data]
    nav_ratios = [b / a for a, b in zip(nav_values, nav_values[1:])]
    # The index has one fewer point than NAV: the first NAV→NAV ratio is embedded
    # in level[0]/base, so consecutive index-level ratios reproduce nav_ratios[1:].
    level_ratios = [b / a for a, b in zip(idx.levels, idx.levels[1:])]
    np.testing.assert_allclose(level_ratios, nav_ratios[1:], rtol=1e-6)
    # And level[0]/base reproduces the first NAV ratio.
    assert idx.levels[0] / float(to_returns(nav).base) == pytest.approx(
        nav_ratios[0], rel=1e-6
    )

    # The index rebases to base 100 — levels are NOT the NAV levels.
    assert idx.levels[0] != pytest.approx(nav_values[1])
    # First level = 100 * (1 + first return) = 100 * (130/123.45)
    assert idx.levels[0] == pytest.approx(100.0 * (130.00 / 123.45), rel=1e-9)
    assert idx.dates == to_returns(nav).dates


# ---------------------------------------------------------------------------
# ReturnSeries — construction invariants
# ---------------------------------------------------------------------------


def test_return_series_coerces_int_to_float64() -> None:
    # Integer input is coerced (cast-at-birth) to float64, not stored as int.
    rs = ReturnSeries(
        dates=(date(2024, 1, 31), date(2024, 2, 29)),
        values=np.array([1, 2], dtype=np.int64),
    )
    assert rs.values.dtype == np.float64


def test_return_series_rejects_non_float64_dtype() -> None:
    # A non-numeric array cannot be cast to float64 — construction fails loud.
    with pytest.raises((TypeError, ValueError)):
        ReturnSeries(
            dates=(date(2024, 1, 31), date(2024, 2, 29)),
            values=np.array(["a", "b"]),
        )


def test_return_series_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError):
        ReturnSeries(
            dates=(date(2024, 1, 31),),
            values=np.array([0.1, 0.2], dtype=np.float64),
        )


def test_return_series_rejects_unsorted_dates() -> None:
    with pytest.raises(ValueError):
        ReturnSeries(
            dates=(date(2024, 2, 29), date(2024, 1, 31)),
            values=np.array([0.1, 0.2], dtype=np.float64),
        )


def test_return_series_values_are_read_only() -> None:
    rs = ReturnSeries(
        dates=(date(2024, 1, 31),),
        values=np.array([0.1], dtype=np.float64),
    )
    assert not rs.values.flags.writeable
    assert len(rs) == 1


# ---------------------------------------------------------------------------
# ValueIndex — explicitly not a NavSeries
# ---------------------------------------------------------------------------


def test_value_index_has_no_amfi_code() -> None:
    idx = ValueIndex(
        dates=(date(2024, 1, 31),),
        levels=np.array([100.0], dtype=np.float64),
    )
    assert not hasattr(idx, "amfi_code")


def test_value_index_rejects_unsorted_dates() -> None:
    with pytest.raises(ValueError):
        ValueIndex(
            dates=(date(2024, 2, 29), date(2024, 1, 31)),
            levels=np.array([100.0, 101.0], dtype=np.float64),
        )
