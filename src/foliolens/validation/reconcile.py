"""Three-way reconciliation: own implementation vs oracle vs published.

Tolerance constants (from CLAUDE.md, never adjusted at runtime):
  - own ↔ oracle:    relative ≤ 1e-6
  - own/oracle ↔ published: ≤ 10 bps absolute, after matching factsheet_as_of

Out-of-tolerance cases fail loud with fund / period / delta; never swallowed.

This module implements the **published** leg. It rides the production pipeline
end to end: raw fixture NAV → :func:`share_class_from_nav` (the same factory the
flexipage runner uses) → :func:`period_return` (the SEBI-annualising return
engine). It never re-derives a return by hand — the leg validates the pipeline,
so it must run *through* the pipeline. The engine is consumed here, never
adjusted: a mismatch is a finding to report, not licence to edit the engine.

Every published row resolves to exactly one :class:`Status`:
  - ``MATCH``        — computes and lands within tolerance.
  - ``MISMATCH``     — computes but exceeds tolerance. A finding.
  - ``UNCOMPUTABLE`` — the frozen fixture cannot support the row (scheme absent,
                       as_of beyond the freeze boundary, window predating fund
                       inception). Decided mechanically, before any engine call.
  - ``EXEMPT``       — computes, but is excused for a documented convention
                       reason recorded in ``fixtures/reconciliation_exemptions.csv``.
                       Exemptions are *data*, never inline in code; this module
                       reads them, it never invents them.
"""
from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path

from ..data_access import DataAccess
from ..model.investments import ShareClass, share_class_from_nav
from ..model.value_objects import NavSeries
from ..returns.engine import period_return

#: Own↔published tolerance: 10 bps absolute, on the annualised return. One
#: named constant, applied identically to every row — never loosened per row
#: or at runtime (CLAUDE.md "Validation": tolerances are fixed constants).
PUBLISHED_TOLERANCE_BPS = Decimal("10")

#: The frozen fixture carries NAV through mid-2026 but the reconciliation set
#: is anchored to the 2026-05-31 factsheet freeze. An as_of strictly beyond
#: this boundary cannot be reconciled against the freeze — it is uncomputable
#: (the fixture does not represent that as-of), never a mismatch.
FROZEN_AS_OF_MAX = date(2026, 5, 31)

#: Integer-year anchors for the SEBI-annualised windows (SI is inception-based).
_ANCHOR_YEARS: dict[str, int] = {"1Y": 1, "3Y": 3, "5Y": 5}


class Status(str, Enum):
    """The one status every published row resolves to."""

    MATCH = "match"
    MISMATCH = "mismatch"
    UNCOMPUTABLE = "uncomputable"
    EXEMPT = "exempt"


@dataclass(frozen=True)
class PublishedReturn:
    """One row of ``fixtures/published_returns.csv`` — an AMC factsheet figure.

    Columns are consumed exactly as they exist in the file; nothing is
    reshaped or invented. ``published_pct`` is the annualised return in
    percent (e.g. ``14.51`` for 14.51%), kept Decimal as a figure of record.
    """

    amfi_code: str
    period: str
    published_pct: Decimal
    as_of: date
    source_url: str


@dataclass(frozen=True)
class Exemption:
    """One row of ``fixtures/reconciliation_exemptions.csv``.

    A row that computes but is excused for a documented convention reason.
    The exemption list is reviewable data, adjudicated by a human row by row —
    this module never adds to it.
    """

    amfi_code: str
    window: str
    as_of: date
    reason: str


@dataclass(frozen=True)
class ReconRow:
    """The reconciliation outcome for one published row.

    ``computed_pct`` / ``diff_bps`` are ``None`` only for ``UNCOMPUTABLE``
    rows (no engine call was made). ``diff_bps`` is ``computed − published`` in
    basis points (positive ⇒ own figure runs higher than the factsheet).
    """

    amfi_code: str
    period: str
    as_of: date
    status: Status
    published_pct: Decimal
    computed_pct: Decimal | None
    diff_bps: Decimal | None
    detail: str


