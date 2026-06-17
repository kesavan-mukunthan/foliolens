"""mftool client — all mftool calls are isolated here.

Fetches full NAV history by amfi_code and normalises to
(amfi_code, date, nav) with nav as Decimal. Distinguishes holidays/weekends
from missing data; no forward-fill in the raw layer.
"""
