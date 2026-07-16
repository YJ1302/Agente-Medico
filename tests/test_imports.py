"""Bulk-import framework tests (Batch 2F)."""

from __future__ import annotations

import io
import json

import openpyxl

from app.database import SessionLocal
from app.repositories.repositories import RepositoryBundle
from app.services.auth_service import Identity
from app.services.import_service import ImportService
from tests.conftest import csrf_token


def _identity(email: str) -> Identity:
    db = SessionLocal()
    u = RepositoryBundle(db).users.get_by_email(email)
    ident = Identity(user_id=u.id, email=u.email, full_name=u.full_name,
                     role_code=u.role_code, role_name=u.role.name if u.role else "")
    db.close()
    return ident


ADMIN = lambda: _identity("admin@internado360.demo")  # noqa: E731
UNI = lambda: _identity("coordinator@internado360.demo")  # noqa: E731


def _xlsx(sheet: str, headers: list, rows: list, *, macro=False) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_STUDENT_HEADERS = ["Código", "Nombre completo", "DNI/CE", "Correo", "Ciclo",
                    "Institución", "Sede", "Inicio", "Término"]


def _student_rows(n_from=1):
    return [
        [f"2026I{n_from}A", "Interno Importado A", f"9100000{n_from}",
         f"impA{n_from}@demo.upeu.edu.pe", "13", "MINSA",
         "Hospital Lima Este - Vitarte", "2026-01-01", "2026-12-31"],
        [f"2026I{n_from}B", "Interno Importado B", f"9200000{n_from}",
         f"impB{n_from}@demo.upeu.edu.pe", "14", "MINSA",
         "Hospital Lima Este - Vitarte", "2026-01-01", "2026-12-31"],
    ]


def _run(ident, profile, raw, mode, *, sheet=None, mapping=None, confirm=True):
    """Drive a full import via the service; return the batch."""
    db = SessionLocal()
    svc = ImportService(db, ident)
    ct = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    batch = svc.create_batch(profile, "data.xlsx", ct, raw)
    sheet = sheet or svc.sheets(batch)[0]
    svc.set_sheet(batch.id, sheet)
    b = svc.repos.import_batches.get(batch.id)
    m = mapping or json.loads(b.mapping_json)
    svc.set_mapping(batch.id, m, mode)
    svc.validate_batch(batch.id)
    if confirm:
        svc.confirm_batch(batch.id)
    out = svc.repos.import_batches.get(batch.id)
    db.close()
    return out


# --- File validation ---------------------------------------------------------
def test_valid_xlsx_accepted():
    b = _run(ADMIN(), "students", _xlsx("Alumnos", _STUDENT_HEADERS, _student_rows(3)),
             "create_only")
    assert b.created_count == 2 and b.status in ("confirmed", "partial")


def test_valid_xlsm_accepted():
    # openpyxl can't easily write .xlsm; simulate the upload validation directly.
    from app.services import excel_reader
    raw = _xlsx("Alumnos", _STUDENT_HEADERS, _student_rows(4))
    ext = excel_reader.validate_upload("datos.xlsm",
                                       "application/vnd.ms-excel.sheet.macroEnabled.12", raw)
    assert ext == "xlsm"


def test_invalid_extension_rejected():
    from app.services import excel_reader
    from app.services.validators import ValidationError
    try:
        excel_reader.validate_upload("datos.xls", "application/vnd.ms-excel", b"PK\x03\x04junk")
        assert False, "should reject .xls"
    except ValidationError as e:
        assert "file" in e.errors


def test_corrupt_workbook_rejected():
    from app.services import excel_reader
    from app.services.validators import ValidationError
    corrupt = b"PK\x03\x04" + b"not a real workbook"
    try:
        excel_reader.load_workbook(corrupt)
        assert False, "should reject corrupt workbook"
    except ValidationError as e:
        assert "file" in e.errors


