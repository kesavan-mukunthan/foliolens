"""Excel validation report writer (xlsxwriter, write-only).

Produces outputs/validation_report.xlsx with three tabs:
  - Reconciliation: fund × period × own/oracle/published/delta/pass-fail
  - Per-fund NAV:   date, daily nav, month-end flag
  - Metadata:       amfi_code, isin, option, plan, source URLs, run info

Reporter computes nothing — it reads engine and reconcile outputs only.
NAV displayed to 4 dp; returns displayed as % to 2 dp; no scientific notation.
"""
