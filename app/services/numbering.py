"""Server-side sequential numbering for documents and incidents.

Generates codes like ``DOC-2026-0001`` / ``INC-2026-0007``:

* Unique (UNIQUE constraint on the code column is the final backstop).
* Sequential per calendar year.
* Generated server-side only — never editable by normal users.
* Safe under concurrent creation: allocation performs an atomic in-transaction
  increment on the ``document_sequences`` row; a UNIQUE violation on the code
  triggers a bounded retry.
"""

from __future__ import annotations

from datetime import date

from app.repositories.repositories import RepositoryBundle

_PREFIX = {"document": "DOC", "incident": "INC", "import": "IMP"}


def allocate_code(repos: RepositoryBundle, kind: str, year: int | None = None) -> str:
    """Allocate the next ``PREFIX-YEAR-NNNN`` code for the given kind."""
    year = year or date.today().year
    prefix = _PREFIX[kind]
    number = repos.sequences.next_value(kind, year)
    return f"{prefix}-{year}-{number:04d}"