# --- Sheet / header / mapping ------------------------------------------------
def test_sheet_selection_and_header_detection():
    db = SessionLocal()
    svc = ImportService(db, ADMIN())
    raw = _xlsx("MiHoja", _STUDENT_HEADERS, _student_rows(5))
    batch = svc.create_batch("students", "d.xlsx",
                             "application/zip", raw)
    assert svc.sheets(batch) == ["MiHoja"]
    svc.set_sheet(batch.id, "MiHoja")
    b = svc.repos.import_batches.get(batch.id)
    mapping = json.loads(b.mapping_json)
    # Auto-mapping detected the key columns.
    assert mapping.get("student_code") == "Código"
    assert mapping.get("full_name") == "Nombre completo"
    db.close()


# --- Student import + duplicates ---------------------------------------------
def test_student_import_creates_records():
    db = SessionLocal()
    before = len(RepositoryBundle(db).students.search())
    db.close()
    _run(ADMIN(), "students", _xlsx("Alumnos", _STUDENT_HEADERS, _student_rows(6)), "create_only")
    db = SessionLocal()
    after = len(RepositoryBundle(db).students.search())
    db.close()
    assert after == before + 2


def test_duplicate_student_create_only_errors():
    raw = _xlsx("Alumnos", _STUDENT_HEADERS, _student_rows(7))
    _run(ADMIN(), "students", raw, "create_only")           # first import creates
    b = _run(ADMIN(), "students", raw, "create_only")       # second: duplicates
    assert b.error_rows == 2 and b.created_count == 0


def test_duplicate_student_skip_duplicates():
    raw = _xlsx("Alumnos", _STUDENT_HEADERS, _student_rows(8))
    _run(ADMIN(), "students", raw, "create_only")
    b = _run(ADMIN(), "students", raw, "skip_duplicates")
    assert b.skipped_count == 2 and b.created_count == 0


def test_reimport_idempotency():
    raw = _xlsx("Alumnos", _STUDENT_HEADERS, _student_rows(9))
    b1 = _run(ADMIN(), "students", raw, "create_only")
    b2 = _run(ADMIN(), "students", raw, "skip_duplicates")
    # No new students created on the second run.
    assert b1.created_count == 2 and b2.created_count == 0


# --- Modes -------------------------------------------------------------------
def test_valid_rows_only_mode():
    rows = _student_rows(10)
    rows.append(["", "Sin codigo", "93000010", "bad@d.com", "13", "MINSA",
                 "Hospital Lima Este - Vitarte", "", ""])  # invalid: no code
    b = _run(ADMIN(), "students", _xlsx("Alumnos", _STUDENT_HEADERS, rows), "valid_only")
    assert b.created_count == 2 and b.failed_count == 1 and b.status == "partial"


def test_all_or_nothing_rollback():
    from app.services.validators import ValidationError
    rows = _student_rows(11)
    rows.append(["", "Sin codigo", "93000011", "bad2@d.com", "13", "MINSA",
                 "Hospital Lima Este - Vitarte", "", ""])
    db = SessionLocal()
    before = len(RepositoryBundle(db).students.search())
    db.close()
    raised = False
    try:
        _run(ADMIN(), "students", _xlsx("Alumnos", _STUDENT_HEADERS, rows), "all_or_nothing")
    except ValidationError:
        raised = True
    db = SessionLocal()
    after = len(RepositoryBundle(db).students.search())
    db.close()
    assert raised and after == before  # nothing written


# --- Sede / tutor lookup -----------------------------------------------------
def test_sede_and_institution_lookup_resolves():
    raw = _xlsx("Alumnos", _STUDENT_HEADERS, _student_rows(12))
    b = _run(ADMIN(), "students", raw, "create_only")
    db = SessionLocal()
    st = RepositoryBundle(db).students.get_by_code("2026I12A")
    ok = st is not None and st.sede_id is not None and st.institution_type_id is not None
    db.close()
    assert ok


