"""Exceptions raised by the Suez VHS client."""

from __future__ import annotations


class SuezError(Exception):
    """Base class for every error raised by the client."""


class SuezConnectionError(SuezError):
    """Raised on network failures, timeouts or unexpected HTTP statuses."""


class SuezAuthenticationError(SuezError):
    """Raised when the portal refuses the supplied credentials."""


class SuezParseError(SuezError):
    """Raised when an expected element cannot be located in a portal page."""
