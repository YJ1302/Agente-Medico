"""Academic grade foundation service + grade-import profile (Batch 2F).

Stores grade components faithfully and **never** computes a final grade until
the official weights are confirmed. Import rules (GRADE_IMPORT_RULES.md):

* Blank cell → ``score = NULL`` (not registered); a real ``0`` is kept as ``0``.
* Scores outside 0–max (default 20) are rejected.
* An existing **approved** component is never overwritten silently — a differing
  value is flagged and only applied on a confirmed update, always with history.
* Source sheet/row/column and the import batch are preserved on every component.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.authorization import ensure, is_admin, is_global_viewer
from app.models.base import GradeComponentStatus, utcnow
from app.models.grades import GradeComponentHistory, StudentGradeComponent
from app.models.user import ROLE_SEDE_COORDINATOR, ROLE_STUDENT
from app.repositories.repositories import RepositoryBundle
from app.services import audit_service as audit
from app.services.audit_service import AuditService
from app.services.auth_service import Identity
from app.services.import_profiles import (
    ImportField,
    ImportProfile,
    Message,
    RowResult,
    as_str,
)
from app.models.user import ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR


# ---------------------------------------------------------------------------
# Real-workbook compatibility mapping (BASE DE DATOS - NOTAS INTERNADO MÉDICO)
#
# The client's official workbook uses these exact sheet names and a merged
# "category band" row (Actitudinal / Desempeño / Conocimiento) directly above
# the real header row. This maps sheet names to a suggested rotation type code
# and free-text category labels to our internal GRADE_CATEGORIES codes, so the
# scheme-authoring UI can pre-fill sensible defaults — it never invents weights
# or a final formula.
# ---------------------------------------------------------------------------
SHEET_ROTATION_HINTS: dict[str, str] = {
    "qx 2026": "",                       # ENAM simulacro average — not rotation-specific
    "int. cirugía": "CIR",
    "int. cirugia": "CIR",
    "int. medicina": "MED",
    "int. pediatría": "PED",
    "int. pediatria": "PED",
    "int. go": "GO",
    "rev. med. quir iii": "",            # cross-specialty review, no single rotation
    "rev. med. quir iv": "",
}

# Free-text category-band label -> internal GRADE_CATEGORIES code.
CATEGORY_BAND_ALIASES: dict[str, str] = {
    "actitudinal": "actitudinal",
    "desempeño": "desempeno",
    "desempeno": "desempeno",
    "conocimiento": "conocimiento",
}


def rotation_hint_for_sheet(sheet_name: str) -> str:
    return SHEET_ROTATION_HINTS.get((sheet_name or "").strip().lower(), "")


def category_code_for_band(band_label: str) -> str:
    return CATEGORY_BAND_ALIASES.get((band_label or "").strip().lower(), "otro")


def _parse_score(raw, max_score: float):
    """Return (value_or_None, error_message_or_None). Blank → (None, None)."""
    if raw is None:
        return None, None
    if isinstance(raw, str) and raw.strip() == "":
        return None, None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, "Valor no numérico."
    if value < 0 or value > max_score:
        return None, f"Puntaje fuera de rango (0–{int(max_score)})."
    return value, None


# ---------------------------------------------------------------------------
# Grade-import profile (registered via import_profiles.get_profile)
# ---------------------------------------------------------------------------
class GradeComponentProfile(ImportProfile):
    code = "grade_components"
    label = "Componentes de nota"
    entity_type = "student_grade_component"
    allowed_roles = {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR}
    unique_field = "student_key"
    # Only the student key is a fixed field; component columns are added
    # dynamically from the chosen scheme (see fields_for_scheme()).
    fields = [
        ImportField("student_key", "Interno (código/DNI)", True,
                    ("dni", "ce", "codigo", "código", "documento", "dni/ce")),
        # Optional — captured for display/cross-sheet mismatch detection only;
        # the authoritative match is always by student_key, never by name.
        ImportField("student_name", "Nombre del alumno", False,
                    ("nombre del alumno", "nombre", "apellido", "apellidos y nombres")),
    ]

    def fields_for_scheme(self, components) -> list[ImportField]:
        base = list(self.fields)
        for c in components:
            base.append(ImportField(f"comp_{c.id}", c.name, c.is_required,
                                    (c.name.lower(),)))
        return base

    def display_fields(self, ctx) -> list[ImportField]:
        scheme_id = self._scheme_id(ctx)
        if scheme_id:
            components = ctx.repos.grade_components.for_scheme(scheme_id)
            return self.fields_for_scheme(components)
        return self.fields

    def _scheme_id(self, ctx) -> int | None:
        if not (ctx.batch and ctx.batch.mapping_json):
            return None
        mapping = json.loads(ctx.batch.mapping_json)
        val = mapping.get("_scheme_id")
        try:
            return int(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    def auto_map(self, headers: list[str]) -> dict[str, str]:
        # The student key and (optionally) the display name can be
        # auto-detected without knowing the scheme; component columns cannot.
        mapping: dict[str, str] = {}
        lowered = {h: h.strip().lower() for h in headers}
        for target, aliases in (("student_key", self.fields[0].aliases),
                                ("student_name", self.fields[1].aliases)):
            for h, hl in lowered.items():
                if any(a in hl for a in aliases):
                    mapping[target] = h
                    break
        return mapping

    def normalize(self, raw: dict, mapping: dict[str, str]) -> dict:
        out: dict = {}
        for target, header in mapping.items():
            if target == "_scheme_id":
                out["_scheme_id"] = header
                continue
            # Keep the RAW value for component cells (blank vs zero distinction).
            out[target] = raw.get(header)
        return out

    def resolve(self, ctx, normalized: dict) -> dict:
        scheme_id = self._scheme_id(ctx)
        components = ctx.repos.grade_components.for_scheme(scheme_id) if scheme_id else []
        by_id = {c.id: c for c in components}
        student_key = as_str(normalized.get("student_key"))
        student = ctx.repos.students.get_by_code(student_key) if student_key else None
        if student is None and student_key:
            student = ctx.repos.students.get_by_document(student_key)
        comp_values = []
        for target, raw in normalized.items():
            if not target.startswith("comp_"):
                continue
            cid = int(target.split("_", 1)[1])
            comp = by_id.get(cid)
            if comp is not None:
                comp_values.append({"component_id": cid, "name": comp.name,
                                    "max_score": comp.max_score,
                                    "required": comp.is_required, "raw": raw})
        return {
            "_scheme_id": scheme_id, "student_id": student.id if student else None,
            "student_key": student_key,
            "student_name": as_str(normalized.get("student_name")),
            "components": comp_values,
        }

    def find_existing(self, ctx, data):
        # Grades are upserted at the component level; row-level dedup is not used.
        return None

    def validate(self, ctx, data, existing) -> RowResult:
        msgs: list[Message] = []
        if data.get("_scheme_id") is None:
            msgs.append(Message("error", "scheme", "No se seleccionó un esquema de notas."))
        if data.get("student_id") is None:
            msgs.append(Message("error", "student_key",
                                f"No se encontró el interno «{data.get('student_key')}»."))
        else:
            key = data["student_key"]
            if key in ctx.seen:
                msgs.append(Message("warning", "student_key",
                                    "El interno aparece más de una vez en la hoja."))
            ctx.seen[key] = ctx.seen.get(key, 0) + 1
        for comp in data.get("components", []):
            value, err = _parse_score(comp["raw"], comp["max_score"])
            comp["value"] = value
            comp["blank"] = (comp["raw"] is None
                             or (isinstance(comp["raw"], str) and comp["raw"].strip() == ""))
            if err:
                msgs.append(Message("error", comp["name"], f"{comp['name']}: {err}"))
            elif comp["blank"] and comp["required"]:
                msgs.append(Message("warning", comp["name"],
                                    f"{comp['name']}: componente requerido en blanco."))
            # Approved-value protection.
            if data.get("student_id") and value is not None:
                existing_sgc = ctx.repos.student_grades.get_one(
                    data["student_id"], data["_scheme_id"], comp["component_id"])
                if existing_sgc and existing_sgc.status == GradeComponentStatus.APPROVED.value \
                        and existing_sgc.score != value:
                    msgs.append(Message("warning", comp["name"],
                                        f"{comp['name']}: sobrescribe una nota aprobada "
                                        "(requiere confirmación)."))
        return RowResult(normalized=data, messages=msgs, existing_id=None)

    def in_scope(self, ctx, data) -> bool:
        return True  # grade imports are global-viewer only

    def apply(self, ctx, data, existing, action):
        scheme_id = data["_scheme_id"]
        student_id = data["student_id"]
        sheet = ctx.batch.sheet_name if ctx.batch else None
        batch_id = ctx.batch.id if ctx.batch else None
        audit_svc = AuditService(ctx.db)
        touched = 0
        for comp in data.get("components", []):
            value = comp.get("value")
            blank = comp.get("blank")
            sgc = ctx.repos.student_grades.get_one(student_id, scheme_id, comp["component_id"])
            if sgc is None:
                sgc = StudentGradeComponent(
                    student_id=student_id, scheme_id=scheme_id,
                    component_id=comp["component_id"],
                    score=value, status=GradeComponentStatus.IMPORTED.value,
                    source_type="import", source_batch_id=batch_id, source_sheet=sheet,
                    source_row=comp.get("_row"), source_col=comp["name"],
                    entered_by_user_id=ctx.identity.user_id)
                ctx.repos.student_grades.add(sgc)
                ctx.db.flush()
                ctx.db.add(GradeComponentHistory(
                    student_grade_component_id=sgc.id, old_score=None, new_score=value,
                    old_status=None, new_status=sgc.status, action="import_created",
                    actor_user_id=ctx.identity.user_id, actor_label=ctx.identity.email,
                    batch_id=batch_id))
                touched += 1
            else:
                # Blank never erases an existing value.
                if blank or value is None or sgc.score == value:
                    continue
                old_score, old_status = sgc.score, sgc.status
                sgc.score = value
                sgc.source_type = "import"
                sgc.source_batch_id = batch_id
                sgc.source_sheet = sheet
                # An approved value that changes stays flagged for re-review.
                if sgc.status == GradeComponentStatus.APPROVED.value:
                    sgc.status = GradeComponentStatus.IMPORTED.value
                ctx.db.flush()
                ctx.db.add(GradeComponentHistory(
                    student_grade_component_id=sgc.id, old_score=old_score, new_score=value,
                    old_status=old_status, new_status=sgc.status, action="import_updated",
                    actor_user_id=ctx.identity.user_id, actor_label=ctx.identity.email,
                    batch_id=batch_id))
                audit_svc.record(audit.UPDATE_GRADE_COMPONENT_FROM_IMPORT, identity=ctx.identity,
                                 entity_type="student_grade_component", entity_id=sgc.id,
                                 detail={"old": old_score, "new": value}, commit=False)
                touched += 1
        audit_svc.record(audit.IMPORT_GRADE_COMPONENT, identity=ctx.identity,
                         entity_type="student", entity_id=student_id,
                         detail={"scheme_id": scheme_id, "components": touched}, commit=False)
        return self.entity_type, student_id


# ---------------------------------------------------------------------------
# Grade viewing / approval service
# ---------------------------------------------------------------------------
class GradeService:
    def __init__(self, db: Session, identity: Identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)
        self.audit = AuditService(db)

    def can_manage(self) -> bool:
        return is_global_viewer(self.identity)

    def list_schemes(self):
        return self.repos.grade_schemes.active()

    def get_scheme(self, scheme_id: int):
        scheme = self.repos.grade_schemes.get_full(scheme_id)
        ensure(scheme is not None, "Esquema no encontrado.", "not_found")
        return scheme

    def final_grade_note(self, scheme) -> str | None:
        """Never compute a final grade until weights are confirmed."""
        components = self.repos.grade_components.for_scheme(scheme.id)
        missing = [c for c in components if c.is_required and c.weight_percent is None]
        if not scheme.weights_confirmed or missing:
            return "Fórmula pendiente de confirmación"
        return None  # weights confirmed — computation belongs to the future agent

    def build_matrix(self, scheme_id: int) -> dict:
        scheme = self.get_scheme(scheme_id)
        components = self.repos.grade_components.for_scheme(scheme_id)
        rows = self.repos.student_grades.for_scheme(scheme_id)
        by_student: dict[int, dict[int, StudentGradeComponent]] = {}
        for sgc in rows:
            by_student.setdefault(sgc.student_id, {})[sgc.component_id] = sgc
        students = []
        for sid in by_student:
            st = self.repos.students.get(sid)
            if st:
                students.append(st)
        students.sort(key=lambda s: s.full_name)
        return {
            "scheme": scheme, "components": components, "students": students,
            "cells": by_student, "final_note": self.final_grade_note(scheme),
        }

    def approve_component(self, sgc_id: int, ip: str | None = None):
        ensure(self.can_manage(), "No puede aprobar notas.", "approve_grade_denied")
        sgc = self.repos.student_grades.get(sgc_id)
        ensure(sgc is not None, "Componente no encontrado.", "not_found")
        old_status = sgc.status
        sgc.status = GradeComponentStatus.APPROVED.value
        sgc.approved_by_user_id = self.identity.user_id
        sgc.approved_at = utcnow()
        self.db.flush()
        self.db.add(GradeComponentHistory(
            student_grade_component_id=sgc.id, old_score=sgc.score, new_score=sgc.score,
            old_status=old_status, new_status=sgc.status, action="approve",
            actor_user_id=self.identity.user_id, actor_label=self.identity.email))
        self.db.commit()
        return sgc

    def can_view_scheme(self) -> bool:
        # Students never see the raw grade matrix; staff within scope may.
        return self.identity.role_code not in (ROLE_STUDENT,)

    # -- cross-sheet consistency (multi-batch comparison) -----------------
    def cross_sheet_report(self, batch_ids: list[int]) -> dict:
        """Compare the student sets imported by several grade-import batches.

        Surfaces students present in some sheets but not others, and any
        name/code mismatch for the same key across sheets — a common real-
        workbook issue (e.g. a student listed in "INT. CIRUGÍA" but missing
        from "QX 2026"). This is a read-only report; it never mutates data.
        """
        batches = [b for b in (self.repos.import_batches.get(bid) for bid in batch_ids) if b]
        by_sheet: dict[str, set[str]] = {}
        names_by_key: dict[str, dict[str, str]] = {}
        for b in batches:
            # Key by the unique batch code (not sheet_name): two batches may
            # legitimately share the same sheet name from different uploads.
            sheet = f"{b.code} ({b.sheet_name})" if b.sheet_name else b.code
            keys = set()
            for row in self.repos.import_rows.for_batch(b.id):
                normalized = json.loads(row.normalized_json or "{}")
                key = str(normalized.get("student_key") or "").strip()
                if not key:
                    continue
                keys.add(key)
                name = str(normalized.get("student_name") or "").strip()
                if name:
                    names_by_key.setdefault(key, {})[sheet] = name
            by_sheet[sheet] = keys

        all_keys = set().union(*by_sheet.values()) if by_sheet else set()
        missing: list[dict] = []
        for key in sorted(all_keys):
            present_in = [s for s, ks in by_sheet.items() if key in ks]
            absent_from = [s for s in by_sheet if s not in present_in]
            if absent_from:
                missing.append({"student_key": key, "present_in": present_in,
                                "absent_from": absent_from})

        mismatches: list[dict] = []
        for key, names in names_by_key.items():
            distinct = {n for n in names.values() if n}
            if len(distinct) > 1:
                mismatches.append({"student_key": key, "names": names})

        return {"sheets": list(by_sheet.keys()), "missing": missing,
                "mismatches": mismatches, "total_students": len(all_keys)}
