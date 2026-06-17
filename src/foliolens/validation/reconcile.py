"""Three-way reconciliation: own implementation vs oracle vs published.

Tolerance constants (from CLAUDE.md, never adjusted at runtime):
  - own ↔ oracle:    relative ≤ 1e-6
  - own/oracle ↔ published: ≤ 10 bps absolute, after matching factsheet_as_of

Out-of-tolerance cases fail loud with fund / period / delta; never swallowed.
"""
