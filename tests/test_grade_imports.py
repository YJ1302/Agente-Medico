"""Academic grade import tests (Batch 2F)."""

from __future__ import annotations

import io
import json

import openpyxl

from app.database import SessionLocal
from app.models.base import GradeComponentStatus
from app.models.grades import GradeComponentDefinition, GradeScheme
from app.repositories.repositories import RepositoryBundle
from app.services.auth_service import Identity
from app.services.grade_service import GradeService
from app.services.import_service import ImportService

_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _uni() -> Identity:
    db = SessionLocal()
    u = RepositoryBundle(db).users.get_by_email("coordinator@internado360.demo")
    ident = Identity(user_id=u.id, email=u.email, full_name=u.full_name,
                     role_code=u.role_code, role_name=u.role.name if u.role else "")
    db.close()
    return ident


_counter = [0]


def _make_scheme(required_portfolio=False):
    """Create a fresh scheme with 3 components (null weights). Returns ids."""
    _counter[0] += 1
    n = _counter[0]
    db = SessionLocal()
    r = RepositoryBundle(db)
    scheme = GradeScheme(code=f"GS-T{n}", name=f"Esquema Test {n}", version=1,
                         status="active", weights_confirmed=False)
    r.grade_schemes.add(scheme)
    db.flush()
    c1 = GradeComponentDefinition(scheme_id=scheme.id, name="Actitudinal",
                                  category="actitudinal", is_required=True, display_order=1)
    c2 = GradeComponentDefinition(scheme_id=scheme.id, name="Examen escrito",
                                  category="examen_escrito", is_required=True, display_order=2)
    c3 = GradeComponentDefinition(scheme_id=scheme.id, name="Portafolio",
                                  category="portafolio", is_required=required_portfolio,
                                  display_order=3)
    for c in (c1, c2, c3):
        r.grade_components.add(c)
    db.commit()
    ids = (scheme.id, c1.id, c2.id, c3.id)
    db.close()
    return ids


