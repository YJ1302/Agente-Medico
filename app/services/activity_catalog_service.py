"""Activity catalog management service (Batch 2C).

Owns CRUD for ``ActivityDefinition`` and the official-catalog import
preview/confirm workflow (idempotent by ``code`` — re-running never
duplicates). Role scope: Admin full; University Coordinator create/edit/
(de)activate; Sede Coordinator and Tutor/Student read-only.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.authorization import ensure, is_global_viewer
from app.data.activity_catalog import build_catalog
from app.models.activity import ActivityDefinition, TARGET_FIXED, TARGET_TYPES
from app.repositories.repositories import RepositoryBundle
from app.services import audit_service as audit
from app.services.audit_service import AuditService
from app.services.auth_service import Identity
from app.services.validators import FieldValidator, ValidationError


class ActivityCatalogService:
    def __init__(self, db: Session, identity: Identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)
        self.audit = AuditService(db)

    def can_manage(self) -> bool:
        return is_global_viewer(self.identity)

    # -- listing / detail ---------------------------------------------------
    def list_definitions(self, **filters) -> list[ActivityDefinition]:
        return self.repos.activity_definitions.search(**filters)

    def get_for_view(self, definition_id: int) -> ActivityDefinition:
        d = self.repos.activity_definitions.get(definition_id)
        ensure(d is not None, "Definición no encontrada.", "not_found")
        return d

    # -- validation -----------------------------------------------------------
    def _validate(self, data: dict, *, existing: ActivityDefinition | None) -> dict:
        v = FieldValidator()
        code = v.required("code", data.get("code"), "El código").strip().upper()
        name = v.required("name", data.get("name"), "El nombre")
        target_type = v.choice("target_type", data.get("target_type"), TARGET_TYPES,
                               "El tipo de meta") or "no_fixed_target"
        target_count = None
        if target_type == TARGET_FIXED:
            target_count = v.int_field("target_count", data.get("target_count"),
                                       "La meta numérica", min_v=1)
            if not target_count:
                v.add("target_count", "Las metas fijas requieren un número entero positivo.")
        rotation_type_id = v.int_field("rotation_type_id", data.get("rotation_type_id"),
                                       "La rotación")

        if code:
            dup = self.repos.activity_definitions.get_by_code(code)
            if dup and (existing is None or dup.id != existing.id):
                v.add("code", "El código ya existe.")

        v.raise_if_errors()
        return {
            "code": code, "name": name, "category": (data.get("category") or None),
            "description": (data.get("description") or "").strip() or None,
            "target_type": target_type, "target_count": target_count,
            "unit_label": (data.get("unit_label") or "").strip() or None,
            "rotation_type_id": rotation_type_id,
            "requires_tutor_verification": data.get("requires_tutor_verification") == "1",
            "evidence_policy": data.get("evidence_policy") or "anonymous_reference",
            "supervision_required": data.get("supervision_required") == "1",
            "is_provisional": data.get("is_provisional") == "1",
            "display_order": v.int_field("display_order", data.get("display_order"),
                                         "El orden") or 0,
        }

    def create(self, data: dict, ip: str | None = None) -> ActivityDefinition:
        ensure(self.can_manage(), "No puede crear definiciones.", "create_activity_def_denied")
        clean = self._validate(data, existing=None)
        d = ActivityDefinition(**clean)
        self.repos.activity_definitions.add(d)
        self.db.flush()
        self.audit.record(audit.CREATE_ACTIVITY_DEFINITION, identity=self.identity,
                          entity_type="activity_definition", entity_id=d.id,
                          detail={"code": d.code}, ip_address=ip, commit=False)
        self.db.commit()
        return d

    def update(self, definition_id: int, data: dict, ip: str | None = None) -> ActivityDefinition:
        d = self.repos.activity_definitions.get(definition_id)
        ensure(d is not None, "Definición no encontrada.", "not_found")
        ensure(self.can_manage(), "No puede editar definiciones.", "edit_activity_def_denied")
        clean = self._validate(data, existing=d)
        for field, value in clean.items():
            setattr(d, field, value)
        self.db.flush()
        self.audit.record(audit.UPDATE_ACTIVITY_DEFINITION, identity=self.identity,
                          entity_type="activity_definition", entity_id=d.id,
                          detail={"code": d.code}, ip_address=ip, commit=False)
        self.db.commit()
        return d

    def set_active(self, definition_id: int, active: bool, ip: str | None = None) -> ActivityDefinition:
        d = self.repos.activity_definitions.get(definition_id)
        ensure(d is not None, "Definición no encontrada.", "not_found")
        ensure(self.can_manage(), "No puede modificar definiciones.", "toggle_activity_def_denied")
        d.is_active = active
        self.db.flush()
        self.audit.record(audit.DEACTIVATE_ACTIVITY_DEFINITION, identity=self.identity,
                          entity_type="activity_definition", entity_id=d.id,
                          detail={"is_active": active}, ip_address=ip, commit=False)
        self.db.commit()
        return d

    # -- catalog import (idempotent by code) ---------------------------------
    def preview_import(self) -> dict:
        """Diff the official catalog against the DB: new / already-present rows."""
        catalog = build_catalog()
        existing_codes = {d.code for d in self.repos.activity_definitions.list()}
        new_items = [c for c in catalog if c.code not in existing_codes]
        present_items = [c for c in catalog if c.code in existing_codes]
        self.audit.record(audit.IMPORT_ACTIVITY_CATALOG_PREVIEW, identity=self.identity,
                          entity_type="activity_definition",
                          detail={"new_count": len(new_items), "present_count": len(present_items)})
        return {"new_items": new_items, "present_items": present_items, "total": len(catalog)}

    def confirm_import(self, ip: str | None = None) -> int:
        ensure(self.can_manage(), "No puede importar el catálogo.", "import_catalog_denied")
        catalog = build_catalog()
        rotation_ids = {rt.code: rt.id for rt in self.repos.rotation_types.list()}
        existing_codes = {d.code for d in self.repos.activity_definitions.list()}
        created = 0
        for item in catalog:
            if item.code in existing_codes:
                continue
            self.repos.activity_definitions.add(ActivityDefinition(
                code=item.code, name=item.name, category=item.category,
                description=item.description,
                rotation_type_id=rotation_ids.get(item.rotation_code) if item.rotation_code else None,
                target_type=item.target_type, target_count=item.target_count,
                unit_label=item.unit_label,
                requires_tutor_verification=item.requires_tutor_verification,
                evidence_policy=item.evidence_policy,
                supervision_required=item.supervision_required,
                source_document=item.source_document, source_year=item.source_year,
                source_section=item.source_section, is_provisional=item.is_provisional,
                display_order=item.display_order,
            ))
            created += 1
        self.db.flush()
        self.audit.record(audit.IMPORT_ACTIVITY_CATALOG_CONFIRMED, identity=self.identity,
                          entity_type="activity_definition", detail={"created": created},
                          ip_address=ip, commit=False)
        self.db.commit()
        return created

    def form_options(self) -> dict:
        return {
            "rotation_types": [(r.id, r.name) for r in self.repos.rotation_types.list()],
            "target_types": [("fixed", "Meta fija"), ("no_fixed_target", "Sin meta fija (NA)"),
                             ("completion_only", "Solo cumplimiento")],
            "categories": [("hospitalization", "Hospitalización"), ("emergency", "Emergencia"),
                          ("community", "Comunidad"), ("academic", "Académica"),
                          ("clinical_topic", "Tema clínico"), ("procedure", "Procedimiento")],
            "evidence_policies": [("none", "Ninguna"), ("anonymous_reference", "Referencia anónima"),
                                  ("optional_attachment", "Adjunto opcional")],
        }
