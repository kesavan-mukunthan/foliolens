"""Month-end NAV series derivation.

Month-end = last available NAV on or before calendar month-end.
No look-ahead: no selected date may exceed its calendar month-end.
Incomplete leading/trailing months are skipped, not fabricated.
Daily NAV is the stored base; this module derives the monthly layer on top.
"""
