"""One-time snapshot freeze script.

Reads fixtures/funds.csv, fetches each fund's full NAV history via the
mftool client, and writes frozen parquet to fixtures/nav_snapshots/.

Run once and commit the output — thereafter tests read frozen files and
never touch the network. Records the freeze date and verifies every
factsheet_as_of <= the fund's snapshot last date.
"""
