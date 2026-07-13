"""Lightweight interface-language toggle (Spanish default, English chrome).

The application UI is authored in Spanish (per UI/UX requirements). This module
adds a per-session language preference and a small translation table for the
persistent *chrome* — navigation labels, section titles and top-bar controls —
so the "Traducir" button visibly switches the shell without any external
service (fully offline). Page bodies remain Spanish; full body translation is a
future enhancement (documented in DECISIONS_LOG).
"""

from __future__ import annotations

from fastapi import Request

SUPPORTED = {"es", "en"}
DEFAULT_LANG = "es"

# Chrome translations: Spanish source string -> English.
_CHROME_EN = {
    # Sidebar section titles
    "GENERAL": "GENERAL",
    "GESTIÓN DEL INTERNADO": "INTERNSHIP MANAGEMENT",
    "GESTIÓN INSTITUCIONAL": "INSTITUTIONAL MANAGEMENT",
    "AUTOMATIZACIÓN INTELIGENTE": "INTELLIGENT AUTOMATION",
    "ADMINISTRACIÓN": "ADMINISTRATION",
    # Sidebar items
    "Dashboard": "Dashboard",
    "Internos": "Interns",
    "Sedes": "Sites",
    "Coordinadores de Sede": "Site Coordinators",
    "Tutores": "Tutors",
    "Rotaciones": "Rotations",
    "Catálogo de Actividades": "Activity Catalog",
    "Mis Actividades": "My Activities",
    "Bandeja de Verificación": "Verification Inbox",
    "Monitoreo de Actividades": "Activity Monitoring",
    "Evaluaciones": "Evaluations",
    "Documentos": "Documents",
    "Incidencias": "Incidents",
    "Reportes": "Reports",
    "Centro de Agentes": "Agent Center",
    "Alertas": "Alerts",
    "Ejecuciones de Agentes": "Agent Executions",
    "Usuarios y Roles": "Users & Roles",
    "Periodos Académicos": "Academic Periods",
    "Configuración": "Settings",
    "Auditoría": "Audit Log",
    # Top bar / user menu
    "Alertas recientes": "Recent alerts",
    "Ver todas": "View all",
    "Mi perfil": "My profile",
    "Cerrar sesión": "Sign out",
    "Notificaciones": "Notifications",
    "Idioma": "Language",
    "Traducir": "Translate",
}


def get_lang(request: Request) -> str:
    lang = request.session.get("lang", DEFAULT_LANG)
    return lang if lang in SUPPORTED else DEFAULT_LANG


def make_translator(lang: str):
    """Return a ``t(text)`` callable for the given language.

    For Spanish (default) it is the identity function; for English it maps known
    chrome strings, falling back to the original Spanish when no entry exists.
    """
    if lang == "en":
        return lambda s: _CHROME_EN.get(s, s)
    return lambda s: s
