"""Domain errors. The API layer maps each class to one HTTP status (doc/api.md section 1.2)."""
from __future__ import annotations

from typing import Optional


class DomainError(Exception):
    code = "validation"

    def __init__(self, message: str, fields: Optional[dict[str, str]] = None):
        super().__init__(message)
        self.message = message
        self.fields = fields or None


class NoUser(DomainError):
    """The request has no user, or the user key is not known (401)."""
    code = "no_user"


class Forbidden(DomainError):
    """The permission rules do not allow the action (403)."""
    code = "forbidden"


class NotFound(DomainError):
    """The row does not exist (404)."""
    code = "not_found"


class Conflict(DomainError):
    """A key exists already, a row is in use, or the data changed (409)."""
    code = "conflict"


class Invalid(DomainError):
    """The input is not correct, or a CHECK or a trigger stopped the statement (422)."""
    code = "validation"
