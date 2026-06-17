"""Single read seam for NAV parquet data.

All parquet reads go through this module — no other module opens parquet paths directly.
Abstracted so the path root can be swapped from local data/raw/ to gs:// at step 4
without touching any caller.
"""