def _xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "QX 2026"
    ws.append(["DNI/CE", "Actitudinal", "Examen escrito", "Portafolio"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _run_grade(scheme_id, cids, rows, mode="create_only", confirm=True):
    db = SessionLocal()
    svc = ImportService(db, _uni())
    batch = svc.create_batch("grade_components", "notas.xlsx", _CT, raw=_xlsx(rows),
                             scheme_id=scheme_id)
    svc.set_sheet(batch.id, "QX 2026")
    mapping = {"student_key": "DNI/CE", f"comp_{cids[0]}": "Actitudinal",
               f"comp_{cids[1]}": "Examen escrito", f"comp_{cids[2]}": "Portafolio",
               "_scheme_id": str(scheme_id)}
    svc.set_mapping(batch.id, mapping, mode)
    svc.validate_batch(batch.id)
    if confirm:
        svc.confirm_batch(batch.id)
    b = svc.repos.import_batches.get(batch.id)
    rows_out = [{"status": row.status, "messages": json.loads(row.messages_json or "[]")}
                for row in svc.repos.import_rows.for_batch(batch.id)]
    db.close()
    return b, rows_out


def _codes(n=2):
    db = SessionLocal()
    codes = [s.student_code for s in RepositoryBundle(db).students.search()[:n]]
    db.close()
    return codes


def _cell(scheme_id, student_code, component_id):
    db = SessionLocal()
    r = RepositoryBundle(db)
    st = r.students.get_by_code(student_code)
    sgc = r.student_grades.get_one(st.id, scheme_id, component_id) if st else None
    db.close()
    return sgc


# --- Blank vs zero -----------------------------------------------------------
def test_blank_preserved_as_null():
    sid, *cids = _make_scheme()
    code = _codes(1)[0]
    _run_grade(sid, cids, [[code, 12, 14, None]])  # portfolio blank
    sgc = _cell(sid, code, cids[2])
    assert sgc is not None and sgc.score is None


def test_zero_preserved_as_zero():
    sid, *cids = _make_scheme()
    code = _codes(1)[0]
    _run_grade(sid, cids, [[code, 0, 14, 10]])  # actitudinal = 0
    sgc = _cell(sid, code, cids[0])
    assert sgc is not None and sgc.score == 0.0


# --- Validation --------------------------------------------------------------
def test_score_outside_range_rejected():
    sid, *cids = _make_scheme()
    code = _codes(1)[0]
    b, rows = _run_grade(sid, cids, [[code, 25, 14, 10]], confirm=False)  # 25 > 20
    assert rows[0]["status"] == "error"
    assert any("rango" in m["message"].lower() for m in rows[0]["messages"])


def test_student_not_found_flagged():
    sid, *cids = _make_scheme()
    b, rows = _run_grade(sid, cids, [["0000000", 10, 10, 10]], confirm=False)
    assert rows[0]["status"] == "error"
    assert any("interno" in m["message"].lower() for m in rows[0]["messages"])


def test_duplicate_student_flagged():
    sid, *cids = _make_scheme()
    code = _codes(1)[0]
    b, rows = _run_grade(sid, cids, [[code, 10, 10, 10], [code, 11, 11, 11]], confirm=False)
    # The second appearance carries a duplicate warning.
    assert any(m["level"] == "warning" and "más de una vez" in m["message"]
               for m in rows[1]["messages"])


# --- Approved not overwritten silently --------------------------------------
def test_existing_approved_grade_not_overwritten_silently():
    sid, *cids = _make_scheme()
    code = _codes(1)[0]
    _run_grade(sid, cids, [[code, 10, 12, 8]])  # creates imported values
    # Approve the Actitudinal component.
    sgc = _cell(sid, code, cids[0])
    db = SessionLocal()
    GradeService(db, _uni()).approve_component(sgc.id)
    db.close()
    # Re-import with a DIFFERENT value in create_only mode → flagged as warning.
    b, rows = _run_grade(sid, cids, [[code, 18, 12, 8]], mode="create_only", confirm=False)
    assert any("aprobada" in m["message"].lower() for m in rows[0]["messages"])
    # History exists for the approved component (approval recorded).
    db = SessionLocal()
    hist = RepositoryBundle(db).grade_history.for_component(sgc.id)
    db.close()
    assert any(h.action == "approve" for h in hist)


def test_confirmed_update_records_history_and_reflags():
    sid, *cids = _make_scheme()
    code = _codes(1)[0]
    _run_grade(sid, cids, [[code, 10, 12, 8]])
    sgc = _cell(sid, code, cids[0])
    db = SessionLocal()
    GradeService(db, _uni()).approve_component(sgc.id)
    db.close()
    # An update-mode confirmed import changes the value but records history and
    # drops the status back to 'imported' (not a silent overwrite).
    _run_grade(sid, cids, [[code, 19, 12, 8]], mode="valid_only")
    updated = _cell(sid, code, cids[0])
    assert updated.score == 19.0
    assert updated.status == GradeComponentStatus.IMPORTED.value
    db = SessionLocal()
    hist = RepositoryBundle(db).grade_history.for_component(sgc.id)
    db.close()
    assert any(h.action == "import_updated" for h in hist)


# --- No final grade without weights -----------------------------------------
def test_final_grade_not_calculated_without_weights():
    sid, *cids = _make_scheme()
    db = SessionLocal()
    svc = GradeService(db, _uni())
    scheme = svc.get_scheme(sid)
    note = svc.final_grade_note(scheme)
    db.close()
    assert note == "Fórmula pendiente de confirmación"


# --- Source preserved --------------------------------------------------------
def test_source_sheet_and_status_preserved():
    sid, *cids = _make_scheme()
    code = _codes(1)[0]
    _run_grade(sid, cids, [[code, 10, 12, 8]])
    sgc = _cell(sid, code, cids[0])
    assert sgc.source_sheet == "QX 2026"
    assert sgc.source_type == "import"
    assert sgc.status == GradeComponentStatus.IMPORTED.value
    assert sgc.source_batch_id is not None
