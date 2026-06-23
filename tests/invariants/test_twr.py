"""Invariants: TWR == point-to-point on cashflow-free series; chaining consistency."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from foliolens.model.sources import PricedSource
from foliolens.model.value_objects import NavSeries
from foliolens.returns.engine import period_return


def _source(*rows: tuple[date, Decimal]) -> PricedSource:
    return PricedSource(nav=NavSeries(amfi_code="999999", data=rows))


def test_twr_equals_point_to_point() -> None:
    """On a cashflow-free NAV series, TWR == (end_nav/start_nav − 1) or CAGR thereof."""
    rows = (
        (date(2021, 1, 4), Decimal("100")),
        (date(2021, 6, 1), Decimal("110")),
        (date(2022, 1, 4), Decimal("130")),
        (date(2023, 1, 3), Decimal("150")),
    )
    source = _source(*rows)
    as_of = date(2023, 1, 3)

    result = period_return(source, "SI", as_of)

    start_nav = rows[0][1]
    end_nav = rows[-1][1]
    actual_days = (as_of - rows[0][0]).days
    years_d = Decimal(actual_days) / Decimal(365)
    expected = (end_nav / start_nav) ** (Decimal(1) / years_d) - Decimal(1)

    assert result.value == expected


def test_chaining_consistency() -> None:
    """Cumulative TWR from A to C == compound of TWR(A→B) and TWR(B→C)."""
    a = date(2021, 1, 4)
    b = date(2022, 1, 4)
    c = date(2023, 1, 3)
    nav_a = Decimal("100")
    nav_b = Decimal("120")
    nav_c = Decimal("144")

    source = _source((a, nav_a), (b, nav_b), (c, nav_c))

    r_ab = period_return(source, "SI", b)  # inception → b
    # Build a fresh source starting at b for the b→c leg
    source_bc = _source((b, nav_b), (c, nav_c))
    r_bc = period_return(source_bc, "SI", c)
    r_ac = period_return(source, "SI", c)

    # Compound the sub-period absolute returns: (1+r_ab)*(1+r_bc) - 1
    # This holds only when the sub-period lengths add to the full period.
    # For point-to-point CAGR chains, compare via the ratio:
    #   (nav_c / nav_a) == (nav_b / nav_a) * (nav_c / nav_b)
    ratio_direct = nav_c / nav_a
    ratio_chained = (nav_b / nav_a) * (nav_c / nav_b)
    assert ratio_direct == ratio_chained

    # The engine must produce the same end/start ratio regardless of path.
    actual_days_ac = (c - a).days
    years_ac = Decimal(actual_days_ac) / Decimal(365)
    expected_cagr_ac = ratio_direct ** (Decimal(1) / years_ac) - Decimal(1)
    assert r_ac.value == expected_cagr_ac

    # Sub-period returns compound correctly: (1+r_ab)*(1+r_bc) - 1 == r_ac as absolute
    compounded = (Decimal(1) + r_ab.value) * (Decimal(1) + r_bc.value) - Decimal(1)
    direct_absolute = nav_c / nav_a - Decimal(1)
    assert compounded == direct_absolute
