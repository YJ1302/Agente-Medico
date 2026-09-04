"""Authoritative server-side conflict detection for rotation assignments.

Returns a list of structured ``Conflict`` results. Routes/templates never
contain conflict logic — they call this service and render its output in the
"Validación de asignación" panel. Blocking conflicts prevent a save unless an
authorized user (per ``can_override``) supplies a reason.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

from app.config import settings
from app.models.base import AssignmentStatus, InstitutionCode
from app.repositories.repositories import RepositoryBundle

# Conflict codes (stable identifiers).
STUDENT_OVERLAP = "student_overlap"
DUPLICATE_CORE_ROTATION = "duplicate_core_rotation"
TUTOR_SEDE_MISMATCH = "tutor_sede_mismatch"
TUTOR_INACTIVE = "tutor_inactive"
SEDE_INACTIVE = "sede_inactive"
STUDENT_INACTIVE = "student_inactive"
INSTITUTION_MISMATCH = "institution_mismatch"
COMMUNITY_NOT_ALLOWED = "community_not_allowed"
PERIOD_DATE_MISMATCH = "period_date_mismatch"
TUTOR_WORKLOAD_WARNING = "tutor_workload_warning"
UNUSUAL_DURATION = "unusual_duration"

# Codes that an Administrator may override with a mandatory reason.
OVERRIDABLE = {INSTITUTION_MISMATCH, COMMUNITY_NOT_ALLOWED, PERIOD_DATE_MISMATCH}


@dataclass
class Conflict:
    code: str
    severity: str  # 'warning' | 'critical'
    title: str
    message: str
    blocking: bool
    can_override: bool
    requires_reason: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RotationInput:
    """Normalized proposed assignment used by the conflict checks."""

    student_id: int | None
    rotation_type_id: int | None
    sede_id: int | None
    period_id: int | None
    tutor_id: int | None
    start_date: date | None
    end_date: date | None
    assignment_id: int | None = None  # exclude self when editing


class RotationConflictService:
    """Runs the deterministic conflict checks over the repository layer."""

    def __init__(self, repos: RepositoryBundle) -> None:
        self.repos = repos

    def check(self, data: RotationInput, *, student=None, sede=None, tutor=None,
              rot=None, period=None, siblings=None, include_warnings: bool = True) -> list[Conflict]:
        """Run the conflict checks.

        Callers with an already-loaded ``RotationAssignment`` (its relations
        are eager-loaded by the repository) can pass ``student``/``sede``/
        ``tutor``/``rot``/``period``/``siblings`` directly to skip the
        redundant per-field ``.get()`` + sibling-search queries below — see
        the list-view caller in rotation_routes.py, which otherwise turned
        "show all rotations" into N rows × ~7 queries each.
        """
        conflicts: list[Conflict] = []
        if student is None and data.student_id:
            student = self.repos.students.get(data.student_id)
        if sede is None and data.sede_id:
            sede = self.repos.sedes.get(data.sede_id)
        if tutor is None and data.tutor_id:
            tutor = self.repos.tutors.get(data.tutor_id)
        if rot is None and data.rotation_type_id:
            rot = self.repos.rotation_types.get(data.rotation_type_id)
        if period is None and data.period_id:
            period = self.repos.periods.get(data.period_id)

        # F. Student inactive.
        if student and (not student.is_active or student.is_deleted):
            conflicts.append(self._c(STUDENT_INACTIVE, "critical",
                "Interno inactivo", "El interno está inactivo o eliminado.", True))
        # E. Sede inactive.
        if sede and (not sede.is_active or sede.is_deleted):
            conflicts.append(self._c(SEDE_INACTIVE, "critical",
                "Sede inactiva", "La sede está inactiva o eliminada.", True))
        # D. Tutor inactive.
        if tutor and (not tutor.is_active or tutor.is_deleted):
            conflicts.append(self._c(TUTOR_INACTIVE, "critical",
                "Tutor inactivo", "El tutor está inactivo o eliminado.", True))
        # C. Tutor-sede mismatch.
        if tutor and sede and tutor.sede_id != sede.id:
            conflicts.append(self._c(TUTOR_SEDE_MISMATCH, "critical",
                "Tutor de otra sede",
                "El tutor no pertenece a la sede de la asignación.", True))

        # A/B share the student's other active/planned assignments — reuse
        # preloaded ``siblings`` when the caller has them (list view), else
        # fetch (single-row callers: create/update/preview/detail).
        sibling_rows = siblings if siblings is not None else (
            self._student_active_planned(student.id, data.assignment_id) if student else [])

        # A. Student overlap (planned/active) with proposed dates.
        if student and data.start_date and data.end_date:
            for a in sibling_rows:
                if a.start_date and a.end_date and _overlaps(
                    data.start_date, data.end_date, a.start_date, a.end_date):
                    conflicts.append(self._c(STUDENT_OVERLAP, "critical",
                        "Rotaciones superpuestas",
                        f"Se superpone con «{a.rotation_type.name}» "
                        f"({a.start_date:%d/%m/%Y}–{a.end_date:%d/%m/%Y}).", True))
                    break

        # B. Duplicate core rotation in same period.
        if student and rot and period and rot.is_core:
            for a in sibling_rows:
                if a.rotation_type_id == rot.id and a.period_id == period.id:
                    conflicts.append(self._c(DUPLICATE_CORE_ROTATION, "critical",
                        "Rotación core duplicada",
                        f"El interno ya tiene «{rot.name}» en {period.name}.", True))
                    break

        # G. Institution mismatch (sede vs student) — override-able by admin.
        if student and sede and student.institution_type_id and \
                sede.institution_type_id != student.institution_type_id:
            conflicts.append(self._c(INSTITUTION_MISMATCH, "critical",
                "Institución no coincide",
                "La institución de la sede no coincide con la del interno "
                "(MINSA/EsSalud).", True, can_override=True))

        # H. Community rotation rule — EsSalud may not receive it; admin override.
        if student and rot and not rot.is_core and "comunitar" in rot.name.lower():
            inst = student.institution_type
            if inst and inst.code == InstitutionCode.ESSALUD.value:
                conflicts.append(self._c(COMMUNITY_NOT_ALLOWED, "critical",
                    "Rotación comunitaria no permitida",
                    "Los internos de EsSalud no pueden recibir la rotación "
                    "comunitaria (MINSA).", True, can_override=True))

        # I. Period/date fit — the academic period is a calendar bucket, not a
        # hard boundary. A rotation may legitimately span two bimonthly periods
        # (e.g. Oct–Dec covers Set-Oct and Nov-Dic). Only flag it when the
        # rotation and the chosen period barely overlap, and block only when
        # they do not overlap at all (almost certainly the wrong period).
        if period and data.start_date and data.end_date and period.start_date and period.end_date:
            overlap = _overlap_days(data.start_date, data.end_date,
                                    period.start_date, period.end_date)
            if overlap <= 0:
                conflicts.append(self._c(PERIOD_DATE_MISMATCH, "critical",
                    "Fechas fuera del periodo",
                    f"Las fechas ({data.start_date:%d/%m/%Y}–{data.end_date:%d/%m/%Y}) "
                    f"no coinciden con «{period.name}» "
                    f"({period.start_date:%d/%m/%Y}–{period.end_date:%d/%m/%Y}). "
                    "¿Seleccionó el periodo correcto?", True, can_override=True))
            elif overlap < settings.rotation_period_min_overlap_days:
                conflicts.append(self._c(PERIOD_DATE_MISMATCH, "warning",
                    "Coincidencia mínima con el periodo",
                    f"La rotación solo coincide {overlap} día(s) con "
                    f"«{period.name}». Verifique que el periodo sea el correcto.",
                    False))

        # J. Tutor workload — warning only. Skippable: it never blocks, and
        # costs its own query (workload_count), not worth it for bulk/list use.
        if include_warnings and tutor:
            from app.services.staff_service import compute_workload
            wl = compute_workload(self.repos.tutors.workload_count(tutor.id))
            if wl.level in ("near", "above"):
                sev = "critical" if wl.level == "above" else "warning"
                conflicts.append(self._c(TUTOR_WORKLOAD_WARNING, sev,
                    "Carga del tutor elevada",
                    f"El tutor tiene {wl.count} asignación(es) "
                    f"(umbral {wl.threshold}). Confirme para continuar.", False))

        # K. Unusual duration vs the rotation type's expected weeks — warning only.
        if include_warnings and rot and data.start_date and data.end_date and rot.typical_weeks:
            days = (data.end_date - data.start_date).days
            expected = rot.typical_weeks * 7
            if expected and abs(days - expected) > expected * settings.rotation_duration_tolerance_ratio:
                conflicts.append(self._c(UNUSUAL_DURATION, "warning",
                    "Duración inusual",
                    f"La duración ({days} días) difiere de lo esperado para "
                    f"«{rot.name}» (~{expected} días).", False))

        return conflicts

    # -- helpers ----------------------------------------------------------
    def _student_active_planned(self, student_id: int, exclude_id: int | None):
        # Filter by student at the SQL level — the previous all_with_relations()
        # scan reloaded and eager-joined every assignment in the whole system
        # (with relations) on every single call, so cost grew with total
        # rows in the DB rather than with this one student's history. That
        # made bulk rotation imports (each row calls this twice) effectively
        # O(rows_in_batch × rows_in_db), which is what turned a ~250-row
        # import into a multi-second-per-row operation.
        rows = []
        for a in self.repos.assignments.search(student_id=student_id):
            if exclude_id and a.id == exclude_id:
                continue
            if a.status in (AssignmentStatus.ACTIVE.value, AssignmentStatus.PLANNED.value):
                rows.append(a)
        return rows

    @staticmethod
    def _c(code, severity, title, message, blocking, can_override=False) -> Conflict:
        return Conflict(code=code, severity=severity, title=title, message=message,
                        blocking=blocking, can_override=can_override,
                        requires_reason=can_override)


def _overlaps(a1: date, a2: date, b1: date, b2: date) -> bool:
    return a1 <= b2 and b1 <= a2


def _overlap_days(s: date, e: date, ps: date, pe: date) -> int:
    """Number of days the rotation [s,e] overlaps the period [ps,pe].

    Inclusive of both endpoints; 0 or negative means the two ranges are
    disjoint.
    """
    latest_start = max(s, ps)
    earliest_end = min(e, pe)
    return (earliest_end - latest_start).days + 1
