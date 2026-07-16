"""Reports & exports routes (Batch 2E). Thin controllers.

Role scope is applied inside ``ReportService`` before any data is gathered.
Every export (Excel/PDF) and every on-screen generation is audited. A Student
may only download their own internship summary.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.authorization import ensure
from app.database import get_db
from app.dependencies import Identity, require_identity
from app.models.user import ROLE_STUDENT
from app.services import audit_service as audit
from app.services.audit_service import client_ip
from app.services.export_service import excel_from_table, pdf_from_table
from app.services.report_service import ReportService
from app.templating import render
from app.web import flash

router = APIRouter(tags=["reports"])


@router.get("/reports")
def reports_index(request: Request, identity: Identity = Depends(require_identity),
                  db: Session = Depends(get_db)):
    svc = ReportService(db, identity)
    students = svc.scoped_students() if identity.role_code != ROLE_STUDENT else svc.scoped_students()
    return render(request, "pages/reports_index.html", identity=identity,
                  page_title="Reportes", page_subtitle="Reportes académicos y de gestión con exportación.",
                  page_icon="bar-chart", reports=svc.available_reports(), students=students,
                  is_student=identity.role_code == ROLE_STUDENT)


@router.get("/reports/view/{key}")
def report_view(key: str, request: Request, identity: Identity = Depends(require_identity),
                db: Session = Depends(get_db)):
    svc = ReportService(db, identity)
    ensure(svc.can_access(key), "No tiene permiso para este reporte.", "report_access_denied")
    result = svc.build(key)
    from app.services.audit_service import AuditService
    AuditService(db).record(audit.GENERATE_REPORT, identity=identity, entity_type="report",
                            detail={"report": key}, ip_address=client_ip(request))
    return render(request, "pages/report_view.html", identity=identity,
                  page_title=result.title, page_subtitle="Vista en pantalla · exportable a Excel/PDF.",
                  page_icon="bar-chart", result=result, meta=svc.meta(), key=key)


@router.get("/reports/export/{key}.{fmt}")
def report_export(key: str, fmt: str, request: Request,
                  identity: Identity = Depends(require_identity),
                  db: Session = Depends(get_db)):
    svc = ReportService(db, identity)
    ensure(svc.can_access(key), "No tiene permiso para este reporte.", "report_access_denied")
    result = svc.build(key)
    meta = svc.meta()
    from app.services.audit_service import AuditService
    if fmt == "xlsx":
        content = excel_from_table(title=result.title, headers=result.headers,
                                   rows=result.rows, meta=meta)
        AuditService(db).record(audit.EXPORT_REPORT_EXCEL, identity=identity, entity_type="report",
                                detail={"report": key}, ip_address=client_ip(request))
        return Response(content=content,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{key}.xlsx"'})
    if fmt == "pdf":
        content = pdf_from_table(title=result.title, headers=result.headers,
                                 rows=result.rows, meta=meta)
        AuditService(db).record(audit.EXPORT_REPORT_PDF, identity=identity, entity_type="report",
                                detail={"report": key}, ip_address=client_ip(request))
        return Response(content=content, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{key}.pdf"'})
    ensure(False, "Formato no soportado.", "report_format_invalid")


# --- Student internship summary --------------------------------------------
@router.get("/reports/student/{student_id}")
def student_summary(student_id: int, request: Request,
                    identity: Identity = Depends(require_identity),
                    db: Session = Depends(get_db)):
    svc = ReportService(db, identity)
    data = svc.build_student_summary(student_id)
    ensure(bool(data), "No tiene permiso para ver este resumen.", "student_summary_denied")
    from app.services.audit_service import AuditService
    AuditService(db).record(audit.GENERATE_STUDENT_SUMMARY, identity=identity,
                            entity_type="student", entity_id=student_id,
                            ip_address=client_ip(request))
    return render(request, "pages/student_summary.html", identity=identity,
                  page_title=f"Resumen de internado · {data['student'].full_name}",
                  page_subtitle="Registro consolidado del internado.",
                  page_icon="person-vcard", meta=svc.meta(), **data)


@router.get("/reports/student/{student_id}/export.{fmt}")
def student_summary_export(student_id: int, fmt: str, request: Request,
                           identity: Identity = Depends(require_identity),
                           db: Session = Depends(get_db)):
    svc = ReportService(db, identity)
    data = svc.build_student_summary(student_id)
    ensure(bool(data), "No tiene permiso para exportar este resumen.", "student_summary_denied")
    tables = svc.student_summary_tables(data)
    meta = svc.meta({"Interno": data["student"].full_name})
    from app.services.audit_service import AuditService
    if fmt == "xlsx":
        # One combined sheet: sections stacked with headers.
        headers = ["Sección", "Detalle 1", "Detalle 2", "Detalle 3", "Detalle 4"]
        rows: list[list] = []
        for section, cols, data_rows in tables:
            rows.append([section] + cols[:4] + [""] * (4 - len(cols[:4])))
            for r in data_rows:
                rows.append([""] + [str(c) for c in r][:4] + [""] * (4 - len(r[:4])))
            rows.append([""] * 5)
        content = excel_from_table(title=f"Resumen de internado — {data['student'].full_name}",
                                   headers=headers, rows=rows, meta=meta)
        AuditService(db).record(audit.EXPORT_REPORT_EXCEL, identity=identity, entity_type="student",
                                entity_id=student_id, detail={"report": "student_summary"},
                                ip_address=client_ip(request))
        return Response(content=content,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="resumen_{student_id}.xlsx"'})
    if fmt == "pdf":
        # Render each section as a small table concatenated in one PDF.
        from app.services.export_service import _ReportPDF, _latin1, _mc
        pdf = _ReportPDF(orientation="P", unit="mm", format="A4")
        pdf.alias_nb_pages(); pdf.set_auto_page_break(auto=True, margin=15); pdf.add_page()
        pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(31, 59, 87)
        _mc(pdf, 8, _latin1(f"Resumen de internado — {data['student'].full_name}"))
        pdf.set_text_color(0); pdf.set_font("Helvetica", "", 9)
        for k, v in meta.items():
            _mc(pdf, 5, _latin1(f"{k}: {v}"))
        pdf.ln(2)
        epw = pdf.w - pdf.l_margin - pdf.r_margin
        for section, cols, data_rows in tables:
            pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(31, 59, 87)
            _mc(pdf, 7, _latin1(section)); pdf.set_text_color(0)
            cw = epw / max(len(cols), 1)
            pdf.set_font("Helvetica", "B", 8); pdf.set_fill_color(31, 59, 87); pdf.set_text_color(255)
            for c in cols:
                pdf.cell(cw, 6, _latin1(str(c))[:32], border=1, align="C", fill=True)
            pdf.ln(); pdf.set_text_color(0); pdf.set_font("Helvetica", "", 8)
            if not data_rows:
                pdf.cell(0, 6, _latin1("Sin datos."), border=0); pdf.ln()
            for r in data_rows:
                for i in range(len(cols)):
                    val = r[i] if i < len(r) else ""
                    pdf.cell(cw, 6, _latin1(str(val))[:32], border=1)
                pdf.ln()
            pdf.ln(3)
        content = bytes(pdf.output())
        AuditService(db).record(audit.EXPORT_REPORT_PDF, identity=identity, entity_type="student",
                                entity_id=student_id, detail={"report": "student_summary"},
                                ip_address=client_ip(request))
        return Response(content=content, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="resumen_{student_id}.pdf"'})
    ensure(False, "Formato no soportado.", "report_format_invalid")
