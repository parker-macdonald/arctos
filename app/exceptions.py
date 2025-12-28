"""
Domain exceptions for Arctos.

These are intentionally lightweight and Flask-agnostic so they can be used in:
- services
- serializers
- route handlers
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ArctosError(Exception):
    """Base exception for domain-level errors."""

    message: str
    status_code: int = 400
    public: bool = True  # whether it's safe to show message to end users

    def __str__(self) -> str:  # pragma: no cover (tiny)
        return self.message


class NotFoundError(ArctosError):
    def __init__(
        self, message: str = "Not found", *, status_code: int = 404, public: bool = True
    ):
        super().__init__(message=message, status_code=status_code, public=public)


class UnauthorizedError(ArctosError):
    def __init__(
        self,
        message: str = "Not authorized",
        *,
        status_code: int = 403,
        public: bool = True,
    ):
        super().__init__(message=message, status_code=status_code, public=public)


class ValidationError(ArctosError):
    def __init__(
        self,
        message: str = "Invalid input",
        *,
        status_code: int = 400,
        public: bool = True,
    ):
        super().__init__(message=message, status_code=status_code, public=public)


class RegistrationClosedError(ArctosError):
    def __init__(
        self,
        message: str = "Registration is not open",
        *,
        status_code: int = 400,
        public: bool = True,
    ):
        super().__init__(message=message, status_code=status_code, public=public)


class TournamentNotFoundError(NotFoundError):
    def __init__(self, tournament_url: Optional[str] = None):
        msg = (
            "Tournament not found"
            if not tournament_url
            else f"Tournament not found: {tournament_url}"
        )
        super().__init__(msg)