# --- Rotation conflict handling ---------------------------------------------
def test_rotation_conflict_flagged():
    db = SessionLocal()
    r = RepositoryBundle(db)
    student = r.students.search()[0]
    rt = r.rotation_types.list()[0]
    sede = r.sedes.active()[0]
    period = r.periods.current()
    db.close()
    headers = ["Código interno", "Rotación", "Sede", "Periodo", "Inicio", "Término", "Estado"]
    # Two identical core rotations for the same student/period → duplicate-core conflict.
    rows = [
        [student.student_code, rt.name, sede.name, period.name, "2026-03-01", "2026-04-30", "planned"],
        [student.student_code, rt.name, sede.name, period.name, "2026-03-01", "2026-04-30", "planned"],
    ]
    b = _run(ADMIN(), "rotations", _xlsx("Rot", headers, rows), "valid_only", confirm=False)
    # At least one row carries a conflict message.
    db = SessionLocal()
    msgs = [json.loads(row.messages_json or "[]")
            for row in RepositoryBundle(db).import_rows.for_batch(b.id)]
    db.close()
    assert any(m for group in msgs for m in group)


# --- Error report ------------------------------------------------------------
def test_error_report_generation():
    rows = _student_rows(13)
    rows.append(["", "Sin codigo", "93000013", "e@d.com", "13", "MINSA",
                 "Hospital Lima Este - Vitarte", "", ""])
    b = _run(ADMIN(), "students", _xlsx("Alumnos", _STUDENT_HEADERS, rows), "valid_only")
    db = SessionLocal()
    svc = ImportService(db, ADMIN())
    content = svc.error_report(svc.repos.import_batches.get(b.id))
    db.close()
    assert content[:2] == b"PK"  # a real xlsx


# --- Audit -------------------------------------------------------------------
def test_import_is_audited():
    _run(ADMIN(), "students", _xlsx("Alumnos", _STUDENT_HEADERS, _student_rows(14)), "create_only")
    db = SessionLocal()
    actions = {l.action for l in RepositoryBundle(db).audit_logs.recent(limit=80)}
    db.close()
    assert {"upload_import_file", "create_import_batch", "validate_import_batch",
            "confirm_import_batch"}.issubset(actions)


# --- HTTP: RBAC + CSRF -------------------------------------------------------
def test_student_has_no_import_access(student_client):
    assert student_client.get("/imports", follow_redirects=False).status_code == 403
    assert student_client.get("/imports/new?profile=students",
                              follow_redirects=False).status_code == 403


def test_tutor_has_no_master_import_access(tutor_client):
    assert tutor_client.get("/imports/new?profile=students",
                            follow_redirects=False).status_code == 403


def test_csrf_required_on_upload(admin):
    # POST without a CSRF token is rejected.
    r = admin.post("/imports", data={"profile": "students"}, follow_redirects=False)
    assert r.status_code == 400


def test_full_wizard_via_http(admin):
    tok = csrf_token(admin, "/imports/new?profile=students")
    raw = _xlsx("Alumnos", _STUDENT_HEADERS, _student_rows(15))
    r = admin.post("/imports", data={"csrf_token": tok, "profile": "students"},
                   files={"file": ("d.xlsx", raw,
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                   follow_redirects=False)
    assert r.status_code == 303
    bid = int(r.headers["location"].split("/")[2])
    admin.post(f"/imports/{bid}/sheet", data={"csrf_token": tok, "sheet_name": "Alumnos"})
    # auto-mapping is stored; submit the map form with the detected mapping.
    db = SessionLocal()
    mapping = json.loads(RepositoryBundle(db).import_batches.get(bid).mapping_json)
    db.close()
    form = {"csrf_token": tok, "mode": "create_only"}
    for target, header in mapping.items():
        form[f"map_{target}"] = header
    admin.post(f"/imports/{bid}/map", data=form)
    db = SessionLocal()
    b = RepositoryBundle(db).import_batches.get(bid)
    ch = b.content_hash
    db.close()
    admin.post(f"/imports/{bid}/confirm", data={"csrf_token": tok, "content_hash": ch})
    db = SessionLocal()
    b = RepositoryBundle(db).import_batches.get(bid)
    db.close()
    assert b.status in ("confirmed", "partial") and b.created_count == 2
