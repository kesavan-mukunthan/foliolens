"""Raw NAV landing layer.

Writes normalised NavRecords to data_dir as decimal128 parquet, partitioned
by amfi_code (Hive-style: data_dir/amfi_code=<code>/data.parquet).
Ingestion writes; analysis reads via data_access.
"""
from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .mftool_client import NavRecord

_NAV_SCHEMA = pa.schema(
    [
        pa.field("amfi_code", pa.string()),
        pa.field("date", pa.date32()),
        pa.field("nav", pa.decimal128(18, 6)),
    ]
)


def land(records: list[NavRecord], data_dir: Path) -> Path:
    """Write all NavRecords for one fund to data_dir/amfi_code=<code>/data.parquet.

    Overwrites any existing file for that code.
    Returns the path of the written file.
    """
    if not records:
        raise ValueError("no records to land")

    amfi_code = records[0].amfi_code
    out_dir = data_dir / f"amfi_code={amfi_code}"
    out_dir.mkdir(parents=True, exist_ok=True)

    table = pa.table(
        {
            "amfi_code": pa.array([r.amfi_code for r in records], type=pa.string()),
            "date": pa.array([r.date for r in records], type=pa.date32()),
            "nav": pa.array([r.nav for r in records], type=pa.decimal128(18, 6)),
        },
        schema=_NAV_SCHEMA,
    )

    out_path = out_dir / "data.parquet"
    pq.write_table(table, out_path)  # type: ignore[no-untyped-call]
    return out_path
