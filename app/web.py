"""Web helpers shared by routes: flash messages and pagination.

Kept separate from ``templating`` (which owns the Jinja env) so routes can
import lightweight helpers without pulling template globals.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from fastapi import Request

_FLASH_KEY = "_flashes"

# Allowed flash categories map to CSS chip/alert tones.
FLASH_SUCCESS = "success"
FLASH_ERROR = "danger"
FLASH_WARNING = "warning"
FLASH_INFO = "info"


def flash(request: Request, message: str, category: str = FLASH_INFO) -> None:
    """Queue a one-time flash message in the session."""
    flashes = request.session.get(_FLASH_KEY, [])
    flashes.append({"message": message, "category": category})
    request.session[_FLASH_KEY] = flashes


def pop_flashes(request: Request) -> list[dict]:
    """Return and clear queued flash messages (consumed on render)."""
    flashes = request.session.pop(_FLASH_KEY, [])
    return flashes


@dataclass
class Page:
    """Pagination result wrapper for list views."""

    items: list
    total: int
    page: int
    per_page: int

    @property
    def pages(self) -> int:
        return max(1, ceil(self.total / self.per_page)) if self.per_page else 1

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def start_index(self) -> int:
        return 0 if self.total == 0 else (self.page - 1) * self.per_page + 1

    @property
    def end_index(self) -> int:
        return min(self.page * self.per_page, self.total)

    def window(self, radius: int = 2) -> list[int]:
        """Page numbers to show around the current page."""
        lo = max(1, self.page - radius)
        hi = min(self.pages, self.page + radius)
        return list(range(lo, hi + 1))


def paginate(items: list, page: int, per_page: int = 10) -> Page:
    """Slice an in-memory list into a :class:`Page`.

    For the prototype's data volume, in-memory pagination is adequate and keeps
    repositories simple; a future move to SQL LIMIT/OFFSET is contained to this
    helper and the repositories.
    """
    page = max(1, page)
    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    return Page(items=items[start:end], total=total, page=page, per_page=per_page)
