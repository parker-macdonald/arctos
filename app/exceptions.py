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
    """Raised when a requested resource does not exist (HTTP 404)."""

    def __init__(
        self, message: str = "Not found", *, status_code: int = 404, public: bool = True
    ) -> None:
        """Initialise the error.

        Args:
            message: Human-readable description of the missing resource.
            status_code: HTTP status code to associate with this error.
            public: Whether ``message`` is safe to surface to end users.
        """
        super().__init__(message=message, status_code=status_code, public=public)


class UnauthorizedError(ArctosError):
    """Raised when the current user lacks permission for an action (HTTP 403)."""

    def __init__(
        self,
        message: str = "Not authorized",
        *,
        status_code: int = 403,
        public: bool = True,
    ) -> None:
        """Initialise the error.

        Args:
            message: Human-readable description of the permission failure.
            status_code: HTTP status code to associate with this error.
            public: Whether ``message`` is safe to surface to end users.
        """
        super().__init__(message=message, status_code=status_code, public=public)


class ValidationError(ArctosError):
    """Raised when request input fails domain validation (HTTP 400)."""

    def __init__(
        self,
        message: str = "Invalid input",
        *,
        status_code: int = 400,
        public: bool = True,
    ) -> None:
        """Initialise the error.

        Args:
            message: Human-readable description of the validation failure.
            status_code: HTTP status code to associate with this error.
            public: Whether ``message`` is safe to surface to end users.
        """
        super().__init__(message=message, status_code=status_code, public=public)


class RegistrationClosedError(ArctosError):
    """Raised when a registration action is attempted outside the open window."""

    def __init__(
        self,
        message: str = "Registration is not open",
        *,
        status_code: int = 400,
        public: bool = True,
    ) -> None:
        """Initialise the error.

        Args:
            message: Human-readable description of the closed-registration state.
            status_code: HTTP status code to associate with this error.
            public: Whether ``message`` is safe to surface to end users.
        """
        super().__init__(message=message, status_code=status_code, public=public)


class TournamentNotFoundError(NotFoundError):
    """Raised when a tournament URL slug cannot be resolved to a record."""

    def __init__(self, tournament_url: Optional[str] = None) -> None:
        """Initialise the error, optionally embedding the offending slug.

        Args:
            tournament_url: The URL slug that was not found, or ``None`` for a
                generic "tournament not found" message.
        """
        msg = (
            "Tournament not found"
            if not tournament_url
            else f"Tournament not found: {tournament_url}"
        )
        super().__init__(msg)
