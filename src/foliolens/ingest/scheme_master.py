"""Scheme master — universe-scale fund metadata derived from backfill shards.

Each raw shard (``raw/{amfi_code}.json.gz``) retains the full mftool response,
including ``scheme_name``, ``fund_house`` and ``scheme_category``. This module
turns one shard into one ``SchemeMasterRecord`` — no refetch, no network. The
derivation runs inside ``consolidate()`` in the same pass that lands NAV.

Four fields are parsed by convention:
- ``sebi_category``: the raw AMFI ``scheme_category`` string normalised to a slug
  (e.g. ``Equity Scheme - Flexi Cap Fund`` → ``flexi_cap``). Derived from the
  category field, never from the scheme name — a name may carry "Flexi IDCW"
  (an IDCW frequency) while the fund is a Credit Risk scheme.
- ``plan`` (``direct`` | ``regular`` | NULL) and ``option`` (``growth`` | ``idcw``
  | NULL): parsed from the scheme name. Ambiguous or absent → NULL, never guessed
  (CLAUDE.md executor guard; spec-benchmarks §1 accept).
- ``inception_date`` (date | NULL): read from the mftool scheme-details payload's
  ``scheme_start_date`` field — a ``{'date': 'DD-MM-YYYY', 'nav': ...}`` object
  (mftool 3.3 ``get_scheme_details`` shape); the ``date`` sub-field is the
  inception. A plain ``'DD-MM-YYYY'`` string is accepted too. A shard that does
  not carry the field → NULL: an unknown inception is never fabricated (and
  never back-filled from the NAV history itself — mfapi history depth is not
  true inception, the 103340 lesson). Manifest F-INC.

Storage is separate from the hand-curated ``benchmark_map.csv`` (distinct
provenance, update mechanics, audit trail); ``load_scheme_master`` joins them.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

_INCEPTION_DATE_FMT = "%d-%m-%Y"

_SCHEME_MASTER_SCHEMA = pa.schema(
    [
        pa.field("amfi_code", pa.string()),
        pa.field("scheme_name", pa.string()),
        pa.field("fund_house", pa.string()),
        pa.field("scheme_category", pa.string()),  # raw AMFI string
        pa.field("sebi_category", pa.string()),  # normalised slug, nullable
        pa.field("plan", pa.string()),  # direct|regular, nullable
        pa.field("option", pa.string()),  # growth|idcw, nullable
        pa.field("inception_date", pa.date32()),  # date, nullable (unknown)
    ]
)

# A trailing "Fund"/"Funds"/"Scheme"/"Schemes" word is category boilerplate, not
# part of the discriminating category name — dropped so the slug reads
# ``flexi_cap`` not ``flexi_cap_fund``.
_BOILERPLATE = re.compile(r"\b(funds?|schemes?)\b", re.IGNORECASE)
_NON_SLUG = re.compile(r"[^a-z0-9]+")

_DIRECT = re.compile(r"\bdirect\b", re.IGNORECASE)
_REGULAR = re.compile(r"\bregular\b", re.IGNORECASE)
_GROWTH = re.compile(r"\bgrowth\b", re.IGNORECASE)
# IDCW is the current SEBI term; "Dividend" is the legacy label; the long phrase
# is the fully-spelled variant AMCs use in place of the IDCW acronym.
_IDCW = re.compile(
    r"\bidcw\b|\bdividend\b|income distribution cum capital withdrawal",
    re.IGNORECASE,
)


def normalise_category(raw: str | None) -> str | None:
    """Normalise a raw AMFI ``scheme_category`` string to a SEBI-category slug.

    Keys off the leaf after the last ``" - "`` separator, drops the trailing
    Fund/Scheme boilerplate, and slugifies (``Equity Scheme - Flexi Cap Fund`` →
    ``flexi_cap``). Empty/blank input → ``None`` (unclassified, never guessed).
    """
    text = (raw or "").strip()
    if not text:
        return None
    leaf = text.rsplit(" - ", 1)[-1].strip()
    lowered = _BOILERPLATE.sub(" ", leaf.lower())
    slug = _NON_SLUG.sub("_", lowered).strip("_")
    return slug or None


def parse_plan(scheme_name: str | None) -> str | None:
    """Parse ``direct`` | ``regular`` from a scheme name; NULL if absent/ambiguous.

    A name carrying exactly one of the plan tokens resolves to it; neither token,
    or both, → ``None`` (not guessed).
    """
    name = scheme_name or ""
    has_direct = _DIRECT.search(name) is not None
    has_regular = _REGULAR.search(name) is not None
    if has_direct and not has_regular:
        return "direct"
    if has_regular and not has_direct:
        return "regular"
    return None


def parse_option(scheme_name: str | None) -> str | None:
    """Parse ``growth`` | ``idcw`` from a scheme name; NULL if absent/ambiguous.

    IDCW is recognised via ``IDCW``, the legacy ``Dividend`` label, or the fully
    spelled "income distribution cum capital withdrawal". Exactly one signal
    resolves; neither, or both, → ``None`` (not guessed).
    """
    name = scheme_name or ""
    has_growth = _GROWTH.search(name) is not None
    has_idcw = _IDCW.search(name) is not None
    if has_growth and not has_idcw:
        return "growth"
    if has_idcw and not has_growth:
        return "idcw"
    return None


def parse_inception_date(raw: dict[str, Any]) -> datetime.date | None:
    """Read the scheme's inception date from a raw mftool shard; NULL if absent.

    mftool's ``get_scheme_details`` payload carries ``scheme_start_date`` as a
    ``{'date': 'DD-MM-YYYY', 'nav': ...}`` object (mftool 3.3); the ``date``
    sub-field is the inception. A plain ``'DD-MM-YYYY'`` string is accepted too.

    Returns ``None`` — an explicit "unknown" — when the field is absent, empty,
    or unparseable: an inception is never fabricated, and never derived from the
    NAV history itself (mfapi history depth is not the true inception).
    """
    start = raw.get("scheme_start_date")
    if isinstance(start, dict):
        start = start.get("date")
    text = str(start or "").strip()
    if not text:
        return None
    try:
        return datetime.datetime.strptime(text, _INCEPTION_DATE_FMT).date()
    except ValueError:
        return None


@dataclass(frozen=True)
class SchemeMasterRecord:
    amfi_code: str
    scheme_name: str
    fund_house: str
    scheme_category: str
    sebi_category: str | None
    plan: str | None
    option: str | None
    # Nullable — some shards do not carry an inception; NULL is "unknown".
    # Defaulted so callers predating Manifest F-INC construct unchanged.
    inception_date: datetime.date | None = None


def scheme_record(amfi_code: str, raw: dict[str, Any]) -> SchemeMasterRecord:
    """Derive one ``SchemeMasterRecord`` from a raw mftool shard response.

    Pure function — no network. ``sebi_category`` comes from the AMFI
    ``scheme_category`` field; ``plan``/``option`` are name-parsed, NULL when the
    name does not name them.
    """
    scheme_name = str(raw.get("scheme_name") or "")
    scheme_category = str(raw.get("scheme_category") or "").strip()
    return SchemeMasterRecord(
        amfi_code=str(amfi_code),
        scheme_name=scheme_name,
        fund_house=str(raw.get("fund_house") or ""),
        scheme_category=scheme_category,
        sebi_category=normalise_category(scheme_category),
        plan=parse_plan(scheme_name),
        option=parse_option(scheme_name),
        inception_date=parse_inception_date(raw),
    )


def land_scheme_master(
    records: list[SchemeMasterRecord], data_dir: Path
) -> Path:
    """Write ``SchemeMasterRecord``s to ``data_dir/scheme_master.parquet``.

    One row per record, sorted by ``amfi_code``; nullable slug/plan/option/
    inception_date carry real NULLs (``inception_date`` as a parquet ``date32``).
    Overwrites any existing file. Returns the written path.
    """
    if not records:
        raise ValueError("no scheme_master records to land")

    ordered = sorted(records, key=lambda r: r.amfi_code)
    table = pa.table(
        {
            "amfi_code": pa.array([r.amfi_code for r in ordered], type=pa.string()),
            "scheme_name": pa.array(
                [r.scheme_name for r in ordered], type=pa.string()
            ),
            "fund_house": pa.array(
                [r.fund_house for r in ordered], type=pa.string()
            ),
            "scheme_category": pa.array(
                [r.scheme_category for r in ordered], type=pa.string()
            ),
            "sebi_category": pa.array(
                [r.sebi_category for r in ordered], type=pa.string()
            ),
            "plan": pa.array([r.plan for r in ordered], type=pa.string()),
            "option": pa.array([r.option for r in ordered], type=pa.string()),
            "inception_date": pa.array(
                [r.inception_date for r in ordered], type=pa.date32()
            ),
        },
        schema=_SCHEME_MASTER_SCHEMA,
    )

    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / "scheme_master.parquet"
    pq.write_table(table, out_path)  # type: ignore[no-untyped-call]
    return out_path
