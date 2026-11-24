"""Typed domain and service errors for pmlib (Layer 0).

Layers 0-3 raise PmError subclasses instead of calling sys.exit; Layer 4 (cli.main)
maps them to exit codes, stderr/stdout streams, and JSON payloads.
"""
from __future__ import annotations


class PmError(Exception):
    """Base structured failure carrying exit code, optional JSON payload, and target stream."""

    code: int = 1
    payload: object = None
    stream: str = "stderr"

    def __init__(
        self,
        message: str = "",
        *,
        code: int | None = None,
        payload: object = None,
        stream: str | None = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.payload = payload
        if stream is not None:
            self.stream = stream


class Refused(PmError):
    """A requested operation is disallowed or invalid as asked."""

    code: int = 1


class NotFound(PmError, LookupError):
    """The requested task, project, session, or resource does not exist."""

    code: int = 1


class IdentityError(PmError):
    """An uncertain PM identity must never authorize a mutation."""

    code: int = 2


class StoreError(PmError):
    """Base error for ledger store failures."""

    code: int = 1


class VersionConflict(PmError, ValueError):
    """A write whose `if_version` no longer matches the file: someone changed it since it was read."""

    code: int = 4

    def __init__(
        self,
        message: str = "",
        current: str = "",
        *,
        code: int | None = None,
        payload: object = None,
        stream: str | None = None,
    ) -> None:
        PmError.__init__(self, message, code=code, payload=payload, stream=stream)
        self.current = current


class WaitOutcome(PmError):
    """Non-zero wait outcome (e.g., timeout=2, stopped unreported=3)."""

    code: int = 2
