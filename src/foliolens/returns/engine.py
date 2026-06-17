"""Return engine.

Implements TWR (time-weighted return) and the SEBI annualisation rule:
  - period < 1 year  → absolute return (end/start − 1), never annualised
  - period ≥ 1 year  → CAGR (end/start)^(1/years) − 1
Day-count: years = actual_days / 365 (AMFI convention, fixed).
Decimal throughout; float permitted only at the numeric-library boundary.
"""
