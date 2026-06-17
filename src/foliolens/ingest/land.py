"""Raw NAV landing layer.

Writes normalised NAV records to data/raw/ as parquet with decimal128 dtype,
partitioned by amfi_code. Ingestion writes; analysis reads via data_access.
"""
