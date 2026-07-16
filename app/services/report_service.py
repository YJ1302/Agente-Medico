"""Reports service (Batch 2E).

Produces 14 management/academic reports as ``(headers, rows, meta)`` tables.
Role scope is applied **before** any data is gathered, so a Sede Coordinator
only ever sees their own sede, a Tutor only their assigned students, and a
Student only their own internship summary. Every report carries generation
metadata (date, filters, generating user). Patient data is never included.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.authorization import is_global_viewer
from app.models.base import (
    AssignmentStatus,
    DocumentStatus,
    EvaluationStatus,
    IncidentStatus,
)
from app.models.operations import DOCUMENT_TYPES, INCIDENT_TYPES
from app.models.user import (
    ROLE_ADMIN,
    ROLE_SEDE_COORDINATOR,
    ROLE_STUDENT,
    ROLE_TUTOR,
    ROLE_UNIVERSITY_COORDINATOR,
)
from app.repositories.repositories import RepositoryBundle
from app.services.auth_service import Identity


@dataclass
class ReportResult:
    key: str
    title: str
    headers: list[str]
    rows: list[list]
    description: str = ""


# Report registry: key -> (title, roles allowed).
REPORTS: dict[str, tuple[str, set[str]]] = {
    "students_by_sede": ("Internos por sede",
                         {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR}),
    "students_by_institution": ("Internos por tipo de institución",
                                {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR}),
    "rotations_status": ("Rotaciones activas / planificadas / completadas",
                         {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR}),
    "rotations_ending_soon": ("Rotaciones por finalizar",
                              {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR}),
    "missing_tutor": ("Rotaciones sin tutor asignado",
                      {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR}),
    "activity_progress_student": ("Avance de actividades por interno",
                                  {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR,
                                   ROLE_SEDE_COORDINATOR, ROLE_TUTOR}),
    "activity_progress_sede": ("Avance de actividades por sede",
                               {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR}),
    "pending_verifications": ("Verificaciones de tutor pendientes",
                              {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR,
                               ROLE_SEDE_COORDINATOR, ROLE_TUTOR}),
    "evaluations_status": ("Evaluaciones pendientes / enviadas / aprobadas",
                           {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR}),
    "tutor_workload": ("Carga de trabajo de tutores",
                       {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR}),
    "open_incidents_severity": ("Incidencias abiertas por severidad",
                                {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR}),
    "documents_status_type": ("Documentos por estado / tipo",
                              {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR}),
    "internship_summary": ("Resumen de internado por interno",
                           {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR}),
}


class ReportService:
    def __init__(self, db: Session, identity: Identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)

    # -- scope helpers ----------------------------------------------------
    def _own_sede_ids(self) -> set[int]:
        return {c.sede_id for c in self.repos.sede_coordinators.active()
                if c.user_id == self.identity.user_id and c.sede_id}

    def _own_tutor_ids(self) -> set[int]:
        return {t.id for t in self.repos.tutors.active() if t.user_id == self.identity.user_id}

    def _tutor_student_ids(self) -> set[int]:
        ids = self._own_tutor_ids()
        if not ids:
            return set()
        return {a.student_id for a in self.repos.assignments.search(tutor_ids=ids)}

    def scoped_students(self):
        role = self.identity.role_code
        if is_global_viewer(self.identity):
            return self.repos.students.search()
        if role == ROLE_SEDE_COORDINATOR:
            return self.repos.students.search(sede_ids=self._own_sede_ids() or {-1})
        if role == ROLE_TUTOR:
            ids = self._tutor_student_ids()
            return [s for s in self.repos.students.search() if s.id in ids]
        if role == ROLE_STUDENT:
            return [s for s in self.repos.students.search(active=None)
                    if s.user_id == self.identity.user_id]
        return []

    def scoped_sedes(self):
        if is_global_viewer(self.identity):
            return self.repos.sedes.active()
        if self.identity.role_code == ROLE_SEDE_COORDINATOR:
            ids = self._own_sede_ids()
            return [s for s in self.repos.sedes.active() if s.id in ids]
        return []

    def scoped_assignments(self):
        role = self.identity.role_code
        if is_global_viewer(self.identity):
            return self.repos.assignments.all_with_relations()
        if role == ROLE_SEDE_COORDINATOR:
            return self.repos.assignments.search(sede_ids=self._own_sede_ids() or {-1})
        if role == ROLE_TUTOR:
            return self.repos.assignments.search(tutor_ids=self._own_tutor_ids() or {-1})
        if role == ROLE_STUDENT:
            sids = {s.id for s in self.scoped_students()}
            return self.repos.assignments.search(student_ids=sids or {-1})
        return []

    # -- access -----------------------------------------------------------
    def available_reports(self) -> list[tuple[str, str]]:
        return [(k, v[0]) for k, v in REPORTS.items()
                if self.identity.role_code in v[1]]

    def can_access(self, key: str) -> bool:
        meta = REPORTS.get(key)
        return bool(meta) and self.identity.role_code in meta[1]

    # -- builders ---------------------------------------------------------
    def build(self, key: str) -> ReportResult:
        builder = getattr(self, f"_r_{key}")
        return builder()

    def _r_students_by_sede(self) -> ReportResult:
        students = self.scoped_students()
        by_sede: dict[int, list] = {}
        for s in students:
            by_sede.setdefault(s.sede_id, []).append(s)
        sede_map = {s.id: s for s in self.repos.sedes.active()}
        rows = []
        for sede_id, group in by_sede.items():
            sede = sede_map.get(sede_id)
            inst = sede.institution_type.code if sede and sede.institution_type else "—"
            rows.append([sede.name if sede else "Sin sede", inst, len(group)])
        rows.sort(key=lambda r: -r[2])
        return ReportResult("students_by_sede", REPORTS["students_by_sede"][0],
                            ["Sede", "Institución", "N° internos"], rows)

    def _r_students_by_institution(self) -> ReportResult:
        students = self.scoped_students()
        counts: dict[str, int] = {}
        for s in students:
            code = s.institution_type.code if s.institution_type else "—"
            counts[code] = counts.get(code, 0) + 1
        rows = [[k, v] for k, v in sorted(counts.items())]
        return ReportResult("students_by_institution", REPORTS["students_by_institution"][0],
                            ["Institución", "N° internos"], rows)

    def _r_rotations_status(self) -> ReportResult:
        assignments = self.scoped_assignments()
        by_type: dict[str, dict[str, int]] = {}
        for a in assignments:
            name = a.rotation_type.name if a.rotation_type else "—"
            d = by_type.setdefault(name, {"active": 0, "planned": 0, "completed": 0, "cancelled": 0})
            if a.status in d:
                d[a.status] += 1
        rows = [[name, d["active"], d["planned"], d["completed"]]
                for name, d in sorted(by_type.items())]
        return ReportResult("rotations_status", REPORTS["rotations_status"][0],
                            ["Rotación", "Activas", "Planificadas", "Completadas"], rows)

    def _r_rotations_ending_soon(self, days: int = 14) -> ReportResult:
        today = date.today()
        cutoff = today + timedelta(days=days)
        rows = []
        for a in self.scoped_assignments():
            if a.status == AssignmentStatus.ACTIVE.value and a.end_date and today <= a.end_date <= cutoff:
                rows.append([
                    a.student.full_name if a.student else "—",
                    a.rotation_type.name if a.rotation_type else "—",
                    a.sede.short_name or a.sede.name if a.sede else "—",
                    a.end_date.strftime("%d/%m/%Y"), (a.end_date - today).days,
                ])
        rows.sort(key=lambda r: r[4])
        return ReportResult("rotations_ending_soon",
                            f"{REPORTS['rotations_ending_soon'][0]} ({days} días)",
                            ["Interno", "Rotación", "Sede", "Fin", "Días restantes"], rows)

    def _r_missing_tutor(self) -> ReportResult:
        rows = []
        for a in self.scoped_assignments():
            if a.tutor_id is None and a.status in (AssignmentStatus.ACTIVE.value,
                                                   AssignmentStatus.PLANNED.value):
                rows.append([
                    a.student.full_name if a.student else "—",
                    a.rotation_type.name if a.rotation_type else "—",
                    a.sede.short_name or a.sede.name if a.sede else "—",
                    a.period.name if a.period else "—",
                ])
        return ReportResult("missing_tutor", REPORTS["missing_tutor"][0],
                            ["Interno", "Rotación", "Sede", "Periodo"], rows)

    def _r_activity_progress_student(self) -> ReportResult:
        rows = []
        for s in self.scoped_students():
            entries = self.repos.student_activities.for_student(s.id)
            verified = sum(1 for e in entries if e.verification_status == "verified")
            pending = sum(1 for e in entries if e.verification_status == "pending")
            rows.append([s.full_name, s.sede.short_name or s.sede.name if s.sede else "—",
                         len(entries), verified, pending])
        rows.sort(key=lambda r: -r[2])
        return ReportResult("activity_progress_student", REPORTS["activity_progress_student"][0],
                            ["Interno", "Sede", "Registradas", "Verificadas", "Pendientes"], rows)

    def _r_activity_progress_sede(self) -> ReportResult:
        sedes = self.scoped_sedes()
        rows = []
        for sede in sedes:
            students = [s for s in self.scoped_students() if s.sede_id == sede.id]
            total = verified = pending = 0
            for s in students:
                entries = self.repos.student_activities.for_student(s.id)
                total += len(entries)
                verified += sum(1 for e in entries if e.verification_status == "verified")
                pending += sum(1 for e in entries if e.verification_status == "pending")
            rows.append([sede.name, total, verified, pending])
        rows.sort(key=lambda r: -r[1])
        return ReportResult("activity_progress_sede", REPORTS["activity_progress_sede"][0],
                            ["Sede", "Registradas", "Verificadas", "Pendientes"], rows)

    def _r_pending_verifications(self) -> ReportResult:
        rows = []
        student_ids = {s.id for s in self.scoped_students()}
        for e in self.repos.student_activities.all_pending():
            if e.student_id not in student_ids:
                continue
            tutor = e.assignment.tutor if e.assignment else None
            rows.append([
                e.student.full_name if e.student else "—",
                e.definition.name if e.definition else "—",
                tutor.user.full_name if tutor and tutor.user else "—",
                e.submitted_at.strftime("%d/%m/%Y") if e.submitted_at else "—",
            ])
        return ReportResult("pending_verifications", REPORTS["pending_verifications"][0],
                            ["Interno", "Actividad", "Tutor", "Enviada"], rows)

    def _r_evaluations_status(self) -> ReportResult:
        assignments = {a.id for a in self.scoped_assignments()}
        rows = []
        for ev in self.repos.evaluations.search():
            if ev.assignment_id not in assignments and not is_global_viewer(self.identity):
                continue
            rows.append([
                ev.student.full_name if ev.student else "—",
                ev.assignment.rotation_type.name if ev.assignment and ev.assignment.rotation_type else "—",
                ev.status,
                f"{ev.final_score:.2f}" if ev.final_score is not None else "—",
            ])
        return ReportResult("evaluations_status", REPORTS["evaluations_status"][0],
                            ["Interno", "Rotación", "Estado", "Nota final"], rows)

    def _r_tutor_workload(self) -> ReportResult:
        rows = []
        sede_ids = self._own_sede_ids() if self.identity.role_code == ROLE_SEDE_COORDINATOR else None
        for t in self.repos.tutors.active():
            if sede_ids is not None and t.sede_id not in sede_ids:
                continue
            rows.append([
                t.user.full_name if t.user else "—",
                t.sede.short_name or t.sede.name if t.sede else "—",
                self.repos.tutors.workload_count(t.id),
            ])
        rows.sort(key=lambda r: -r[2])
        return ReportResult("tutor_workload", REPORTS["tutor_workload"][0],
                            ["Tutor", "Sede", "Asignaciones activas/planificadas"], rows)

    def _r_open_incidents_severity(self) -> ReportResult:
        sede_ids = None
        if self.identity.role_code == ROLE_SEDE_COORDINATOR:
            sede_ids = self._own_sede_ids() or {-1}
        terminal = {IncidentStatus.CLOSED.value, IncidentStatus.DISMISSED.value}
        counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        for inc in self.repos.incidents.all_active():
            if inc.status in terminal:
                continue
            if sede_ids is not None and inc.sede_id not in sede_ids:
                continue
            if inc.severity in counts:
                counts[inc.severity] += 1
        labels = {"low": "Baja", "medium": "Media", "high": "Alta", "critical": "Crítica"}
        rows = [[labels[k], v] for k, v in counts.items()]
        return ReportResult("open_incidents_severity", REPORTS["open_incidents_severity"][0],
                            ["Severidad", "N° abiertas"], rows)

    def _r_documents_status_type(self) -> ReportResult:
        sede_ids = None
        if self.identity.role_code == ROLE_SEDE_COORDINATOR:
            sede_ids = self._own_sede_ids() or {-1}
        rows = []
        for d in self.repos.documents.all_active():
            if sede_ids is not None and d.sede_id not in sede_ids:
                continue
            if d.visibility == "confidential" and not is_global_viewer(self.identity):
                continue
            rows.append([d.code, DOCUMENT_TYPES.get(d.doc_type, d.doc_type), d.status, d.priority])
        return ReportResult("documents_status_type", REPORTS["documents_status_type"][0],
                            ["Código", "Tipo", "Estado", "Prioridad"], rows)

    def _r_internship_summary(self) -> ReportResult:
        rows = []
        for s in self.scoped_students():
            assignments = self.repos.assignments.search(student_id=s.id)
            entries = self.repos.student_activities.for_student(s.id)
            verified = sum(1 for e in entries if e.verification_status == "verified")
            evals = self.repos.evaluations.search(student_id=s.id)
            approved_evals = sum(1 for e in evals if e.status == EvaluationStatus.APPROVED.value)
            docs = self.repos.documents.search(student_id=s.id)
            approved_docs = sum(1 for d in docs if d.status == DocumentStatus.APPROVED.value)
            incs = self.repos.incidents.search(student_id=s.id)
            open_incs = sum(1 for i in incs if i.status not in
                            (IncidentStatus.CLOSED.value, IncidentStatus.DISMISSED.value))
            rows.append([s.full_name, s.sede.short_name or s.sede.name if s.sede else "—",
                         len(assignments), verified, approved_evals, approved_docs, open_incs])
        rows.sort(key=lambda r: r[0])
        return ReportResult("internship_summary", REPORTS["internship_summary"][0],
                            ["Interno", "Sede", "Rotaciones", "Act. verificadas",
                             "Eval. aprobadas", "Doc. aprobados", "Incid. abiertas"], rows)

    # -- student internship summary ---------------------------------------
    def can_view_student_summary(self, student) -> bool:
        role = self.identity.role_code
        if student is None:
            return False
        if is_global_viewer(self.identity):
            return True
        if role == ROLE_SEDE_COORDINATOR:
            return student.sede_id in self._own_sede_ids()
        if role == ROLE_TUTOR:
            return student.id in self._tutor_student_ids()
        if role == ROLE_STUDENT:
            return student.user_id == self.identity.user_id
        return False

    def build_student_summary(self, student_id: int) -> dict:
        """Consolidated internship record for a single student (scope-respecting).

        A Student sees only their own approved/final information: incidents are
        limited to non-confidential ones and internal notes are never included.
        """
        student = self.repos.students.get_full(student_id)
        if not self.can_view_student_summary(student):
            return {}
        is_student_self = self.identity.role_code == ROLE_STUDENT

        assignments = sorted(self.repos.assignments.search(student_id=student.id),
                             key=lambda a: (a.start_date or date.min))
        entries = self.repos.student_activities.for_student(student.id)
        verified = sum(1 for e in entries if e.verification_status == "verified")
        pending = sum(1 for e in entries if e.verification_status == "pending")
        evals = self.repos.evaluations.search(student_id=student.id)
        if is_student_self:
            evals = [e for e in evals if e.status == EvaluationStatus.APPROVED.value]
        docs = [d for d in self.repos.documents.search(student_id=student.id)
                if d.status == DocumentStatus.APPROVED.value]
        # Incidents: student self sees only non-confidential; others by scope.
        incidents = self.repos.incidents.search(student_id=student.id)
        if is_student_self:
            incidents = [i for i in incidents if i.visibility != "confidential"]
        # Tutors involved.
        tutors = []
        seen = set()
        for a in assignments:
            if a.tutor and a.tutor.id not in seen:
                seen.add(a.tutor.id)
                tutors.append(a.tutor)
        # Alerts referencing this student (non-confidential summary only).
        alerts = [al for al in self.repos.alerts.open_alerts()
                  if al.related_entity_type == "student" and al.related_entity_id == student.id]
        completed = sum(1 for a in assignments if a.status == AssignmentStatus.COMPLETED.value)
        completion = {
            "total": len(assignments), "completed": completed,
            "active": sum(1 for a in assignments if a.status == AssignmentStatus.ACTIVE.value),
            "planned": sum(1 for a in assignments if a.status == AssignmentStatus.PLANNED.value),
        }
        return {
            "student": student, "assignments": assignments, "tutors": tutors,
            "activity": {"total": len(entries), "verified": verified, "pending": pending},
            "evaluations": evals, "documents": docs, "incidents": incidents,
            "alerts": alerts, "completion": completion,
            "is_student_self": is_student_self,
            "incident_types": INCIDENT_TYPES, "document_types": DOCUMENT_TYPES,
        }

    def student_summary_tables(self, data: dict) -> list[tuple[str, list[str], list[list]]]:
        """Flatten the summary into (section, headers, rows) tuples for exports."""
        s = data["student"]
        tables = []
        tables.append(("Perfil", ["Campo", "Valor"], [
            ["Interno", s.full_name], ["Código", s.student_code],
            ["Institución", s.institution_type.name if s.institution_type else "—"],
            ["Sede", s.sede.name if s.sede else "—"], ["Ciclo", s.cycle or "—"],
        ]))
        tables.append(("Rotaciones", ["Rotación", "Sede", "Inicio", "Fin", "Estado"],
                       [[a.rotation_type.name if a.rotation_type else "—",
                         a.sede.short_name or a.sede.name if a.sede else "—",
                         a.start_date.strftime("%d/%m/%Y") if a.start_date else "—",
                         a.end_date.strftime("%d/%m/%Y") if a.end_date else "—", a.status]
                        for a in data["assignments"]]))
        tables.append(("Evaluaciones", ["Rotación", "Estado", "Nota final"],
                       [[e.assignment.rotation_type.name if e.assignment and e.assignment.rotation_type else "—",
                         e.status, f"{e.final_score:.2f}" if e.final_score is not None else "—"]
                        for e in data["evaluations"]]))
        tables.append(("Documentos aprobados", ["Código", "Tipo", "Título"],
                       [[d.code, data["document_types"].get(d.doc_type, d.doc_type), d.title]
                        for d in data["documents"]]))
        tables.append(("Incidencias", ["Código", "Tipo", "Severidad", "Estado"],
                       [[i.code, data["incident_types"].get(i.incident_type, i.incident_type),
                         i.severity, i.status] for i in data["incidents"]]))
        return tables

    # -- generation metadata ----------------------------------------------
    def meta(self, extra: dict | None = None) -> dict[str, str]:
        m = {
            "Generado": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "Usuario": self.identity.email,
            "Rol": self.identity.role_code,
            "Alcance": "Global" if is_global_viewer(self.identity) else "Restringido a su ámbito",
        }
        if extra:
            m.update(extra)
        return m