# ---------------------------------------------------------------------------
# Loaders — consume the CSV contract exactly as it exists on disk
# ---------------------------------------------------------------------------


def load_published_returns(path: Path | str) -> list[PublishedReturn]:
    """Parse ``published_returns.csv`` (amfi_code, period, published_return_pct,
    factsheet_as_of, source_url) into :class:`PublishedReturn` records."""
    rows: list[PublishedReturn] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append(
                PublishedReturn(
                    amfi_code=row["amfi_code"],
                    period=row["period"],
                    published_pct=Decimal(row["published_return_pct"]),
                    as_of=date.fromisoformat(row["factsheet_as_of"]),
                    source_url=row["source_url"],
                )
            )
    return rows


def load_exemptions(path: Path | str) -> list[Exemption]:
    """Parse ``reconciliation_exemptions.csv`` (amfi_code, window, as_of, reason).

    A missing file is treated as an empty exemption list — the file is created
    empty and populated only by human adjudication.
    """
    p = Path(path)
    if not p.exists():
        return []
    rows: list[Exemption] = []
    with p.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append(
                Exemption(
                    amfi_code=row["amfi_code"],
                    window=row["window"],
                    as_of=date.fromisoformat(row["as_of"]),
                    reason=row["reason"],
                )
            )
    return rows


# ---------------------------------------------------------------------------
# Uncomputability — mechanical, decided before any engine call
# ---------------------------------------------------------------------------


def _subtract_years(d: date, n: int) -> date:
    """Subtract n calendar years; clamps Feb 29 → Feb 28 in a non-leap target.

    Mirrors the engine's own anchor arithmetic — used here only to decide,
    mechanically, whether a window's start predates fund inception (an
    uncomputable row), never to re-derive the return itself.
    """
    try:
        return date(d.year - n, d.month, d.day)
    except ValueError:
        return date(d.year - n, 2, 28)


def _window_start(nav: NavSeries, period: str, as_of: date) -> date:
    """The start anchor a given window would use: inception for SI, else as_of
    minus the integer-year anchor."""
    if period == "SI":
        return nav.data[0][0]
    return _subtract_years(as_of, _ANCHOR_YEARS[period])


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def _uncomputable(pub: PublishedReturn, detail: str) -> ReconRow:
    return ReconRow(
        amfi_code=pub.amfi_code,
        period=pub.period,
        as_of=pub.as_of,
        status=Status.UNCOMPUTABLE,
        published_pct=pub.published_pct,
        computed_pct=None,
        diff_bps=None,
        detail=detail,
    )


def _reconcile_row(
    pub: PublishedReturn,
    nav: NavSeries | None,
    share_class: ShareClass | None,
    exempt_keys: frozenset[tuple[str, str, date]],
    tolerance_bps: Decimal,
    frozen_as_of_max: date,
) -> ReconRow:
    # --- Uncomputable checks (mechanical, no engine call) ---
    if nav is None or share_class is None:
        return _uncomputable(pub, "scheme absent from frozen parquet")
    if pub.as_of > frozen_as_of_max:
        return _uncomputable(
            pub, f"as_of {pub.as_of.isoformat()} beyond frozen boundary "
            f"{frozen_as_of_max.isoformat()}"
        )
    start_anchor = _window_start(nav, pub.period, pub.as_of)
    inception = nav.data[0][0]
    if start_anchor < inception:
        return _uncomputable(
            pub,
            f"{pub.period} window start {start_anchor.isoformat()} predates "
            f"inception {inception.isoformat()}",
        )

    # --- Computable: ride the engine on the factory-built share class ---
    result = period_return(share_class, pub.period, pub.as_of)
    computed_pct = result.value * Decimal(100)
    diff_bps = (computed_pct - pub.published_pct) * Decimal(100)

    if (pub.amfi_code, pub.period, pub.as_of) in exempt_keys:
        status = Status.EXEMPT
    elif abs(diff_bps) <= tolerance_bps:
        status = Status.MATCH
    else:
        status = Status.MISMATCH

    return ReconRow(
        amfi_code=pub.amfi_code,
        period=pub.period,
        as_of=pub.as_of,
        status=status,
        published_pct=pub.published_pct,
        computed_pct=computed_pct,
        diff_bps=diff_bps,
        detail="",
    )


