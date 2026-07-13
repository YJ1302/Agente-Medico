"""Reusable server-side validation helpers.

Validation is authoritative on the server (SECURITY_AND_PRIVACY_RULES.md §5).
Helpers return normalized values or raise ``ValidationError`` carrying a dict of
``field -> message`` so routes can re-render the form with inline errors and the
user's entered values preserved.
"""

from __future__ import annotations

import re
from datetime import date, datetime

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ValidationError(Exception):
    """Aggregates field-level validation errors for a form submission."""

    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


class FieldValidator:
    """Accumulates field errors, then raises once at the end if any exist."""

    def __init__(self) -> None:
        self.errors: dict[str, str] = {}

    def add(self, field: str, message: str) -> None:
        # Keep the first error per field (most relevant).
        self.errors.setdefault(field, message)

    def required(self, field: str, value: str | None, label: str) -> str:
        v = (value or "").strip()
        if not v:
            self.add(field, f"{label} es obligatorio.")
        return v

    def email(self, field: str, value: str | None, label: str = "El correo") -> str | None:
        v = (value or "").strip()
        if v and not _EMAIL_RE.match(v):
            self.add(field, f"{label} no tiene un formato válido.")
        return v or None

    def date(self, field: str, value: str | None, label: str) -> date | None:
        v = (value or "").strip()
        if not v:
            return None
        try:
            return datetime.strptime(v, "%Y-%m-%d").date()
        except ValueError:
            self.add(field, f"{label} no es una fecha válida (AAAA-MM-DD).")
            return None

    def choice(self, field: str, value: str | None, allowed: set[str], label: str) -> str | None:
        v = (value or "").strip()
        if v and v not in allowed:
            self.add(field, f"{label} no es una opción válida.")
        return v or None

    def int_field(self, field: str, value: str | None, label: str,
                  min_v: int | None = None, max_v: int | None = None) -> int | None:
        v = (value or "").strip()
        if v == "":
            return None
        try:
            n = int(v)
        except ValueError:
            self.add(field, f"{label} debe ser un número entero.")
            return None
        if min_v is not None and n < min_v:
            self.add(field, f"{label} no puede ser menor que {min_v}.")
        if max_v is not None and n > max_v:
            self.add(field, f"{label} no puede ser mayor que {max_v}.")
        return n

    def raise_if_errors(self) -> None:
        if self.errors:
            raise ValidationError(self.errors)
