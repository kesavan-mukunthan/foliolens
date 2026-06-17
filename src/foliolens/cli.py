"""End-to-end runner.

Entry point: python -m foliolens.cli
Runs the full pipeline on the reference fund set (fixtures/funds.csv) and
writes outputs/validation_report.xlsx. Deterministic: same frozen inputs
produce an identical report across runs.
"""
