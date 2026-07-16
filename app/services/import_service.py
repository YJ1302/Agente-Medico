"""Bulk-import orchestration service (Batch 2F).

Drives the whole workflow — upload → sheet → map → validate (dry-run) → confirm
(transactional) — reusing the existing per-entity services for validation and
persisting a whole batch in a single transaction (all-or-nothing). No file is
imported automatically; confirmation is always an explicit human step and is
rejected if the file/mapping changed since validation (stale-confirmation guard).
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid

from sqlalchemy.orm import Session

from app.authorization import ensure, is_global_viewer
from app.config import settings
from app.models.base import ImportMode, ImportRowStatus, ImportStatus, utcnow
from app.models.imports import ImportBatch, ImportRow
from app.models.user import ROLE_SEDE_COORDINATOR
from app.repositories.repositories import RepositoryBundle
from app.services import audit_service as audit
from app.services import excel_reader
from app.services.audit_service import AuditService
from app.services.auth_service import Identity
from app.services.import_profiles import ImportContext, get_profile
from app.services.numbering import allocate_code
from app.services.validators import ValidationError

_ACTIVE_STATUSES = {ImportStatus.UPLOADED.value, ImportStatus.MAPPED.value,
                    ImportStatus.VALIDATED.value}


class ImportService:
    def __init__(self, db: Session, identity: Identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)
        self.audit = AuditService(db)

    # -- scope / access ---------------------------------------------------
    def _own_sede_ids(self) -> set[int]:
        return {c.sede_id for c in self.repos.sede_coordinators.active()
                if c.user_id == self.identity.user_id and c.sede_id}

    def can_use_profile(self, profile_code: str) -> bool:
        profile = get_profile(profile_code)
        return bool(profile) and self.identity.role_code in profile.allowed_roles

    def _sede_scope(self) -> set[int] | None:
        if self.identity.role_code == ROLE_SEDE_COORDINATOR and not is_global_viewer(self.identity):
            return self._own_sede_ids() or {-1}
        return None

    def can_view_batch(self, batch: ImportBatch) -> bool:
        if is_global_viewer(self.identity):
            return True
        return batch.created_by_user_id == self.identity.user_id

    # -- storage ----------------------------------------------------------
    def _path(self, stored_filename: str):
        root = settings.import_storage_path
        root.mkdir(parents=True, exist_ok=True)
        candidate = (root / os.path.basename(stored_filename)).resolve()
        if root not in candidate.parents and candidate.parent != root:
            raise ValidationError({"file": "Ruta de archivo inválida."})
        return candidate

    def _read_bytes(self, batch: ImportBatch) -> bytes:
        if not batch.stored_filename:
            raise ValidationError({"file": "El archivo de importación ya no está disponible."})
        path = self._path(batch.stored_filename)
        if not path.exists():
            raise ValidationError({"file": "El archivo de importación ya no está disponible."})
        return path.read_bytes()

    def _content_hash(self, raw: bytes, sheet: str | None, mapping_json: str | None) -> str:
        h = hashlib.sha256()
        h.update(raw)
        h.update((sheet or "").encode())
        h.update((mapping_json or "").encode())
        return h.hexdigest()

    # -- step 1: upload ---------------------------------------------------
    def create_batch(self, profile_code: str, filename: str,
                     content_type: str | None, raw: bytes,
                     scheme_id: int | None = None, ip: str | None = None) -> ImportBatch:
        ensure(self.can_use_profile(profile_code),
               "No tiene permiso para importar este tipo de datos.", "import_profile_denied")
        excel_reader.validate_upload(filename, content_type, raw)
        excel_reader.load_workbook(raw)  # readability / malformed / duplicate sheets
        stored = f"{uuid.uuid4().hex}.{filename.rsplit('.', 1)[-1].lower()}"
        self._path(stored).write_bytes(raw)
        code = self._allocate_code()
        scope = self._sede_scope()
        # Grade imports carry the target scheme id in the mapping from the start.
        mapping_json = (json.dumps({"_scheme_id": str(scheme_id)})
                        if profile_code == "grade_components" and scheme_id else None)
        batch = ImportBatch(
            code=code, profile=profile_code, original_filename=os.path.basename(filename),
            stored_filename=stored, status=ImportStatus.UPLOADED.value,
            mapping_json=mapping_json,
            created_by_user_id=self.identity.user_id,
            sede_scope_id=next(iter(scope)) if scope and len(scope) == 1 else None,
        )
        self.repos.import_batches.add(batch)
        self.db.flush()
        self.audit.record(audit.UPLOAD_IMPORT_FILE, identity=self.identity,
                          entity_type="import_batch", entity_id=batch.id,
                          detail={"code": code, "profile": profile_code,
                                  "filename": batch.original_filename, "size": len(raw)},
                          ip_address=ip, commit=False)
        self.audit.record(audit.CREATE_IMPORT_BATCH, identity=self.identity,
                          entity_type="import_batch", entity_id=batch.id,
                          detail={"code": code, "profile": profile_code}, ip_address=ip, commit=False)
        self.db.commit()
        return batch

    def _allocate_code(self) -> str:
        for _ in range(3):
            code = allocate_code(self.repos, "import")
            if not self.repos.import_batches.get_by_code(code):
                return code
        return code

    # -- step 2: sheet + auto-map ----------------------------------------
    def sheets(self, batch: ImportBatch) -> list[str]:
        return excel_reader.list_sheets(self._read_bytes(batch))

    def set_sheet(self, batch_id: int, sheet_name: str, ip: str | None = None) -> ImportBatch:
        batch = self._get_editable(batch_id)
        raw = self._read_bytes(batch)
        preview = excel_reader.read_sheet(raw, sheet_name)
        profile = get_profile(batch.profile)
        mapping = profile.auto_map(preview.headers)
        # Preserve a pre-set scheme id (grade imports) across auto-mapping.
        prev = json.loads(batch.mapping_json or "{}")
        if prev.get("_scheme_id"):
            mapping["_scheme_id"] = prev["_scheme_id"]
        batch.sheet_name = sheet_name
        batch.mapping_json = json.dumps(mapping, ensure_ascii=False)
        batch.status = ImportStatus.MAPPED.value
        self.db.flush()
        self.db.commit()
        return batch

    # -- step 3: mapping + mode ------------------------------------------
    def set_mapping(self, batch_id: int, mapping: dict[str, str], mode: str,
                    ip: str | None = None) -> ImportBatch:
        batch = self._get_editable(batch_id)
        if mode not in {m.value for m in ImportMode}:
            mode = ImportMode.CREATE_ONLY.value
        cleaned = {k: v for k, v in mapping.items() if v}
        # Preserve the scheme id set at creation (grade imports).
        prev = json.loads(batch.mapping_json or "{}")
        if prev.get("_scheme_id") and "_scheme_id" not in cleaned:
            cleaned["_scheme_id"] = prev["_scheme_id"]
        batch.mapping_json = json.dumps(cleaned, ensure_ascii=False)
        batch.mode = mode
        batch.status = ImportStatus.MAPPED.value
        self.db.flush()
        self.audit.record(audit.MAP_IMPORT_COLUMNS, identity=self.identity,
                          entity_type="import_batch", entity_id=batch.id,
                          detail={"code": batch.code, "mode": mode}, ip_address=ip, commit=False)
        self.db.commit()
        return batch

    # -- step 4: validate (dry-run) --------------------------------------
    def validate_batch(self, batch_id: int, ip: str | None = None) -> ImportBatch:
        batch = self._get_editable(batch_id)
        ensure(batch.sheet_name and batch.mapping_json,
               "Seleccione la hoja y el mapeo antes de validar.", "import_not_mapped")
        raw = self._read_bytes(batch)
        results = self._process(batch, raw, persist=False)
        # Replace any previous staged rows.
        self.repos.import_rows.delete_for_batch(batch.id)
        counts = {"valid": 0, "warning": 0, "error": 0}
        for r in results:
            counts["error" if r["status"] == ImportRowStatus.ERROR.value
                   else ("warning" if r["status"] == ImportRowStatus.WARNING.value else "valid")] += 1
            self.db.add(ImportRow(
                batch_id=batch.id, row_number=r["row_number"], source_sheet=batch.sheet_name,
                raw_json=json.dumps(r["raw"], ensure_ascii=False, default=str),
                normalized_json=json.dumps(r["normalized"], ensure_ascii=False, default=str),
                messages_json=json.dumps(r["messages"], ensure_ascii=False),
                status=r["status"], action=r["action"]))
        batch.total_rows = len(results)
        batch.valid_rows = counts["valid"]
        batch.warning_rows = counts["warning"]
        batch.error_rows = counts["error"]
        batch.content_hash = self._content_hash(raw, batch.sheet_name, batch.mapping_json)
        batch.status = ImportStatus.VALIDATED.value
        self.db.flush()
        self.audit.record(audit.VALIDATE_IMPORT_BATCH, identity=self.identity,
                          entity_type="import_batch", entity_id=batch.id,
                          detail={"code": batch.code, "total": batch.total_rows,
                                  "valid": batch.valid_rows, "errors": batch.error_rows},
                          ip_address=ip, commit=False)
        self.db.commit()
        return batch

    # -- step 5: confirm (transactional import) --------------------------
    def confirm_batch(self, batch_id: int, expected_hash: str | None = None,
                      ip: str | None = None) -> ImportBatch:
        batch = self.repos.import_batches.get_full(batch_id)
        ensure(batch is not None, "Importación no encontrada.", "not_found")
        ensure(self.can_use_profile(batch.profile), "No autorizado.", "import_profile_denied")
        # Prevent duplicate confirmation.
        ensure(batch.status == ImportStatus.VALIDATED.value,
               "La importación no está lista para confirmar (o ya fue procesada).",
               "import_not_validated")
        raw = self._read_bytes(batch)
        current_hash = self._content_hash(raw, batch.sheet_name, batch.mapping_json)
        # Stale confirmation guard.
        if batch.content_hash and current_hash != batch.content_hash:
            raise ValidationError({"file": "El archivo o el mapeo cambiaron desde la validación. "
                                           "Vuelva a validar antes de confirmar."})
        if expected_hash and expected_hash != current_hash:
            raise ValidationError({"file": "Confirmación no válida (datos desincronizados). "
                                           "Vuelva a validar."})

        results = self._process(batch, raw, persist=False)
        error_rows = [r for r in results if r["status"] == ImportRowStatus.ERROR.value]

        # all-or-nothing: any error cancels the entire import.
        if batch.mode == ImportMode.ALL_OR_NOTHING.value and error_rows:
            batch.status = ImportStatus.FAILED.value
            self.db.flush()
            self.audit.record(audit.CANCEL_IMPORT_BATCH, identity=self.identity,
                              entity_type="import_batch", entity_id=batch.id,
                              detail={"code": batch.code, "reason": "all_or_nothing_errors",
                                      "errors": len(error_rows)}, ip_address=ip, commit=False)
            self.db.commit()
            raise ValidationError({"file": f"Importación cancelada: {len(error_rows)} fila(s) con "
                                           "errores en modo «todo o nada». No se escribió nada."})

        # Persist within a single transaction.
        ctx = ImportContext(self.db, self.identity, sede_scope_ids=self._sede_scope(), batch=batch)
        profile = get_profile(batch.profile)
        created = updated = skipped = failed = 0
        self.repos.import_rows.delete_for_batch(batch.id)
        try:
            for r in results:
                row = ImportRow(batch_id=batch.id, row_number=r["row_number"],
                                source_sheet=batch.sheet_name,
                                raw_json=json.dumps(r["raw"], ensure_ascii=False, default=str),
                                normalized_json=json.dumps(r["normalized"], ensure_ascii=False, default=str),
                                messages_json=json.dumps(r["messages"], ensure_ascii=False))
                if r["status"] == ImportRowStatus.ERROR.value or r["action"] is None:
                    row.status = (ImportRowStatus.FAILED.value
                                  if r["status"] == ImportRowStatus.ERROR.value
                                  else ImportRowStatus.SKIPPED.value)
                    failed += 1 if row.status == ImportRowStatus.FAILED.value else 0
                elif r["action"] == "skip":
                    row.status = ImportRowStatus.SKIPPED.value
                    skipped += 1
                else:
                    etype, eid = profile.apply(ctx, r["data"], r["existing"], r["action"])
                    row.status = (ImportRowStatus.CREATED.value if r["action"] == "create"
                                  else ImportRowStatus.UPDATED.value)
                    row.target_entity_type, row.target_entity_id = etype, eid
                    if r["action"] == "create":
                        created += 1
                    else:
                        updated += 1
                row.action = r["action"]
                self.db.add(row)
            batch.created_count = created
            batch.updated_count = updated
            batch.skipped_count = skipped
            batch.failed_count = failed
            batch.status = (ImportStatus.PARTIAL.value if (skipped or failed)
                            else ImportStatus.CONFIRMED.value)
            batch.confirmed_by_user_id = self.identity.user_id
            batch.confirmed_at = utcnow()
            self.audit.record(audit.CONFIRM_IMPORT_BATCH, identity=self.identity,
                              entity_type="import_batch", entity_id=batch.id,
                              detail={"code": batch.code, "created": created, "updated": updated,
                                      "skipped": skipped, "failed": failed}, ip_address=ip, commit=False)
            self.db.commit()  # single commit — all rows or none
        except Exception:
            self.db.rollback()
            batch = self.repos.import_batches.get(batch_id)
            batch.status = ImportStatus.FAILED.value
            self.db.commit()
            raise
        self._cleanup_file(batch)
        return batch

    def cancel_batch(self, batch_id: int, ip: str | None = None) -> ImportBatch:
        batch = self.repos.import_batches.get(batch_id)
        ensure(batch is not None, "Importación no encontrada.", "not_found")
        ensure(self.can_view_batch(batch), "No autorizado.", "import_cancel_denied")
        ensure(batch.status in _ACTIVE_STATUSES, "La importación ya fue procesada.",
               "import_not_cancellable")
        batch.status = ImportStatus.CANCELLED.value
        self.db.flush()
        self._cleanup_file(batch)
        self.audit.record(audit.CANCEL_IMPORT_BATCH, identity=self.identity,
                          entity_type="import_batch", entity_id=batch.id,
                          detail={"code": batch.code}, ip_address=ip, commit=False)
        self.db.commit()
        return batch

    def _cleanup_file(self, batch: ImportBatch) -> None:
        if settings.import_retain_files or not batch.stored_filename:
            return
        try:
            path = self._path(batch.stored_filename)
            if path.exists():
                path.unlink()
        except Exception:
            pass
        batch.stored_filename = None
        self.db.commit()

    # -- row processing (shared by validate & confirm) -------------------
    def _process(self, batch: ImportBatch, raw: bytes, *, persist: bool) -> list[dict]:
        profile = get_profile(batch.profile)
        mapping = json.loads(batch.mapping_json or "{}")
        mode = batch.mode
        preview = excel_reader.read_sheet(raw, batch.sheet_name)
        ctx = ImportContext(self.db, self.identity, sede_scope_ids=self._sede_scope(), batch=batch)
        out: list[dict] = []
        for idx, raw_row in enumerate(preview.rows, start=1):
            normalized = profile.normalize(raw_row, mapping)
            data = profile.resolve(ctx, normalized)
            existing = profile.find_existing(ctx, data)
            result = profile.validate(ctx, data, existing)
            messages = [m.as_dict() for m in result.messages]

            # Scope guard (own-sede coordinator).
            if not profile.in_scope(ctx, data):
                messages.append({"level": "error", "field": "sede",
                                 "message": "Fuera de su ámbito de sede."})

            action, mode_msgs = self._decide_action(mode, existing, bool(
                any(m["level"] == "error" for m in messages)))
            messages.extend(mode_msgs)

            has_error = any(m["level"] == "error" for m in messages)
            has_warning = any(m["level"] == "warning" for m in messages)
            status = (ImportRowStatus.ERROR.value if has_error
                      else ImportRowStatus.WARNING.value if has_warning
                      else ImportRowStatus.VALID.value)
            raw_display = {f.label: normalized.get(f.target, "")
                           for f in profile.display_fields(ctx)}
            out.append({
                "row_number": idx, "raw": raw_display, "normalized": normalized,
                "messages": messages, "status": status,
                "action": None if has_error else action,
                "existing": existing, "data": data,
            })
        return out

    @staticmethod
    def _decide_action(mode: str, existing, has_error: bool):
        """Return (action, extra_messages) given the import mode and duplicate state."""
        msgs: list[dict] = []
        if existing is not None:
            if mode == ImportMode.CREATE_ONLY.value:
                msgs.append({"level": "error", "field": "duplicate",
                             "message": "Ya existe un registro con esta clave (modo «solo crear»)."})
                return None, msgs
            if mode == ImportMode.SKIP_DUPLICATES.value:
                return "skip", msgs
            return "update", msgs  # update_existing / valid_only / all_or_nothing
        # New record.
        if mode == ImportMode.UPDATE_EXISTING.value:
            msgs.append({"level": "warning", "field": "duplicate",
                         "message": "No existe un registro para actualizar; se omite."})
            return "skip", msgs
        return "create", msgs

    # -- helpers ----------------------------------------------------------
    def _get_editable(self, batch_id: int) -> ImportBatch:
        batch = self.repos.import_batches.get(batch_id)
        ensure(batch is not None, "Importación no encontrada.", "not_found")
        ensure(self.can_view_batch(batch), "No autorizado.", "import_scope_denied")
        ensure(batch.status in _ACTIVE_STATUSES,
               "La importación ya fue procesada y no puede modificarse.", "import_locked")
        return batch

    def get_for_view(self, batch_id: int) -> ImportBatch:
        batch = self.repos.import_batches.get_full(batch_id)
        ensure(batch is not None, "Importación no encontrada.", "not_found")
        ensure(self.can_view_batch(batch), "No autorizado.", "import_scope_denied")
        return batch

    def list_batches(self, profile: str | None = None) -> list[ImportBatch]:
        if is_global_viewer(self.identity):
            return self.repos.import_batches.recent(profile=profile)
        return self.repos.import_batches.recent(
            profile=profile, created_by_user_id=self.identity.user_id)

    def target_fields(self, batch: ImportBatch) -> list[dict]:
        """Fields to map for this batch (grade components are scheme-driven)."""
        profile = get_profile(batch.profile)
        fields = list(profile.fields)
        if batch.profile == "grade_components":
            mapping = json.loads(batch.mapping_json or "{}")
            scheme_id = mapping.get("_scheme_id")
            if scheme_id:
                components = self.repos.grade_components.for_scheme(int(scheme_id))
                fields = profile.fields_for_scheme(components)
        return [{"target": f.target, "label": f.label, "required": f.required}
                for f in fields]

    def current_mapping(self, batch: ImportBatch) -> dict:
        return json.loads(batch.mapping_json or "{}")

    def headers_for(self, batch: ImportBatch) -> list[str]:
        if not batch.sheet_name:
            return []
        preview = excel_reader.read_sheet(self._read_bytes(batch), batch.sheet_name)
        return preview.headers

    def preview_rows(self, batch: ImportBatch, limit: int = 100) -> list[dict]:
        rows = self.repos.import_rows.for_batch(batch.id)[:limit]
        out = []
        for r in rows:
            out.append({
                "row_number": r.row_number,
                "raw": json.loads(r.raw_json or "{}"),
                "messages": json.loads(r.messages_json or "[]"),
                "status": r.status, "action": r.action,
                "target_entity_id": r.target_entity_id,
            })
        return out

    # -- downloadable error report ---------------------------------------
    def error_report(self, batch: ImportBatch, ip: str | None = None) -> bytes:
        from app.services.export_service import excel_from_table
        rows = self.repos.import_rows.for_batch(batch.id)
        problem_rows = [r for r in rows if r.status in
                        (ImportRowStatus.ERROR.value, ImportRowStatus.WARNING.value,
                         ImportRowStatus.FAILED.value, ImportRowStatus.SKIPPED.value)]
        headers = ["Fila", "Estado", "Nivel", "Campo", "Mensaje"]
        data: list[list] = []
        for r in problem_rows:
            msgs = json.loads(r.messages_json or "[]")
            if not msgs:
                data.append([r.row_number, r.status, "", "", ""])
            for m in msgs:
                data.append([r.row_number, r.status, m.get("level", ""),
                             m.get("field", ""), m.get("message", "")])
        content = excel_from_table(
            title=f"Reporte de errores — {batch.code}", headers=headers, rows=data,
            meta={"Perfil": batch.profile, "Archivo": batch.original_filename,
                  "Generado por": self.identity.email})
        self.audit.record(audit.DOWNLOAD_IMPORT_ERROR_REPORT, identity=self.identity,
                          entity_type="import_batch", entity_id=batch.id,
                          detail={"code": batch.code}, ip_address=ip)
        return content