def reconcile(
    data_access: DataAccess,
    published: Sequence[PublishedReturn],
    exemptions: Iterable[Exemption] = (),
    *,
    tolerance_bps: Decimal = PUBLISHED_TOLERANCE_BPS,
    frozen_as_of_max: date = FROZEN_AS_OF_MAX,
) -> list[ReconRow]:
    """Reconcile every published row against the engine, riding the pipeline.

    One :class:`~foliolens.returns.calendar.TradingCalendar` is derived across
    the schemes present in the fixture and shared to construct every
    ``ShareClass`` through :func:`share_class_from_nav` — the production factory
    path. The published leg reads daily NAV via :func:`period_return`, so the
    calendar (and the monthly panel it drives) never enters the computed
    figure; constructing through the factory is what keeps the leg *on* the
    pipeline rather than re-deriving returns beside it.

    Returns one :class:`ReconRow` per published row, order preserved. Never
    mutates the exemption set; mismatches are reported, not fixed.
    """
    exempt_keys = frozenset(
        (e.amfi_code, e.window, e.as_of) for e in exemptions
    )

    codes = sorted({p.amfi_code for p in published})
    navs: dict[str, NavSeries | None] = {}
    present: list[str] = []
    for code in codes:
        try:
            navs[code] = data_access.load_nav_series(code)
            present.append(code)
        except ValueError:
            navs[code] = None

    share_classes: dict[str, ShareClass] = {}
    if present:
        cal = data_access.derive_trading_calendar(present)
        for code in present:
            nav = navs[code]
            assert nav is not None  # present ⇒ loaded
            share_classes[code] = share_class_from_nav(
                code, nav, cal, plan="direct", option="growth"
            )

    return [
        _reconcile_row(
            pub,
            navs.get(pub.amfi_code),
            share_classes.get(pub.amfi_code),
            exempt_keys,
            tolerance_bps,
            frozen_as_of_max,
        )
        for pub in published
    ]


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------


def status_counts(rows: Iterable[ReconRow]) -> dict[Status, int]:
    """Count rows by :class:`Status`, every status present (zero-filled)."""
    counts: dict[Status, int] = {s: 0 for s in Status}
    for row in rows:
        counts[row.status] += 1
    return counts


def format_table(rows: Sequence[ReconRow]) -> str:
    """A deterministic fixed-width reconciliation table for the report/PR body.

    Columns: amfi_code, period, as_of, status, published, computed, diff_bps.
    """
    header = (
        f"{'amfi_code':<10}{'period':<8}{'as_of':<12}{'status':<14}"
        f"{'published':>11}{'computed':>11}{'diff_bps':>10}"
    )
    lines = [header, "-" * len(header)]
    for r in rows:
        computed = "—" if r.computed_pct is None else f"{r.computed_pct:.2f}"
        diff = "—" if r.diff_bps is None else f"{r.diff_bps:+.1f}"
        lines.append(
            f"{r.amfi_code:<10}{r.period:<8}{r.as_of.isoformat():<12}"
            f"{r.status.value:<14}{r.published_pct:>11.2f}{computed:>11}{diff:>10}"
        )
    counts = status_counts(rows)
    lines.append("-" * len(header))
    lines.append(
        "  ".join(f"{s.value}={counts[s]}" for s in Status)
        + f"  total={len(rows)}"
    )
    return "\n".join(lines)
