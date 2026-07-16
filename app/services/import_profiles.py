"""Import profiles (Batch 2F).

Each profile declares its columns (with header aliases for auto-mapping), a
unique key for duplicate detection, and reuses the **existing** service
validation so business rules are never bypassed. Persistence writes only
``flush`` (no per-row commit) so the import service can wrap a whole batch in a
single transaction (all-or-nothing) — see DECISIONS_LOG D-029.

Profiles: students, sedes, coordinators, tutors, rotations. The grade-components
profile lives in ``grade_service.py`` and is registered lazily by ``get_profile``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.academic import RotationAssignment
from app.models.base import AssignmentStatus
from app.models.organization import SedeCoordinatorProfile, TutorProfile
from app.models.student import Student
from app.models.user import (
    ROLE_ADMIN,
    ROLE_SEDE_COORDINATOR,
    ROLE_TUTOR,
    ROLE_UNIVERSITY_COORDINATOR,
)
from app.repositories.repositories import RepositoryBundle
from app.services.auth_service import Identity
from app.services.rotation_conflict_service import RotationInput
from app.services.validators import ValidationError


# ---------------------------------------------------------------------------
# Cell-value helpers
# ---------------------------------------------------------------------------
def as_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


def _idstr(x) -> str:
    """Render a resolved id as a string for the form-style ``_validate`` methods
    (they re-parse ids with ``int_field``); '' when unresolved."""
    return str(x) if x else ""


def as_date(v) -> str:
    if v is None or (isinstance(v, str) and not v.strip()):
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s  # let the downstream validator flag an invalid date


@dataclass
class ImportField:
    target: str
    label: str
    required: bool = False
    aliases: tuple[str, ...] = ()
    kind: str = "str"  # str | date


@dataclass
class Message:
    level: str  # error | warning
    field: str
    message: str

    def as_dict(self) -> dict:
        return {"level": self.level, "field": self.field, "message": self.message}


@dataclass
class RowResult:
    normalized: dict
    messages: list[Message] = field(default_factory=list)
    existing_id: int | None = None

    @property
    def has_error(self) -> bool:
        return any(m.level == "error" for m in self.messages)

    @property
    def has_warning(self) -> bool:
        return any(m.level == "warning" for m in self.messages)


class ImportContext:
    """Shared state + service instances for a single import run (one session)."""

    def __init__(self, db: Session, identity: Identity,
                 sede_scope_ids: set[int] | None = None, batch=None) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)
        self.sede_scope_ids = sede_scope_ids
        self.batch = batch          # set during validate/confirm (grade profile uses it)
        self.seen: dict = {}        # per-run dedup tracking (e.g. repeated students)
        self._svc_cache: dict = {}

    # lazy service accessors (share this session; they flush, never commit here)
    def _svc(self, key, factory):
        if key not in self._svc_cache:
            self._svc_cache[key] = factory()
        return self._svc_cache[key]

    @property
    def students(self):
        from app.services.student_service import StudentService
        return self._svc("students", lambda: StudentService(self.db, self.identity))

    @property
    def sedes(self):
        from app.services.sede_service import SedeService
        return self._svc("sedes", lambda: SedeService(self.db, self.identity))

    @property
    def coordinators(self):
        from app.services.staff_service import CoordinatorService
        return self._svc("coordinators", lambda: CoordinatorService(self.db, self.identity))

    @property
    def tutors(self):
        from app.services.staff_service import TutorService
        return self._svc("tutors", lambda: TutorService(self.db, self.identity))

    @property
    def rotations(self):
        from app.services.rotation_service import RotationService
        return self._svc("rotations", lambda: RotationService(self.db, self.identity))

    # -- lookups ----------------------------------------------------------
    def institution_id(self, text: str) -> int | None:
        t = (text or "").strip().lower()
        if not t:
            return None
        for inst in self.repos.institution_types.list():
            if inst.code.lower() == t or inst.name.lower() == t or t in inst.name.lower():
                return inst.id
        if "essalud" in t or "es salud" in t:
            it = self.repos.institution_types.get_by_code("ESSALUD")
            return it.id if it else None
        if "minsa" in t:
            it = self.repos.institution_types.get_by_code("MINSA")
            return it.id if it else None
        return None

    def sede_id(self, text: str) -> int | None:
        t = (text or "").strip().lower()
        if not t:
            return None
        for s in self.repos.sedes.active():
            if s.name.lower() == t or (s.short_name or "").lower() == t:
                return s.id
        for s in self.repos.sedes.active():  # loose contains match
            if t in s.name.lower() or (s.short_name and t in s.short_name.lower()):
                return s.id
        return None

    def rotation_type_id(self, text: str) -> int | None:
        t = (text or "").strip().lower()
        if not t:
            return None
        for rt in self.repos.rotation_types.list():
            if rt.name.lower() == t or rt.code.lower() == t or t in rt.name.lower():
                return rt.id
        return None

    def period_id(self, text: str) -> int | None:
        t = (text or "").strip().lower()
        if not t:
            return None
        for p in self.repos.periods.ordered():
            if p.code.lower() == t or p.name.lower() == t or t in p.name.lower():
                return p.id
        return None

    def tutor_id_by_email(self, text: str) -> int | None:
        t = (text or "").strip().lower()
        if not t:
            return None
        for tp in self.repos.tutors.active():
            if tp.user and tp.user.email.lower() == t:
                return tp.id
        return None

    def student_by_code(self, code: str):
        return self.repos.students.get_by_code((code or "").strip()) if code else None


# ---------------------------------------------------------------------------
# Base profile
# ---------------------------------------------------------------------------
class ImportProfile:
    code: str = ""
    label: str = ""
    entity_type: str = ""
    allowed_roles: set[str] = set()
    fields: list[ImportField] = []
    unique_field: str = ""

    def display_fields(self, ctx: "ImportContext") -> list["ImportField"]:
        """Fields used to build the human-readable raw-row snapshot for preview/
        error reports. Defaults to the static field list; profiles whose fields
        are scheme/context-dependent (grade components) override this."""
        return self.fields

    def auto_map(self, headers: list[str]) -> dict[str, str]:
        """Best-effort {target_field: header} mapping from header aliases."""
        mapping: dict[str, str] = {}
        lowered = {h: h.strip().lower() for h in headers}
        for f in self.fields:
            for h, hl in lowered.items():
                if hl == f.target or hl == f.label.strip().lower() \
                        or any(a in hl for a in f.aliases):
                    mapping[f.target] = h
                    break
        return mapping

    def normalize(self, raw: dict, mapping: dict[str, str]) -> dict:
        out: dict = {}
        for f in self.fields:
            header = mapping.get(f.target)
            value = raw.get(header) if header else None
            out[f.target] = as_date(value) if f.kind == "date" else as_str(value)
        return out

    # Subclasses implement:
    def resolve(self, ctx: ImportContext, normalized: dict) -> dict:
        """Turn normalized text into a data dict the service validator expects."""
        raise NotImplementedError

    def find_existing(self, ctx: ImportContext, data: dict):
        raise NotImplementedError

    def validate(self, ctx: ImportContext, data: dict, existing) -> RowResult:
        raise NotImplementedError

    def apply(self, ctx: ImportContext, data: dict, existing, action: str):
        """Persist the row (flush only). Returns (entity_type, entity_id)."""
        raise NotImplementedError

    def in_scope(self, ctx: ImportContext, data: dict) -> bool:
        """Own-sede scope guard (coordinators). Default: allowed."""
        if ctx.sede_scope_ids is None:
            return True
        sede_id = data.get("sede_id")
        return sede_id in ctx.sede_scope_ids if sede_id else False


def _messages_from_validation_error(e: ValidationError) -> list[Message]:
    return [Message("error", k, v) for k, v in e.errors.items()]


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------
class StudentProfile(ImportProfile):
    code = "students"
    label = "Internos"
    entity_type = "student"
    allowed_roles = {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR}
    unique_field = "student_code"
    fields = [
        ImportField("student_code", "Código", True, ("codigo", "código", "code", "cod")),
        ImportField("full_name", "Nombre completo", True, ("nombre", "apellido", "nombres", "apellidos")),
        ImportField("document_id", "Documento", False, ("dni", "ce", "documento", "dni/ce")),
        ImportField("email", "Correo", False, ("correo", "email", "e-mail")),
        ImportField("phone", "Teléfono", False, ("telefono", "teléfono", "celular", "phone")),
        ImportField("cycle", "Ciclo", False, ("ciclo", "cycle")),
        ImportField("institution", "Institución", False, ("institucion", "institución", "minsa", "essalud")),
        ImportField("sede", "Sede", False, ("sede", "hospital")),
        ImportField("internship_start", "Inicio", False, ("inicio", "start", "fecha inicio"), kind="date"),
        ImportField("internship_end", "Término", False, ("termino", "término", "fin", "end"), kind="date"),
        ImportField("active", "Activo", False, ("activo", "active", "estado")),
    ]

    def resolve(self, ctx, normalized):
        data = {
            "student_code": normalized["student_code"],
            "full_name": normalized["full_name"],
            "document_id": normalized["document_id"] or None,
            "email": normalized["email"] or None,
            "phone": normalized["phone"] or None,
            "cycle": normalized["cycle"],
            "profile_status": "complete",
            "institution_type_id": _idstr(ctx.institution_id(normalized["institution"])),
            "sede_id": _idstr(ctx.sede_id(normalized["sede"])),
            "internship_start": normalized["internship_start"] or None,
            "internship_end": normalized["internship_end"] or None,
        }
        active = (normalized["active"] or "").strip().lower()
        data["_active"] = active not in ("no", "false", "0", "inactivo", "inactive")
        return data

    def find_existing(self, ctx, data):
        return ctx.students.repos.students.get_by_code(data["student_code"]) \
            if data.get("student_code") else None

    def validate(self, ctx, data, existing):
        msgs: list[Message] = []
        try:
            clean, warnings = ctx.students._validate(data, existing=existing)
            data.update(clean)
            for w in warnings:
                msgs.append(Message("warning", "internship_end", w))
        except ValidationError as e:
            msgs.extend(_messages_from_validation_error(e))
        return RowResult(normalized=data, messages=msgs,
                         existing_id=existing.id if existing else None)

    def apply(self, ctx, data, existing, action):
        fields = ("student_code", "full_name", "email", "document_id", "phone",
                  "cycle", "profile_status", "institution_type_id", "sede_id",
                  "internship_start", "internship_end")
        if action == "update" and existing:
            for f in fields:
                if f in data:
                    setattr(existing, f, data[f])
            existing.is_active = data.get("_active", existing.is_active)
            ctx.db.flush()
            return self.entity_type, existing.id
        payload = {f: data.get(f) for f in fields}
        student = Student(**payload, is_active=data.get("_active", True))
        ctx.repos.students.add(student)
        ctx.db.flush()
        return self.entity_type, student.id


# ---------------------------------------------------------------------------
# Sedes
# ---------------------------------------------------------------------------
class SedeProfile(ImportProfile):
    code = "sedes"
    label = "Sedes"
    entity_type = "sede"
    allowed_roles = {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR}
    unique_field = "name"
    fields = [
        ImportField("name", "Nombre", True, ("nombre", "sede", "hospital")),
        ImportField("short_name", "Nombre corto", True, ("corto", "abreviatura", "short")),
        ImportField("institution", "Institución", True, ("institucion", "institución", "minsa", "essalud")),
        ImportField("sede_type", "Tipo", True, ("tipo", "type")),
        ImportField("city", "Ciudad", False, ("ciudad", "city")),
        ImportField("address", "Dirección", False, ("direccion", "dirección", "address")),
    ]

    def resolve(self, ctx, normalized):
        return {
            "name": normalized["name"], "short_name": normalized["short_name"],
            "institution_type_id": _idstr(ctx.institution_id(normalized["institution"])),
            "sede_type": normalized["sede_type"].strip().lower(),
            "city": normalized["city"] or None, "address": normalized["address"] or None,
        }

    def find_existing(self, ctx, data):
        return ctx.repos.sedes.get_by_name(data["name"]) if data.get("name") else None

    def validate(self, ctx, data, existing):
        msgs: list[Message] = []
        try:
            clean = ctx.sedes._validate(data, existing=existing)
            data.update(clean)
        except ValidationError as e:
            msgs.extend(_messages_from_validation_error(e))
        return RowResult(normalized=data, messages=msgs,
                         existing_id=existing.id if existing else None)

    def apply(self, ctx, data, existing, action):
        from app.models.organization import Sede
        fields = ("name", "short_name", "institution_type_id", "sede_type", "city", "address")
        if action == "update" and existing:
            for f in fields:
                setattr(existing, f, data[f])
            ctx.db.flush()
            return self.entity_type, existing.id
        sede = Sede(**{f: data[f] for f in fields})
        ctx.repos.sedes.add(sede)
        ctx.db.flush()
        return self.entity_type, sede.id


# ---------------------------------------------------------------------------
# Staff (coordinators + tutors) share most logic
# ---------------------------------------------------------------------------
class _StaffProfile(ImportProfile):
    allowed_roles = {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR}
    unique_field = "email"
    fields = [
        ImportField("full_name", "Nombre completo", True, ("nombre", "apellido", "docente")),
        ImportField("email", "Correo", True, ("correo", "email", "e-mail")),
        ImportField("phone", "Teléfono", False, ("telefono", "teléfono", "celular")),
        ImportField("specialty", "Especialidad", False, ("especialidad", "specialty")),
        ImportField("sede", "Sede", True, ("sede", "hospital")),
    ]

    def resolve(self, ctx, normalized):
        return {
            "full_name": normalized["full_name"], "email": normalized["email"],
            "phone": normalized["phone"] or None,
            "specialty": normalized["specialty"] or None,
            "sede_id": _idstr(ctx.sede_id(normalized["sede"])),
        }

    def find_existing(self, ctx, data):
        user = ctx.repos.users.get_by_email(data["email"]) if data.get("email") else None
        return user  # existence handled per-subclass; treated as duplicate


class CoordinatorProfile(_StaffProfile):
    code = "coordinators"
    label = "Coordinadores de Sede"
    entity_type = "sede_coordinator"

    def validate(self, ctx, data, existing):
        msgs: list[Message] = []
        try:
            clean = ctx.coordinators._validate({**data, "office_phone": data.get("phone")},
                                               existing=None)
            data.update(clean)
        except ValidationError as e:
            msgs.extend(_messages_from_validation_error(e))
        return RowResult(normalized=data, messages=msgs,
                         existing_id=existing.id if existing else None)

    def apply(self, ctx, data, existing, action):
        user, _ = ctx.coordinators._create_user(
            full_name=data["full_name"], email=data["email"], phone=data.get("phone"),
            role_code=ROLE_SEDE_COORDINATOR, password=None)
        prof = SedeCoordinatorProfile(
            user_id=user.id, sede_id=data["sede_id"], specialty=data.get("specialty"),
            office_phone=data.get("phone"), is_principal=False, is_active=True)
        ctx.repos.sede_coordinators.add(prof)
        ctx.db.flush()
        return self.entity_type, prof.id


class TutorProfileImport(_StaffProfile):
    code = "tutors"
    label = "Tutores"
    entity_type = "tutor"

    def validate(self, ctx, data, existing):
        msgs: list[Message] = []
        try:
            clean = ctx.tutors._validate({**data, "service": data.get("specialty")},
                                         existing=None)
            data.update(clean)
        except ValidationError as e:
            msgs.extend(_messages_from_validation_error(e))
        return RowResult(normalized=data, messages=msgs,
                         existing_id=existing.id if existing else None)

    def apply(self, ctx, data, existing, action):
        user, _ = ctx.tutors._create_user(
            full_name=data["full_name"], email=data["email"], phone=data.get("phone"),
            role_code=ROLE_TUTOR, password=None)
        prof = TutorProfile(
            user_id=user.id, sede_id=data["sede_id"], specialty=data.get("specialty"),
            service=data.get("specialty"), contact_phone=data.get("phone"), is_active=True)
        ctx.repos.tutors.add(prof)
        ctx.db.flush()
        return self.entity_type, prof.id


# ---------------------------------------------------------------------------
# Rotations
# ---------------------------------------------------------------------------
class RotationProfile(ImportProfile):
    code = "rotations"
    label = "Rotaciones"
    entity_type = "rotation_assignment"
    allowed_roles = {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR}
    unique_field = "student_code"
    fields = [
        ImportField("student_code", "Código interno", True, ("codigo", "código", "interno", "alumno")),
        ImportField("rotation_type", "Rotación", True, ("rotacion", "rotación", "especialidad", "curso")),
        ImportField("sede", "Sede", True, ("sede", "hospital")),
        ImportField("tutor_email", "Tutor (correo)", False, ("tutor", "correo tutor")),
        ImportField("period", "Periodo", True, ("periodo", "período", "bimestre")),
        ImportField("start_date", "Inicio", False, ("inicio", "start"), kind="date"),
        ImportField("end_date", "Término", False, ("termino", "término", "fin", "end"), kind="date"),
        ImportField("status", "Estado", False, ("estado", "status")),
    ]

    def resolve(self, ctx, normalized):
        student = ctx.student_by_code(normalized["student_code"])
        status = (normalized["status"] or "planned").strip().lower()
        if status not in {s.value for s in AssignmentStatus}:
            status = AssignmentStatus.PLANNED.value
        return {
            "_student_code": normalized["student_code"],
            "student_id": student.id if student else None,
            "rotation_type_id": ctx.rotation_type_id(normalized["rotation_type"]),
            "sede_id": ctx.sede_id(normalized["sede"]),
            "tutor_id": ctx.tutor_id_by_email(normalized["tutor_email"]),
            "period_id": ctx.period_id(normalized["period"]),
            "start_date": normalized["start_date"] or None,
            "end_date": normalized["end_date"] or None,
            "status": status,
        }

    def find_existing(self, ctx, data):
        # A duplicate core rotation is (student, rotation_type, period).
        if not (data.get("student_id") and data.get("rotation_type_id") and data.get("period_id")):
            return None
        for a in ctx.repos.assignments.search(student_id=data["student_id"]):
            if a.rotation_type_id == data["rotation_type_id"] and a.period_id == data["period_id"]:
                return a
        return None

    def validate(self, ctx, data, existing):
        msgs: list[Message] = []
        if data.get("student_id") is None:
            msgs.append(Message("error", "student_code",
                                f"No se encontró el interno con código «{data.get('_student_code')}»."))
        if data.get("rotation_type_id") is None:
            msgs.append(Message("error", "rotation_type", "Rotación no reconocida."))
        if data.get("sede_id") is None:
            msgs.append(Message("error", "sede", "Sede no reconocida."))
        if data.get("period_id") is None:
            msgs.append(Message("error", "period", "Periodo no reconocido."))
        # Reuse the authoritative conflict engine (overlap, duplicate core, tutor
        # mismatch, institution mismatch, community rule, date/period) for warnings.
        if not any(m.level == "error" for m in msgs):
            start = _parse_date(data.get("start_date"))
            end = _parse_date(data.get("end_date"))
            conflicts = ctx.rotations.conflicts.check(RotationInput(
                student_id=data["student_id"], rotation_type_id=data["rotation_type_id"],
                sede_id=data["sede_id"], period_id=data["period_id"],
                tutor_id=data.get("tutor_id"), start_date=start, end_date=end,
                assignment_id=existing.id if existing else None))
            for c in conflicts:
                level = "error" if c.blocking and not c.can_override else "warning"
                msgs.append(Message(level, "conflict", f"{c.title}: {c.message}"))
        return RowResult(normalized=data, messages=msgs,
                         existing_id=existing.id if existing else None)

    def apply(self, ctx, data, existing, action):
        payload = dict(
            student_id=data["student_id"], rotation_type_id=data["rotation_type_id"],
            sede_id=data["sede_id"], period_id=data["period_id"],
            tutor_id=data.get("tutor_id"),
            start_date=_parse_date(data.get("start_date")),
            end_date=_parse_date(data.get("end_date")), status=data["status"])
        if action == "update" and existing:
            for k, v in payload.items():
                setattr(existing, k, v)
            ctx.db.flush()
            return self.entity_type, existing.id
        a = RotationAssignment(**payload, created_by_user_id=ctx.identity.user_id)
        ctx.repos.assignments.add(a)
        ctx.db.flush()
        return self.entity_type, a.id


def _parse_date(v) -> date | None:
    if not v:
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
_MASTER_PROFILES: dict[str, ImportProfile] = {
    p.code: p for p in (
        StudentProfile(), SedeProfile(), CoordinatorProfile(),
        TutorProfileImport(), RotationProfile(),
    )
}


def get_profile(code: str) -> ImportProfile | None:
    if code in _MASTER_PROFILES:
        return _MASTER_PROFILES[code]
    if code == "grade_components":
        from app.services.grade_service import GradeComponentProfile
        return GradeComponentProfile()
    return None


def all_profiles() -> list[ImportProfile]:
    from app.services.grade_service import GradeComponentProfile
    return list(_MASTER_PROFILES.values()) + [GradeComponentProfile()]
