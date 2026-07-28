"""Validation sub-package: oracle wrapper, three-way reconciliation, and the
post-assembly identity checker (``identities.check_identities``)."""

from __future__ import annotations

from .identities import IdentityViolation, check_identities

__all__ = ["IdentityViolation", "check_identities"]
