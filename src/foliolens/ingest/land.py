"""Raw NAV landing layer.

Writes normalised NavRecords to data_dir as a single decimal128 parquet file
(data_dir/nav.parquet) with amfi_code as an ordinary column, rows sorted by
(amfi_code, date). One file per landing run — avoids the small-file
anti-pattern at universe scale. Ingestion writes; analysis reads via data_access.
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

# Parquet row-group size tuned for columnar scans over the consolidated panel.
_ROW_GROUP_SIZE = 122880


def land(records: list[NavRecord], data_dir: Path) -> Path:
    """Write all NavRecords for a landing run to data_dir/nav.parquet.

    Records may span multiple amfi_codes; rows are sorted by (amfi_code, date).
    Overwrites any existing nav.parquet in data_dir.
    Returns the path of the written file.
    """
    if not records:
        raise ValueError("no records to land")

    ordered = sorted(records, key=lambda r: (r.amfi_code, r.date))

    table = pa.table(
        {
            "amfi_code": pa.array([r.amfi_code for r in ordered], type=pa.string()),
            "date": pa.array([r.date for r in ordered], type=pa.date32()),
            "nav": pa.array([r.nav for r in ordered], type=pa.decimal128(18, 6)),
        },
        schema=_NAV_SCHEMA,
    )

    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / "nav.parquet"
    pq.write_table(table, out_path, row_group_size=_ROW_GROUP_SIZE)  # type: ignore[no-untyped-call]
    return out_path
