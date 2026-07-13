"""Local, offline privacy validation for activity-log free text.

Detects obvious patient-identifying content in activity notes/evidence
references before they are saved or logged, per SECURITY_AND_PRIVACY_RULES.md
and Batch 2C §11. This is a **practical heuristic**, not a guarantee of
de-identification — it catches the common, obvious patterns (DNI-like numbers,
medical-record labels, emails, phone numbers, explicit "nombre del paciente"
phrases) and blocks saving when found. No external service or AI is used.
"""

from __future__ import annotations

import re

WARNING_MESSAGE = (
    "El sistema detectó contenido que podría identificar a un paciente. "
    "Elimine esa información antes de guardar."
)

FORM_NOTICE = (
    "No registre nombres, documentos, números de historia clínica ni otra "
    "información identificable del paciente."
)

# DNI-like: 8 consecutive digits (Peruvian DNI format), optionally with
# separators, not part of a longer numeric run (dates, phone already excluded).
_DNI_RE = re.compile(r"\b\d{8}\b")
_HISTORIA_CLINICA_RE = re.compile(
    r"\b(?:h\.?\s?c\.?|historia\s+cl[ií]nica|n[°º]?\s*historia)\b", re.IGNORECASE
)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_PHONE_RE = re.compile(r"\b(?:\+?51[\s.-]?)?9\d{2}[\s.-]?\d{3}[\s.-]?\d{3}\b")
_PATIENT_NAME_PHRASE_RE = re.compile(
    r"\b(?:nombre\s+del\s+paciente|paciente\s+llamad[oa]|se\s+llama)\b", re.IGNORECASE
)


def find_identifier_risk(*texts: str | None) -> bool:
    """Return True if any given text likely contains a patient identifier."""
    for text in texts:
        if not text:
            continue
        if _DNI_RE.search(text):
            return True
        if _HISTORIA_CLINICA_RE.search(text):
            return True
        if _EMAIL_RE.search(text):
            return True
        if _PHONE_RE.search(text):
            return True
        if _PATIENT_NAME_PHRASE_RE.search(text):
            return True
    return False
