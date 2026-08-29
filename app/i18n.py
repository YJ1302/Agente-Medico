"""Interface language toggle (Spanish default) with full-page English rendering.

The application UI is authored in Spanish. When a viewer switches to English,
``translate_html`` runs the fully rendered HTML through the ``ES_EN`` phrase
catalog (``app/i18n_es_en.py``): it translates the text between tags and a few
safe attributes, leaving ``<script>`` / ``<style>`` / ``<textarea>`` untouched.
Anything not in the catalog stays Spanish, so coverage grows over time with no
risk of breaking the page. No external service — fully offline.

``make_translator`` still backs the ``{{ t(...) }}`` helper used in templates.
"""

from __future__ import annotations

import re

from fastapi import Request

from app.i18n_es_en import ES_EN

SUPPORTED = {"es", "en"}
DEFAULT_LANG = "es"


def get_lang(request: Request) -> str:
    lang = request.session.get("lang", DEFAULT_LANG)
    return lang if lang in SUPPORTED else DEFAULT_LANG


def make_translator(lang: str):
    """Return a ``t(text)`` callable for the given language.

    Spanish (default) is the identity function; English maps known strings and
    falls back to the original Spanish when no entry exists.
    """
    if lang == "en":
        return lambda s: ES_EN.get(s, ES_EN.get(str(s).strip(), s))
    return lambda s: s


# ---------------------------------------------------------------------------
# Full-page translation
# ---------------------------------------------------------------------------

# Blocks whose text content must never be translated.
_PROTECT_RE = re.compile(
    r"<(script|style|textarea|pre|code)\b[^>]*>.*?</\1>", re.S | re.I
)
# A run of text between two tags (no nested tags, no braces from stray Jinja).
_TEXT_RE = re.compile(r">([^<>]+)<")
# Attributes safe to translate (user-visible, not identifiers or URLs).
_ATTR_RE = re.compile(r'\b(title|placeholder|aria-label|alt)="([^"<>]+)"')

# Trailing/leading chars we tolerate when matching a text run against the table
# (so "Estado" still matches inside "  Estado  " or "Estado:").
_TRIM = " \t\r\n "
_PUNCT_EDGES = "·:—–-|/"

# Longest-first phrase pass for catalog entries that appear *inside* a larger
# text run (e.g. a sentence assembled around a Jinja value, or a count suffix
# glued to a number). Multi-word phrases and parenthesised count suffixes only,
# so single words that double as data ("Sede", "Estado") are never touched
# mid-string. Word-boundary guards stop "Sin tutor" matching "Sin tutores".
_WORDCHAR = r"[0-9A-Za-zÁÉÍÓÚÑáéíóúñ]"
_PHRASES = sorted(
    (k for k in ES_EN if (" " in k or "(" in k) and len(k) >= 5),
    key=len,
    reverse=True,
)
_PHRASE_RE = (
    re.compile(
        rf"(?<!{_WORDCHAR})(?:"
        + "|".join(re.escape(p) for p in _PHRASES)
        + rf")(?!{_WORDCHAR})"
    )
    if _PHRASES
    else None
)


def _translate_run(text: str) -> str:
    """Translate one text run: exact-match first, then embedded phrases."""
    core = text.strip(_TRIM)
    if not core:
        return text
    # 1. exact catalog hit (optionally ignoring edge punctuation/space)
    hit = ES_EN.get(core)
    if hit is None:
        stripped = core.strip(_PUNCT_EDGES + _TRIM)
        alt = ES_EN.get(stripped)
        if alt is not None:
            hit = core.replace(stripped, alt, 1)
    if hit is not None:
        return text.replace(core, hit, 1)
    # 2. embedded known phrases
    if _PHRASE_RE is not None and _PHRASE_RE.search(core):
        new_core = _PHRASE_RE.sub(lambda m: ES_EN[m.group(0)], core)
        return text.replace(core, new_core, 1)
    return text


def translate_html(html: str) -> str:
    """Return ``html`` with visible Spanish UI text swapped to English."""
    # Protect non-translatable blocks behind placeholders.
    shelf: list[str] = []

    def _stash(m: re.Match) -> str:
        shelf.append(m.group(0))
        return f"\x00{len(shelf) - 1}\x00"

    guarded = _PROTECT_RE.sub(_stash, html)
    guarded = _TEXT_RE.sub(lambda m: ">" + _translate_run(m.group(1)) + "<", guarded)
    guarded = _ATTR_RE.sub(
        lambda m: f'{m.group(1)}="{ES_EN.get(m.group(2).strip(), m.group(2))}"',
        guarded,
    )
    # Restore protected blocks.
    return re.sub(r"\x00(\d+)\x00", lambda m: shelf[int(m.group(1))], guarded)
