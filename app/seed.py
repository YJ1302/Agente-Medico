"""Seed script — populates the database with FICTIONAL demonstration data.

Run with:
    python -m app.seed

IMPORTANT (privacy): every name, code and contact here is invented for the
demo. No real student or patient data from the reference documents is used
(SECURITY_AND_PRIVACY_RULES.md). The script is idempotent-ish: it drops and
recreates all tables so repeated runs give a clean, predictable demo dataset.

The seeded scenario deliberately produces the alerts required by the spec:
  * a rotation ending within 7 days,
  * a rotation assignment without a tutor,
  * a pending evaluation,
  * an incomplete student profile.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.database import Base, SessionLocal, engine
from app.logging_config import get_logger
from app.data.activity_catalog import build_catalog
from app.models.academic import AcademicPeriod, RotationAssignment, RotationType
from app.models.activity import (
    ActivityDefinition,
    ActivityReview,
    StudentActivity,
    TARGET_FIXED,
)
from app.models.base import (
    AlertSeverity,
    AlertStatus,
    AssignmentStatus,
    DocumentStatus,
    EvaluationStatus,
    IncidentSeverity,
    IncidentStatus,
    utcnow,
)
from app.models.evaluation import (
    AREA_ATTITUDE,
    AREA_KNOWLEDGE,
    AREA_PERFORMANCE,
    Evaluation,
    EvaluationCriterion,
)
from app.models.base import (
    DocumentPriority,
    GradeComponentStatus,
    GradeSchemeStatus,
    ImportMode,
    ImportStatus,
    VisibilityLevel,
)
from app.models.grades import (
    GradeComponentDefinition,
    GradeComponentHistory,
    GradeScheme,
    StudentGradeComponent,
)
from app.models.imports import ImportBatch, ImportRow
from app.models.operations import (
    ALERT_INCOMPLETE_PROFILE,
    ALERT_MISSING_TUTOR,
    ALERT_PENDING_EVALUATION,
    ALERT_ROTATION_ENDING,
    OWNER_DOCUMENT,
    OWNER_INCIDENT,
    Alert,
    DocumentRecord,
    DocumentSequence,
    DocumentTemplate,
    Incident,
    StatusHistory,
)
from app.models.organization import (
    InstitutionType,
    Sede,
    SedeCoordinatorProfile,
    TutorProfile,
)
from app.models.student import Student
from app.models.user import (
    ROLE_ADMIN,
    ROLE_SEDE_COORDINATOR,
    ROLE_STUDENT,
    ROLE_TUTOR,
    ROLE_UNIVERSITY_COORDINATOR,
    Role,
    User,
)
from app.security import hash_password

logger = get_logger("seed")

DEMO_PASSWORD = "Demo123!"
TODAY = date.today()

# The exact 15 evaluation criteria from 'FORMATO DE EVALUACION INTERNO'.
EVAL_CRITERIA = {
    AREA_KNOWLEDGE: [
        "Explica la fisiopatología de los hallazgos clínicos según conocimientos científicos actuales",
        "Explica el fundamento de las medidas terapéuticas según conocimientos científicos actuales",
        "Participa activamente en sesiones académicas programadas",
        "Expone guías clínicas actualizadas sobre el manejo de las patologías",
        "Expone de forma clara y coherente artículos de revistas en relación a temas designados",
    ],
    AREA_PERFORMANCE: [
        "Elabora historias clínicas según las normas de la institución de salud",
        "Reporta clara y oportunamente los datos del paciente que se le solicita",
        "Propone exámenes auxiliares y tratamiento según guías clínicas",
        "Enumera posibles complicaciones y propone medidas preventivas",
        "Usa las normas de bioseguridad de la institución",
    ],
    AREA_ATTITUDE: [
        "Evidencia pulcritud, esmero y limpieza",
        "Cumple con el horario establecido y asiste puntualmente a las actividades programadas",
        "Establece una relación médico-paciente con empatía y respeto",
        "Trabaja de manera responsable y respetuosa con el equipo multidisciplinario de salud",
        "Manifiesta iniciativa y deseos de superación en su trabajo",
    ],
}


def _reset_schema() -> None:
    """DESTRUCTIVE: drop and recreate every table. Demo-reset only."""
    logger.warning("Dropping and recreating all tables (demo reset)…")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _ensure_schema() -> None:
    """Non-destructive: create any missing tables without dropping data."""
    Base.metadata.create_all(bind=engine)


def _already_seeded(db) -> bool:
    return db.query(User).count() > 0


def seed(reset: bool = False) -> None:  # noqa: C901 - linear seed reads clearer flat
    """Populate demo data.

    * ``reset=False`` (default, safe): create any missing tables and seed **only
      if the database is empty**. An already-seeded database is left untouched;
      the caller is told to use ``--reset`` to rebuild it. This is what runs
      after ``alembic upgrade head`` and never silently destroys data.
    * ``reset=True``: drop and recreate all tables, then seed (demo reset).
    """
    if reset:
        _reset_schema()
    else:
        _ensure_schema()

    db = SessionLocal()
    if not reset and _already_seeded(db):
        logger.warning(
            "Database already contains data — skipping seed. "
            "Use 'python -m app.seed --reset' to rebuild demo data."
        )
        db.close()
        return
    try:
        # -- Roles --------------------------------------------------------
        roles = {
            ROLE_ADMIN: Role(code=ROLE_ADMIN, name="Administrador",
                             description="Administrador de la plataforma.", hierarchy_level=1),
            ROLE_UNIVERSITY_COORDINATOR: Role(
                code=ROLE_UNIVERSITY_COORDINATOR, name="Coordinador Universitario",
                description="Coordinador de Internado de la Escuela de Medicina.", hierarchy_level=2),
            ROLE_SEDE_COORDINATOR: Role(
                code=ROLE_SEDE_COORDINATOR, name="Coordinador de Sede",
                description="Docente coordinador de la sede hospitalaria.", hierarchy_level=3),
            ROLE_TUTOR: Role(code=ROLE_TUTOR, name="Tutor",
                             description="Tutor de rotación.", hierarchy_level=4),
            ROLE_STUDENT: Role(code=ROLE_STUDENT, name="Interno",
                               description="Interno de medicina.", hierarchy_level=5),
        }
        db.add_all(roles.values())
        db.flush()

        # -- Demo login accounts (one per role) --------------------------
        pwd = hash_password(DEMO_PASSWORD)
        admin = User(email="admin@internado360.demo", hashed_password=pwd,
                     full_name="Ana Administradora", role_id=roles[ROLE_ADMIN].id)
        uni_coord = User(email="coordinator@internado360.demo", hashed_password=pwd,
                         full_name="Dr. Carlos Coordinador", role_id=roles[ROLE_UNIVERSITY_COORDINATOR].id)
        db.add_all([admin, uni_coord])
        db.flush()

        # -- Institution types -------------------------------------------
        minsa = InstitutionType(code="MINSA", name="Ministerio de Salud (MINSA)",
                                placement_method="ranking", has_community_component=True,
                                description="Incluye componente comunitario en centros de salud.")
        essalud = InstitutionType(code="ESSALUD", name="Seguro Social de Salud (EsSalud)",
                                  placement_method="examen", has_community_component=False,
                                  description="Asignación por resultados de examen.")
        db.add_all([minsa, essalud])
        db.flush()

        # -- Sedes (fictional but realistic teaching sites) --------------
        sedes = [
            Sede(name="Hospital Lima Este - Vitarte", short_name="H. Vitarte",
                 sede_type="hospital", city="Lima", institution_type_id=minsa.id),
            Sede(name="Hospital Nacional Hipólito Unanue", short_name="H. Unanue",
                 sede_type="hospital", city="Lima", institution_type_id=minsa.id),
            Sede(name="Centro Materno Infantil Miguel Grau", short_name="C.M.I. Miguel Grau",
                 sede_type="health_center", city="Lima", institution_type_id=minsa.id),
            Sede(name="Hospital II EsSalud Chosica", short_name="H. Chosica (EsSalud)",
                 sede_type="hospital", city="Lima", institution_type_id=essalud.id),
            # 5th sede: intentionally WITHOUT a coordinator and WITHOUT rotations
            # (demonstrates the "missing coordinator" and normal-deactivation cases).
            Sede(name="Centro de Salud Santa Rosa", short_name="C.S. Santa Rosa",
                 sede_type="health_center", city="Lima", institution_type_id=minsa.id),
        ]
        db.add_all(sedes)
        db.flush()

        # -- Sede coordinators (4 of the 5 sedes; the 5th has none) -------
        coord_names = ["Dra. Rosa Medina", "Dr. Julio Ramírez",
                       "Dra. Digna Paredes", "Dr. Hayder Torres"]
        sede_coords = []
        for i, (sede, name) in enumerate(zip(sedes, coord_names)):  # zip stops at 4
            u = User(email=f"sede{i+1}@internado360.demo" if i > 0 else "sede@internado360.demo",
                     hashed_password=pwd, full_name=name, role_id=roles[ROLE_SEDE_COORDINATOR].id)
            db.add(u); db.flush()
            sc = SedeCoordinatorProfile(user_id=u.id, sede_id=sede.id, is_principal=True,
                                        specialty="Medicina Interna", office_phone=f"98{i}0000000")
            db.add(sc); sede_coords.append(sc)
        db.flush()

        # -- Rotation types (4 core) -------------------------------------
        rt_medicina = RotationType(name="Medicina Interna", code="MED", typical_weeks=8)
        rt_cirugia = RotationType(name="Cirugía General", code="CIR", typical_weeks=8)
        rt_pediatria = RotationType(name="Pediatría", code="PED", typical_weeks=8)
        rt_gineco = RotationType(name="Gineco-Obstetricia", code="GO", typical_weeks=8)
        rt_comunidad = RotationType(name="Componente Comunitario (MINSA)", code="COM",
                                    is_core=False, typical_weeks=4,
                                    description="Rotación comunitaria adicional para sedes MINSA.")
        rotation_types = [rt_medicina, rt_cirugia, rt_pediatria, rt_gineco, rt_comunidad]
        db.add_all(rotation_types)
        db.flush()

        # -- Academic periods (6 bimonthly blocks of the internship year) -
        year = TODAY.year
        period_defs = [
            ("Enero - Febrero", "ENE-FEB", 1, date(year, 1, 1), date(year, 2, 28)),
            ("Marzo - Abril", "MAR-ABR", 2, date(year, 3, 1), date(year, 4, 30)),
            ("Mayo - Junio", "MAY-JUN", 3, date(year, 5, 1), date(year, 6, 30)),
            ("Julio - Agosto", "JUL-AGO", 4, date(year, 7, 1), date(year, 8, 31)),
            ("Setiembre - Octubre", "SET-OCT", 5, date(year, 9, 1), date(year, 10, 31)),
            ("Noviembre - Diciembre", "NOV-DIC", 6, date(year, 11, 1), date(year, 12, 31)),
        ]
        periods = []
        for name, code, ordinal, start, end in period_defs:
            is_current = start <= TODAY <= end
            periods.append(AcademicPeriod(name=f"{name} {year}", code=f"{code}-{year}",
                                          year=year, ordinal=ordinal, start_date=start,
                                          end_date=end, is_current=is_current))
        # Guarantee exactly one current period even if 'today' falls in a gap.
        if not any(p.is_current for p in periods):
            _mark_nearest_current(periods)
        db.add_all(periods)
        db.flush()
        current_period = next(p for p in periods if p.is_current)

        # -- Tutors (8) --------------------------------------------------
        tutor_specs = [
            ("Dra. Lorena López", "Medicina Interna", sedes[0]),
            ("Dr. Julio Ramos", "Cirugía General", sedes[0]),
            ("Dra. Rocío Alcalá", "Pediatría", sedes[2]),
            ("Dra. Digna Pantigoso", "Gineco-Obstetricia", sedes[2]),
            ("Dr. Ronald Galdo", "Medicina Interna", sedes[1]),
            ("Dr. Martín Salas", "Cirugía General", sedes[1]),
            ("Dra. Elena Vargas", "Pediatría", sedes[3]),
            ("Dr. Óscar Ríos", "Gineco-Obstetricia", sedes[3]),
        ]
        tutors = []
        for i, (name, service, sede) in enumerate(tutor_specs):
            email = "tutor@internado360.demo" if i == 0 else f"tutor{i+1}@internado360.demo"
            u = User(email=email, hashed_password=pwd, full_name=name,
                     role_id=roles[ROLE_TUTOR].id)
            db.add(u); db.flush()
            tp = TutorProfile(user_id=u.id, sede_id=sede.id, service=service,
                              specialty=service, contact_phone=f"9{i}1234567")
            db.add(tp); tutors.append(tp)
        # One inactive tutor (demonstrates the inactive-tutor scenario).
        tutors[6].is_active = False
        tutors[6].user.is_active = False
        db.flush()

        # -- Students (12 fictional interns; mix of MINSA/EsSalud) --------
        student_names = [
            "Gabriela Vega Arana", "Marbella Turpo Quispe", "Mariely Huamán Espinoza",
            "Reina Chávez Jara", "Diego Salcedo Ponce", "Lucía Rojas Medina",
            "Kevin Paredes Soto", "Andrea Núñez Ríos", "Sofía Cárdenas Luna",
            "Bruno Mendoza Ávila", "Camila Fuentes Ríos", "Renato Aguilar Peña",
        ]
        # First demo student account.
        student_user = User(email="student@internado360.demo", hashed_password=pwd,
                            full_name=student_names[0], role_id=roles[ROLE_STUDENT].id)
        db.add(student_user); db.flush()

        students = []
        # Assign interns only across the first 4 sedes so the 5th sede
        # (C.S. Santa Rosa) stays empty — a clean "normal deactivation" demo.
        # Each intern's institution matches their sede's institution, so the only
        # institution mismatch in the dataset is the single controlled demo added
        # in the Batch 2B lifecycle block below.
        staffed_sedes = sedes[:4]
        for i, name in enumerate(student_names):
            sede = staffed_sedes[i % len(staffed_sedes)]
            inst = sede.institution_type  # keep interno/sede institution consistent
            # The last student has an intentionally incomplete profile (alert #4).
            profile_status = "incomplete" if i == len(student_names) - 1 else "complete"
            students.append(Student(
                user_id=student_user.id if i == 0 else None,
                student_code=f"2020{1000 + i}",
                full_name=name,
                document_id=f"7{i:07d}",  # fictional
                email=f"interno{i+1}@demo.upeu.edu.pe",
                cycle="13" if i % 2 == 0 else "14",
                institution_type_id=inst.id,
                sede_id=sede.id,
                internship_start=date(year, 1, 1),
                internship_end=date(year, 1, 1) + timedelta(days=365),
                profile_status=profile_status,
            ))
        db.add_all(students)
        db.flush()

        # -- Rotation assignments ----------------------------------------
        core_rotations = [rt_medicina, rt_cirugia, rt_pediatria, rt_gineco]
        assignments: list[RotationAssignment] = []

        # Several ACTIVE assignments in the current period (with tutors).
        for i, student in enumerate(students[:8]):
            rt = core_rotations[i % 4]
            tutor = tutors[i % len(tutors)]
            assignments.append(RotationAssignment(
                student_id=student.id, rotation_type_id=rt.id, sede_id=student.sede_id,
                period_id=current_period.id, tutor_id=tutor.id,
                start_date=current_period.start_date,
                end_date=current_period.end_date,
                status=AssignmentStatus.ACTIVE.value,
            ))

        # ALERT #1 — a rotation ending within 7 days.
        assignments.append(RotationAssignment(
            student_id=students[8].id, rotation_type_id=rt_medicina.id,
            sede_id=students[8].sede_id, period_id=current_period.id,
            tutor_id=tutors[0].id, start_date=TODAY - timedelta(days=50),
            end_date=TODAY + timedelta(days=4), status=AssignmentStatus.ACTIVE.value,
        ))

        # ALERT #2 — an active assignment WITHOUT a tutor.
        assignments.append(RotationAssignment(
            student_id=students[9].id, rotation_type_id=rt_cirugia.id,
            sede_id=students[9].sede_id, period_id=current_period.id,
            tutor_id=None, start_date=current_period.start_date,
            end_date=current_period.end_date, status=AssignmentStatus.ACTIVE.value,
        ))

        # Upcoming (PLANNED) rotations starting soon — "upcoming changes".
        next_period = _next_period(periods, current_period)
        for student in students[:3]:
            assignments.append(RotationAssignment(
                student_id=student.id, rotation_type_id=rt_pediatria.id,
                sede_id=student.sede_id, period_id=next_period.id,
                tutor_id=tutors[2].id, start_date=TODAY + timedelta(days=6),
                end_date=TODAY + timedelta(days=6 + 56),
                status=AssignmentStatus.PLANNED.value,
            ))

        # -- Workload demo (threshold default = 5) -----------------------
        # tutors[4] (Dr. Ronald Galdo, sede[1]) → NEAR the threshold (4 active).
        # tutors[5] (Dr. Martín Salas, sede[1]) → ABOVE the threshold (6 active).
        # These extra planned assignments reuse existing students at sede[1].
        sede1_students = [s for s in students if s.sede_id == sedes[1].id]
        _fill = sede1_students or students
        for n, (tutor_idx, target) in enumerate([(4, 4), (5, 6)]):
            for k in range(target):
                stu = _fill[(n + k) % len(_fill)]
                assignments.append(RotationAssignment(
                    student_id=stu.id, rotation_type_id=core_rotations[k % 4].id,
                    sede_id=sedes[1].id, period_id=next_period.id,
                    tutor_id=tutors[tutor_idx].id,
                    start_date=next_period.start_date, end_date=next_period.end_date,
                    status=AssignmentStatus.PLANNED.value,
                ))
        # -- Batch 2B lifecycle demo assignments -------------------------
        from app.models.base import utcnow as _utcnow
        first_period = periods[0]
        minsa_students = [s for s in students if s.institution_type_id == minsa.id]
        essalud_students = [s for s in students if s.institution_type_id == essalud.id]

        # A COMPLETED rotation (past period) — will get an auto pending evaluation.
        completed_assignment = RotationAssignment(
            student_id=minsa_students[0].id, rotation_type_id=rt_medicina.id,
            sede_id=minsa_students[0].sede_id, period_id=first_period.id,
            tutor_id=tutors[0].id, start_date=first_period.start_date,
            end_date=first_period.end_date, status=AssignmentStatus.COMPLETED.value,
            completed_at=_utcnow(), notes="Rotación finalizada (demo).")
        assignments.append(completed_assignment)

        # A CANCELLED rotation with a recorded reason.
        assignments.append(RotationAssignment(
            student_id=minsa_students[1].id, rotation_type_id=rt_cirugia.id,
            sede_id=minsa_students[1].sede_id, period_id=first_period.id,
            tutor_id=tutors[1].id, start_date=first_period.start_date,
            end_date=first_period.end_date, status=AssignmentStatus.CANCELLED.value,
            cancelled_at=_utcnow(),
            cancellation_reason="Reprogramación por disponibilidad de la sede (demo)."))

        # A MINSA COMMUNITY rotation (allowed for MINSA) in a distinct period.
        assignments.append(RotationAssignment(
            student_id=minsa_students[2].id, rotation_type_id=rt_comunidad.id,
            sede_id=minsa_students[2].sede_id, period_id=periods[4].id,
            tutor_id=None, start_date=periods[4].start_date,
            end_date=periods[4].start_date + timedelta(days=28),
            status=AssignmentStatus.PLANNED.value,
            notes="Componente comunitario MINSA (demo)."))

        # A controlled INSTITUTION-MISMATCH demo: an EsSalud interno placed at a
        # MINSA sede in a distinct period (the rules flag this for review).
        if essalud_students:
            assignments.append(RotationAssignment(
                student_id=essalud_students[0].id, rotation_type_id=rt_pediatria.id,
                sede_id=sedes[0].id, period_id=periods[5].id,
                tutor_id=None, start_date=periods[5].start_date,
                end_date=periods[5].end_date, status=AssignmentStatus.PLANNED.value,
                notes="Demostración de conflicto de institución (revisión)."))

        db.add_all(assignments)
        db.flush()

        # Auto pending evaluation for the completed rotation (as the app does).
        _completed_eval = Evaluation(
            assignment_id=completed_assignment.id, student_id=completed_assignment.student_id,
            tutor_id=completed_assignment.tutor_id, status=EvaluationStatus.PENDING.value)
        db.add(_completed_eval); db.flush()
        _add_criteria(db, _completed_eval)

        # ALERT #3 — one PENDING evaluation (for an active assignment).
        eval_assignment = assignments[0]
        evaluation = Evaluation(
            assignment_id=eval_assignment.id, student_id=eval_assignment.student_id,
            tutor_id=eval_assignment.tutor_id, status=EvaluationStatus.PENDING.value,
        )
        db.add(evaluation); db.flush()
        _add_criteria(db, evaluation)  # unscored criteria (pending)

        # One SUBMITTED evaluation with scores, to populate the evaluations table.
        submitted_assignment = assignments[1]
        submitted = Evaluation(
            assignment_id=submitted_assignment.id, student_id=submitted_assignment.student_id,
            tutor_id=submitted_assignment.tutor_id, status=EvaluationStatus.SUBMITTED.value,
            score_knowledge=18.0, score_performance=17.0, score_attitude=19.0,
            final_score=round((18.0 + 17.0 + 19.0) / 3, 2),
            comments="Buen desempeño general. Continuar reforzando la exposición de guías clínicas.",
            submitted_at=_utcnow(), submitted_by_user_id=tutors[1].user_id,
        )
        db.add(submitted); db.flush()
        _add_criteria(db, submitted, scored=True)

        # -- Batch 2D: an IN_PROGRESS evaluation (partially scored — only the
        # Conocimientos area has been filled in by the tutor so far). ----------
        in_progress_assignment = assignments[2]
        in_progress_eval = Evaluation(
            assignment_id=in_progress_assignment.id, student_id=in_progress_assignment.student_id,
            tutor_id=in_progress_assignment.tutor_id, status=EvaluationStatus.IN_PROGRESS.value,
        )
        db.add(in_progress_eval); db.flush()
        _add_scored_criteria(db, in_progress_eval, {
            AREA_KNOWLEDGE: [4, 4, 3, 4, 3], AREA_PERFORMANCE: [None] * 5,
            AREA_ATTITUDE: [None] * 5,
        })
        in_progress_eval.score_knowledge = 18.0  # only the completed area is cached

        # A RETURNED_FOR_CORRECTION evaluation: fully scored, submitted, then
        # sent back by the sede coordinator with a mandatory comment.
        coord_by_sede = {c.sede_id: c for c in sede_coords}
        returned_assignment = assignments[4]
        returned_coord = coord_by_sede.get(returned_assignment.sede_id, sede_coords[0])
        returned_eval = Evaluation(
            assignment_id=returned_assignment.id, student_id=returned_assignment.student_id,
            tutor_id=returned_assignment.tutor_id, status=EvaluationStatus.RETURNED_FOR_CORRECTION.value,
            comments="Evaluación inicial del interno.",
            submitted_at=_utcnow() - timedelta(days=2), submitted_by_user_id=tutors[4].user_id,
            reviewed_at=_utcnow() - timedelta(days=1),
            reviewed_by_user_id=returned_coord.user_id,
            review_comments="Verificar el puntaje de Actitudinal: parece no reflejar las "
                            "observaciones registradas durante la rotación. Revisar y reenviar.",
        )
        db.add(returned_eval); db.flush()
        scores = _add_scored_criteria(db, returned_eval, {
            AREA_KNOWLEDGE: [4, 4, 3, 4, 3], AREA_PERFORMANCE: [3, 4, 4, 3, 4],
            AREA_ATTITUDE: [4, 4, 4, 3, 4],
        })
        returned_eval.score_knowledge = float(scores[AREA_KNOWLEDGE])
        returned_eval.score_performance = float(scores[AREA_PERFORMANCE])
        returned_eval.score_attitude = float(scores[AREA_ATTITUDE])
        returned_eval.final_score = round(sum(scores.values()) / 3, 2)

        # An APPROVED evaluation: fully scored, submitted and approved by the
        # sede coordinator. Deliberately attached to the DEMO student's own
        # planned assignment (their other two assignments already carry the
        # pending evaluations above) so the demo/test account has a real
        # approved evaluation to view — "student sees only own approved eval".
        approved_assignment = next(
            a for a in assignments
            if a.student_id == students[0].id and a.status == AssignmentStatus.PLANNED.value
        )
        approved_tutor = approved_assignment.tutor_id or tutors[2].id
        approved_coord = coord_by_sede.get(approved_assignment.sede_id, sede_coords[0])
        approved_eval = Evaluation(
            assignment_id=approved_assignment.id, student_id=approved_assignment.student_id,
            tutor_id=approved_tutor, status=EvaluationStatus.APPROVED.value,
            comments="Interno responsable, con buen manejo clínico y disposición al aprendizaje.",
            submitted_at=_utcnow() - timedelta(days=5),
            submitted_by_user_id=next(t.user_id for t in tutors if t.id == approved_tutor),
            reviewed_at=_utcnow() - timedelta(days=4),
            reviewed_by_user_id=approved_coord.user_id,
            review_comments="Evaluación conforme. Aprobada.",
        )
        db.add(approved_eval); db.flush()
        scores2 = _add_scored_criteria(db, approved_eval, {
            AREA_KNOWLEDGE: [3, 3, 4, 3, 3], AREA_PERFORMANCE: [4, 3, 3, 4, 3],
            AREA_ATTITUDE: [4, 4, 3, 4, 4],
        })
        approved_eval.score_knowledge = float(scores2[AREA_KNOWLEDGE])
        approved_eval.score_performance = float(scores2[AREA_PERFORMANCE])
        approved_eval.score_attitude = float(scores2[AREA_ATTITUDE])
        approved_eval.final_score = round(sum(scores2.values()) / 3, 2)

        # -- Activity catalog (Batch 2C): the full official catalog extracted --
        # from the four "LISTA DE ACTIVIDADES" reference documents. See
        # docs/ACTIVITY_CATALOG_SOURCE_MAP.md for the source-to-row mapping.
        rotation_ids_by_code = {"MED": rt_medicina.id, "CIR": rt_cirugia.id,
                                "PED": rt_pediatria.id, "GO": rt_gineco.id}
        activity_defs: dict[str, ActivityDefinition] = {}
        for item in build_catalog():
            d = ActivityDefinition(
                code=item.code, name=item.name, category=item.category,
                description=item.description,
                rotation_type_id=rotation_ids_by_code.get(item.rotation_code) if item.rotation_code else None,
                target_type=item.target_type, target_count=item.target_count,
                unit_label=item.unit_label, requires_tutor_verification=item.requires_tutor_verification,
                evidence_policy=item.evidence_policy, supervision_required=item.supervision_required,
                source_document=item.source_document, source_year=item.source_year,
                source_section=item.source_section, is_provisional=item.is_provisional,
                display_order=item.display_order,
            )
            db.add(d)
            activity_defs[item.code] = d
        db.flush()

        # -- Student activity log demo scenarios (Batch 2C) ------------------
        def _log(assignment, code, qty, days_ago, status="verified", reviewer=None,
                 reject_comment=None, notes=None):
            # NOTE: never mutate the returned entry's attributes after this
            # function flushes it — TimestampMixin's onupdate=utcnow fires on
            # any later UPDATE and would silently overwrite the backdated
            # timestamps set here, breaking the old-pending/rejected demo rules.
            d = activity_defs[code]
            logged = TODAY - timedelta(days=days_ago)
            backdated = utcnow() - timedelta(days=days_ago)
            entry = StudentActivity(
                student_id=assignment.student_id, definition_id=d.id, assignment_id=assignment.id,
                performed_count=qty, logged_on=logged, verification_status=status,
                submitted_at=backdated, created_by_user_id=assignment.student.user_id,
                created_at=backdated, updated_at=backdated, notes=notes,
            )
            db.add(entry); db.flush()
            if status == "verified":
                db.add(ActivityReview(student_activity_id=entry.id, action="verified",
                                      reviewer_user_id=reviewer, created_at=backdated))
            elif status == "rejected":
                db.add(ActivityReview(student_activity_id=entry.id, action="rejected",
                                      reviewer_user_id=reviewer, comment=reject_comment,
                                      created_at=backdated))
            return entry

        tutor0_user = tutors[0].user_id
        tutor1_user = tutors[1].user_id
        tutor2_user = tutors[2].user_id

        # Student at ~20% progress (assignments[0]: Medicina, "Toma de muestra
        # Orina" MED-PROC-05, target 10 -> 2 verified = 20%).
        _log(assignments[0], "MED-PROC-05", 2, 15, "verified", tutor0_user)
        # Student near ~80% (assignments[1]: Cirugía, "Instalación de sonda
        # vesical" CIR-PROC-06, target 5 -> 4 verified = 80%).
        _log(assignments[1], "CIR-PROC-06", 4, 12, "verified", tutor1_user)
        # Student over 100% (assignments[2]: Pediatría, "Realiza otoscopia"
        # PED-PROC-16, target 5 -> 6 verified = 120%, true count kept visible).
        _log(assignments[2], "PED-PROC-16", 6, 10, "verified", tutor2_user)

        # Pending activities (awaiting tutor review; no-fixed-target items).
        _log(assignments[0], "MED-PROC-04", 1, 2, "pending")
        _log(assignments[3], "GO-PROC-05", 1, 1, "pending")

        # A rejected entry for the demo student account itself (assignments[0],
        # student@internado360.demo), so the reject/correct workflow is fully
        # demonstrable while logged in as the seeded demo student.
        _log(assignments[0], "MED-PROC-08", 2, 6, "rejected", tutor0_user,
             "La cantidad reportada no coincide con la referencia. Verifique y reenvíe.")

        # Rejected activity, then corrected + resubmitted — mirrors exactly what
        # StudentActivityService.update() does: the SAME row transitions
        # rejected -> pending (never a new row), and both the rejection and the
        # correction are preserved as separate ActivityReview history entries.
        corrected_entry = _log(assignments[1], "CIR-PROC-05", 1, 8, "rejected", tutor1_user,
                               "Cantidad no coincide con la referencia registrada. Verifique y reenvíe.",
                               notes="Registro inicial con inconsistencia (demo).")
        corrected_entry.verification_status = "pending"
        corrected_entry.performed_count = 1
        corrected_entry.notes = "Corregido tras observación del tutor (demo)."
        corrected_entry.submitted_at = utcnow() - timedelta(days=3)
        db.add(ActivityReview(student_activity_id=corrected_entry.id, action="corrected",
                              reviewer_user_id=assignments[1].student.user_id,
                              comment="Corregido y reenviado por el interno."))

        # Tutor verification backlog: several OLD pending entries for tutors[5]
        # (Dr. Martín Salas — already above the workload threshold) using every
        # assignment supervised by that tutor. Two entries per assignment push
        # the count safely above tutor_verification_backlog_threshold (8).
        backlog_assignments = [a for a in assignments if a.tutor_id == tutors[5].id]
        for i, a in enumerate(backlog_assignments):
            _log(a, "CIR-PROC-01", 1, 9 + i, "pending")   # older than the 5-day threshold
            _log(a, "CIR-PROC-03", 1, 11 + i, "pending")  # second old pending entry

        # Rotation ending soon with fixed-target activity materially at risk
        # (assignments[8]: active, ends in 4 days) — "Realiza lavado gástrico"
        # MED-PROC-09, target 3, only 1 verified (~33%, below the 50% threshold).
        _log(assignments[8], "MED-PROC-09", 1, 20, "verified", tutor0_user)

        # Completed rotation with an UNVERIFIED activity remaining (edge case:
        # activity logged after the rotation was marked completed).
        _log(completed_assignment, "MED-PROC-07", 1, 3, "pending")

        # A second rejected activity that has NOT been corrected, old enough to
        # trigger rejected_activity_requires_correction (distinct from the
        # rejected→corrected pair above, which demonstrates the opposite path).
        stale_rejected = _log(assignments[2], "PED-PROC-06", 1, 9, "rejected", tutor2_user,
                              "Falta referencia anónima del procedimiento. Reenviar con datos completos.",
                              notes="Pendiente de corrección por el interno (demo).")

        # -- Explicit seeded alerts (mirror the 4 rule categories) -------
        db.add_all([
            Alert(category=ALERT_ROTATION_ENDING, severity=AlertSeverity.WARNING.value,
                  status=AlertStatus.OPEN.value, title="Rotación por finalizar",
                  message=f"{students[8].full_name} — Medicina Interna finaliza en 4 día(s).",
                  source="rule_engine", related_entity_type="rotation_assignment"),
            Alert(category=ALERT_MISSING_TUTOR, severity=AlertSeverity.CRITICAL.value,
                  status=AlertStatus.OPEN.value, title="Rotación sin tutor asignado",
                  message=f"La rotación de {students[9].full_name} en Cirugía General no tiene tutor.",
                  source="rule_engine", related_entity_type="rotation_assignment"),
            Alert(category=ALERT_PENDING_EVALUATION, severity=AlertSeverity.WARNING.value,
                  status=AlertStatus.OPEN.value, title="Evaluación pendiente",
                  message=f"Evaluación de fin de rotación pendiente para {eval_assignment.student.full_name}.",
                  source="rule_engine", related_entity_type="evaluation"),
            Alert(category=ALERT_INCOMPLETE_PROFILE, severity=AlertSeverity.INFO.value,
                  status=AlertStatus.OPEN.value, title="Perfil de interno incompleto",
                  message=f"El perfil de {students[-1].full_name} está incompleto.",
                  source="rule_engine", related_entity_type="student"),
        ])

        # -- Batch 2E: document templates --------------------------------
        _seed_document_templates(db)

        # -- Batch 2E: formal documents (every status) -------------------
        admin_id, uni_id = admin.id, uni_coord.id
        sede_coord_id = sede_coords[0].user_id
        student_uid = student_user.id
        now = utcnow()

        def _doc(seq, **kw):
            code = f"DOC-{year}-{seq:04d}"
            kw.setdefault("created_by_user_id", uni_id)
            kw.setdefault("priority", DocumentPriority.NORMAL.value)
            kw.setdefault("visibility", VisibilityLevel.NORMAL.value)
            d = DocumentRecord(code=code, seq_year=year, seq_number=seq, **kw)
            db.add(d); db.flush()
            db.add(StatusHistory(owner_type=OWNER_DOCUMENT, owner_id=d.id, from_status=None,
                                 to_status=DocumentStatus.DRAFT.value, action="create",
                                 actor_user_id=kw.get("created_by_user_id"), actor_label="seed"))
            if d.status != DocumentStatus.DRAFT.value:
                db.add(StatusHistory(owner_type=OWNER_DOCUMENT, owner_id=d.id,
                                     from_status=DocumentStatus.DRAFT.value, to_status=d.status,
                                     action="seed_state", actor_user_id=uni_id, actor_label="seed"))
            return d

        _doc(1, title="Designación de tutores - H. Vitarte", doc_type="tutor_designation",
             status=DocumentStatus.DRAFT.value, created_by_user_id=sede_coord_id,
             origin="Coordinador de Sede", destination="Coordinación de Internado UPeU",
             sede_id=sedes[0].id, subject="Relación de tutores designados",
             body="Se remite la relación de tutores designados para el periodo vigente.")

        _doc(2, title="Comunicación oficial - inicio de periodo", doc_type="official_communication",
             status=DocumentStatus.SUBMITTED.value, submitted_by_user_id=sede_coord_id,
             submitted_at=now - timedelta(days=1), origin="Coordinador de Sede",
             destination="Coordinación de Internado UPeU", sede_id=sedes[0].id,
             subject="Inicio del periodo de internado",
             body="Comunicamos el inicio del periodo de internado en la sede.")

        _doc(3, title="Cambio de rotación - interno", doc_type="rotation_change",
             status=DocumentStatus.UNDER_REVIEW.value, submitted_by_user_id=sede_coord_id,
             submitted_at=now - timedelta(days=2), reviewed_by_user_id=uni_id,
             reviewed_at=now - timedelta(days=1), sede_id=sedes[1].id, student_id=students[1].id,
             subject="Solicitud de cambio de rotación",
             body="Se solicita el cambio de rotación por motivos de programación.")

        _doc(4, title="Designación de coordinador de sede", doc_type="coordinator_designation",
             status=DocumentStatus.APPROVED.value, submitted_by_user_id=sede_coord_id,
             submitted_at=now - timedelta(days=6), reviewed_by_user_id=uni_id,
             reviewed_at=now - timedelta(days=5), approved_by_user_id=uni_id,
             approved_at=now - timedelta(days=4), sede_id=sedes[1].id,
             subject="Designación de coordinador de sede",
             body="Se aprueba la designación del coordinador de sede para el periodo.")

        _doc(5, title="Corrección de nota - rotación", doc_type="grade_correction",
             status=DocumentStatus.REJECTED.value, submitted_by_user_id=sede_coord_id,
             submitted_at=now - timedelta(days=3), reviewed_by_user_id=uni_id,
             reviewed_at=now - timedelta(days=2), rejected_by_user_id=uni_id,
             rejected_at=now - timedelta(days=1),
             rejection_reason="Falta el sustento del acta original. Adjuntar y reenviar.",
             sede_id=sedes[0].id, student_id=students[2].id,
             subject="Solicitud de corrección de nota",
             body="Se solicita la corrección de la nota registrada por error material.")

        _doc(6, title="Comunicación oficial archivada", doc_type="official_communication",
             status=DocumentStatus.ARCHIVED.value, submitted_by_user_id=sede_coord_id,
             submitted_at=now - timedelta(days=40), reviewed_by_user_id=uni_id,
             reviewed_at=now - timedelta(days=39), approved_by_user_id=uni_id,
             approved_at=now - timedelta(days=38), archived_by_user_id=uni_id,
             archived_at=now - timedelta(days=30), sede_id=sedes[1].id,
             subject="Comunicación de cierre de periodo anterior",
             body="Comunicación oficial correspondiente al periodo anterior, archivada.")

        # Resignation example modelled on the attached reference structure.
        _doc(7, title="Comunicación de renuncia a plaza de Internado Médico",
             doc_type="resignation", status=DocumentStatus.APPROVED.value,
             priority=DocumentPriority.HIGH.value, submitted_by_user_id=uni_id,
             submitted_at=now - timedelta(days=8), reviewed_by_user_id=uni_id,
             reviewed_at=now - timedelta(days=7), approved_by_user_id=admin_id,
             approved_at=now - timedelta(days=6), sede_id=sedes[1].id, student_id=students[3].id,
             origin="Dr. Luis Felipe Segura Chávez — Director, Escuela Profesional de Medicina",
             destination=("Dra. Lili Fernández Molocho\nDecana de la Facultad de Ciencias de la Salud\n"
                          "Universidad Peruana Unión"),
             subject=("Comunicación de renuncia a plaza de Internado Médico y solicitud de "
                      "gestión ante la instancia competente."),
             summary="Comunica la renuncia formal de una interna a su plaza de internado.",
             body=("De mi mayor consideración:\n\n"
                   "Me dirijo a usted para saludarle cordialmente y, a la vez, comunicar que la "
                   f"interna {students[3].full_name}, alumna de la Escuela Profesional de Medicina, "
                   "quien se encontraba realizando el Internado Médico en la sede asignada, ha "
                   "presentado formalmente su solicitud de renuncia a la plaza de internado "
                   "adjudicada, adjuntando los fundamentos correspondientes.\n\n"
                   "En ese sentido, solicitamos realizar las coordinaciones y trámites "
                   "administrativos pertinentes ante las instancias competentes, conforme a la "
                   "normativa vigente y los procedimientos institucionales establecidos.\n\n"
                   "Asimismo, se adjunta la documentación presentada por la alumna para los fines "
                   "administrativos correspondientes.\n\n"
                   "Sin otro particular, hago propicia la oportunidad para expresarle las muestras "
                   "de mi especial consideración y estima personal."))

        # Change-of-sede request originated by the demo student (draft).
        _doc(8, title="Solicitud de cambio de sede", doc_type="sede_change",
             status=DocumentStatus.DRAFT.value, created_by_user_id=student_uid,
             student_id=students[0].id, sede_id=students[0].sede_id,
             origin=students[0].full_name, destination="Coordinación de Internado UPeU",
             subject="Solicitud de cambio de sede de internado",
             body="Solicito el cambio de sede por motivos debidamente sustentados.")

        # Overdue document: submitted long ago, still in review.
        _doc(9, title="Permiso pendiente de gestión", doc_type="permission",
             status=DocumentStatus.SUBMITTED.value, priority=DocumentPriority.HIGH.value,
             submitted_by_user_id=sede_coord_id, submitted_at=now - timedelta(days=20),
             due_date=TODAY - timedelta(days=2), sede_id=sedes[0].id, student_id=students[4].id,
             subject="Solicitud de permiso", body="Solicitud de permiso pendiente de decisión.")

        # -- Batch 2E: incidents (every severity/status) -----------------
        def _inc(seq, **kw):
            code = f"INC-{year}-{seq:04d}"
            # Default reporter is the University Coordinator (a global viewer),
            # so scope isolation between sedes is not accidentally widened by the
            # "reporter can always view" rule.
            kw.setdefault("reported_by_user_id", uni_id)
            kw.setdefault("reported_by", "Coordinación de Internado")
            kw.setdefault("report_date", TODAY)
            kw.setdefault("visibility", VisibilityLevel.NORMAL.value)
            i = Incident(code=code, seq_year=year, seq_number=seq, **kw)
            db.add(i); db.flush()
            db.add(StatusHistory(owner_type=OWNER_INCIDENT, owner_id=i.id, from_status=None,
                                 to_status=IncidentStatus.OPEN.value, action="create",
                                 actor_user_id=kw.get("reported_by_user_id"), actor_label="seed"))
            return i

        _inc(1, title="Retraso en credenciales de acceso",
             description="Dos internos reportan demora en la emisión de credenciales en la sede.",
             incident_type="other", severity=IncidentSeverity.LOW.value,
             status=IncidentStatus.OPEN.value, sede_id=sedes[3].id)

        _inc(2, title="Tardanzas reiteradas en la rotación",
             description="Se registran tardanzas reiteradas de un interno durante la última semana.",
             incident_type="repeated_tardiness", severity=IncidentSeverity.HIGH.value,
             status=IncidentStatus.UNDER_REVIEW.value, sede_id=sedes[0].id,
             student_id=students[5].id, due_date=TODAY + timedelta(days=2))

        _inc(3, title="Accidente con material punzocortante",
             description="Interno sufre pinchazo con aguja durante procedimiento; se activa protocolo.",
             incident_type="accident", severity=IncidentSeverity.CRITICAL.value,
             status=IncidentStatus.ACTION_REQUIRED.value, sede_id=sedes[1].id,
             student_id=students[6].id, due_date=TODAY + timedelta(days=1),
             internal_notes="Seguimiento con salud ocupacional (nota interna).")

        _inc(4, title="Queja de la sede por documentación",
             description="La sede reporta documentación incompleta de un interno.",
             incident_type="sede_complaint", severity=IncidentSeverity.MEDIUM.value,
             status=IncidentStatus.RESOLVED.value, sede_id=sedes[0].id, student_id=students[7].id,
             resolution="Documentación regularizada y verificada con la sede.",
             resolved_by_user_id=uni_id, resolved_at=now - timedelta(days=1))

        _inc(5, title="Asunto de confidencialidad - salud",
             description="Situación de salud del interno tratada de forma confidencial.",
             incident_type="confidentiality", severity=IncidentSeverity.HIGH.value,
             status=IncidentStatus.UNDER_REVIEW.value,
             visibility=VisibilityLevel.CONFIDENTIAL.value, sede_id=sedes[1].id,
             student_id=students[1].id, reported_by_user_id=uni_id,
             internal_notes="Información sensible restringida a coordinación (nota interna).")

        _inc(6, title="Incidencia vencida sin atención",
             description="Incidencia con fecha límite vencida y aún sin resolver.",
             incident_type="activity_noncompliance", severity=IncidentSeverity.MEDIUM.value,
             status=IncidentStatus.UNDER_REVIEW.value, sede_id=sedes[0].id,
             student_id=students[2].id, due_date=TODAY - timedelta(days=3))

        # Set numbering counters so live allocation continues after seeded codes.
        db.add(DocumentSequence(kind="document", year=year, last_value=9))
        db.add(DocumentSequence(kind="incident", year=year, last_value=6))

        # -- Batch 2F: grade schemes (null weights) + import batches -----
        _seed_grades_and_imports(db, year, students, uni_coord, rt_cirugia, current_period)
        db.add(DocumentSequence(kind="import", year=year, last_value=3))

        db.commit()
        _print_summary(db)
    except Exception:
        db.rollback()
        logger.exception("Seed failed")
        raise
    finally:
        db.close()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _seed_grades_and_imports(db, year, students, uni_coord, rt_cirugia, current_period) -> None:
    """Seed grade schemes (null weights), example blank-vs-zero scores and a
    couple of import batches (one confirmed, one with errors, one grade preview)."""
    import json as _json

    # -- Grade scheme with UNCONFIRMED (null) weights --------------------
    scheme = GradeScheme(
        code=f"GS-CIR-{year}", name=f"Internado en Cirugía {year}",
        rotation_type_id=rt_cirugia.id, period_id=current_period.id, version=1,
        status=GradeSchemeStatus.ACTIVE.value, weights_confirmed=False,
        notes="Pesos pendientes de confirmación oficial (no se calcula nota final).")
    db.add(scheme); db.flush()
    comps = [
        GradeComponentDefinition(scheme_id=scheme.id, name="Actitudinal",
                                 category="actitudinal", is_required=True, weight_percent=None,
                                 source="QX 2026", display_order=1),
        GradeComponentDefinition(scheme_id=scheme.id, name="Examen escrito",
                                 category="examen_escrito", is_required=True, weight_percent=None,
                                 source="QX 2026", display_order=2),
        GradeComponentDefinition(scheme_id=scheme.id, name="Portafolio",
                                 category="portafolio", is_required=False, weight_percent=None,
                                 source="PORTAFOLIOS", display_order=3),
    ]
    db.add_all(comps); db.flush()

    # A second scheme (foundation for the future agent).
    scheme2 = GradeScheme(
        code=f"GS-RMQ3-{year}", name=f"Revisión Médico Quirúrgica III {year}",
        period_id=current_period.id, version=1, status=GradeSchemeStatus.DRAFT.value,
        weights_confirmed=False)
    db.add(scheme2); db.flush()
    db.add(GradeComponentDefinition(scheme_id=scheme2.id, name="Examen final",
                                    category="examen_final" if False else "examen_escrito",
                                    is_required=True, weight_percent=None, display_order=1))
    db.flush()

    # -- Example BLANK vs ZERO scores ------------------------------------
    # student[0]: Actitudinal = 0 (real zero), Examen escrito = 15, Portafolio = blank (null).
    sg_zero = StudentGradeComponent(
        student_id=students[0].id, scheme_id=scheme.id, component_id=comps[0].id,
        score=0.0, status=GradeComponentStatus.IMPORTED.value, source_type="import",
        source_sheet="QX 2026", source_row=2, source_col="Actitudinal",
        entered_by_user_id=uni_coord.id)
    sg_val = StudentGradeComponent(
        student_id=students[0].id, scheme_id=scheme.id, component_id=comps[1].id,
        score=15.0, status=GradeComponentStatus.APPROVED.value, source_type="import",
        source_sheet="QX 2026", source_row=2, source_col="Examen escrito",
        entered_by_user_id=uni_coord.id, approved_by_user_id=uni_coord.id, approved_at=utcnow())
    sg_blank = StudentGradeComponent(
        student_id=students[0].id, scheme_id=scheme.id, component_id=comps[2].id,
        score=None, status=GradeComponentStatus.IMPORTED.value, source_type="import",
        source_sheet="PORTAFOLIOS", source_row=2, source_col="Portafolio",
        entered_by_user_id=uni_coord.id)  # blank = not registered (distinct from 0)
    db.add_all([sg_zero, sg_val, sg_blank]); db.flush()
    for sg, new in ((sg_zero, 0.0), (sg_val, 15.0), (sg_blank, None)):
        db.add(GradeComponentHistory(student_grade_component_id=sg.id, old_score=None,
                                     new_score=new, old_status=None, new_status=sg.status,
                                     action="import_created", actor_user_id=uni_coord.id,
                                     actor_label="seed"))

    # -- Import batches (history) ----------------------------------------
    # A successful student import.
    b_ok = ImportBatch(
        code=f"IMP-{year}-0001", profile="students", original_filename="internos_demo.xlsx",
        stored_filename=None, sheet_name="Alumnos", mode=ImportMode.CREATE_ONLY.value,
        status=ImportStatus.CONFIRMED.value,
        mapping_json=_json.dumps({"student_code": "Código", "full_name": "Nombre",
                                  "document_id": "DNI/CE"}, ensure_ascii=False),
        total_rows=2, valid_rows=2, created_count=2, created_by_user_id=uni_coord.id,
        confirmed_by_user_id=uni_coord.id, confirmed_at=utcnow())
    db.add(b_ok); db.flush()
    db.add_all([
        ImportRow(batch_id=b_ok.id, row_number=1, source_sheet="Alumnos",
                  raw_json=_json.dumps({"Código": "2026D01"}), status="created", action="create"),
        ImportRow(batch_id=b_ok.id, row_number=2, source_sheet="Alumnos",
                  raw_json=_json.dumps({"Código": "2026D02"}), status="created", action="create"),
    ])

    # An import with errors (partial).
    b_err = ImportBatch(
        code=f"IMP-{year}-0002", profile="students", original_filename="internos_con_errores.xlsx",
        stored_filename=None, sheet_name="Alumnos", mode=ImportMode.VALID_ONLY.value,
        status=ImportStatus.PARTIAL.value,
        mapping_json=_json.dumps({"student_code": "Código"}, ensure_ascii=False),
        total_rows=2, valid_rows=1, error_rows=1, created_count=1, failed_count=1,
        created_by_user_id=uni_coord.id, confirmed_by_user_id=uni_coord.id, confirmed_at=utcnow())
    db.add(b_err); db.flush()
    db.add_all([
        ImportRow(batch_id=b_err.id, row_number=1, source_sheet="Alumnos",
                  raw_json=_json.dumps({"Código": "2026D03"}), status="created", action="create"),
        ImportRow(batch_id=b_err.id, row_number=2, source_sheet="Alumnos",
                  raw_json=_json.dumps({"Código": ""}), status="failed", action=None,
                  messages_json=_json.dumps([{"level": "error", "field": "student_code",
                                              "message": "El código es obligatorio."}])),
    ])

    # A grade import PREVIEW (validated, awaiting confirmation).
    b_grade = ImportBatch(
        code=f"IMP-{year}-0003", profile="grade_components", original_filename="notas_qx_2026.xlsx",
        stored_filename=None, sheet_name="QX 2026", mode=ImportMode.CREATE_ONLY.value,
        status=ImportStatus.VALIDATED.value,
        mapping_json=_json.dumps({"student_key": "DNI/CE", f"comp_{comps[0].id}": "Actitudinal",
                                  "_scheme_id": str(scheme.id)}, ensure_ascii=False),
        total_rows=1, valid_rows=1, created_by_user_id=uni_coord.id)
    db.add(b_grade); db.flush()
    db.add(ImportRow(batch_id=b_grade.id, row_number=1, source_sheet="QX 2026",
                     raw_json=_json.dumps({"DNI/CE": students[1].student_code, "Actitudinal": 0}),
                     status="valid", action="create"))
    db.flush()


def _seed_document_templates(db) -> None:
    """Seed reusable document templates (editable drafts, never auto-approved)."""
    templates = [
        DocumentTemplate(
            code="tpl_resignation", name="Renuncia al internado", doc_type="resignation",
            subject_template="Comunicación de renuncia a plaza de Internado Médico",
            description="Estructura formal basada en la carta de referencia.",
            body_template=(
                "De mi mayor consideración:\n\n"
                "Me dirijo a usted para saludarle cordialmente y comunicar que el/la interno(a) "
                "[NOMBRE], alumno(a) de la Escuela Profesional de Medicina, quien se encontraba "
                "realizando el Internado Médico en [SEDE], ha presentado formalmente su solicitud "
                "de renuncia a la plaza de internado adjudicada, adjuntando los fundamentos "
                "correspondientes.\n\n"
                "En ese sentido, solicitamos realizar las coordinaciones y trámites administrativos "
                "pertinentes ante las instancias competentes, conforme a la normativa vigente.\n\n"
                "Asimismo, se adjunta la documentación presentada para los fines correspondientes.\n\n"
                "Sin otro particular, quedo de usted.")),
        DocumentTemplate(
            code="tpl_sede_change", name="Cambio de sede", doc_type="sede_change",
            subject_template="Solicitud de cambio de sede de internado",
            description="Solicitud de cambio de sede.",
            body_template=(
                "De mi mayor consideración:\n\n"
                "Solicito el cambio de sede de internado de [SEDE_ACTUAL] a [SEDE_DESTINO], "
                "por los motivos que expongo a continuación:\n\n[MOTIVOS]\n\n"
                "Agradezco la atención a la presente solicitud.")),
        DocumentTemplate(
            code="tpl_rotation_change", name="Cambio de rotación", doc_type="rotation_change",
            subject_template="Solicitud de cambio de rotación",
            description="Solicitud de cambio de rotación.",
            body_template=(
                "De mi mayor consideración:\n\n"
                "Solicito el cambio de rotación de [ROTACION_ACTUAL] a [ROTACION_DESTINO], "
                "por los siguientes motivos:\n\n[MOTIVOS]\n\nQuedo atento(a) a su respuesta.")),
        DocumentTemplate(
            code="tpl_incident_report", name="Informe de incidente", doc_type="incident_report",
            subject_template="Informe de incidente",
            description="Informe formal de un incidente.",
            body_template=(
                "Por medio del presente informo el siguiente incidente:\n\n"
                "- Fecha: [FECHA]\n- Interno(a): [NOMBRE]\n- Sede: [SEDE]\n"
                "- Descripción: [DESCRIPCION]\n- Acciones tomadas: [ACCIONES]\n\n"
                "Se remite para su conocimiento y gestión correspondiente.")),
        DocumentTemplate(
            code="tpl_official_communication", name="Comunicación oficial",
            doc_type="official_communication",
            subject_template="Comunicación oficial",
            description="Comunicación oficial institucional.",
            body_template=(
                "De mi mayor consideración:\n\n[CONTENIDO]\n\n"
                "Sin otro particular, hago propicia la oportunidad para expresarle las muestras "
                "de mi especial consideración.")),
    ]
    db.add_all(templates)
    db.flush()



def _add_criteria(db, evaluation: Evaluation, scored: bool = False) -> None:
    """Attach the 15 official criteria to an evaluation."""
    for area, items in EVAL_CRITERIA.items():
        for idx, desc in enumerate(items):
            db.add(EvaluationCriterion(
                evaluation_id=evaluation.id, area=area, order_index=idx,
                description=desc, score=(4 if scored and idx % 2 == 0 else 3) if scored else None,
            ))


def _add_scored_criteria(db, evaluation: Evaluation,
                         area_scores: dict[str, list]) -> dict[str, int]:
    """Attach the 15 criteria with explicit per-criterion scores.

    ``area_scores`` maps area -> list of 5 scores (0-4, or None if unscored).
    Returns the area sums (only for areas with all 5 criteria scored) so the
    caller can cache them exactly as the server-side formula would compute.
    """
    sums: dict[str, int] = {}
    for area, items in EVAL_CRITERIA.items():
        scores = area_scores.get(area, [None] * len(items))
        for idx, desc in enumerate(items):
            db.add(EvaluationCriterion(
                evaluation_id=evaluation.id, area=area, order_index=idx,
                description=desc, score=scores[idx],
            ))
        if all(s is not None for s in scores):
            sums[area] = sum(scores)
    return sums


def _next_period(periods, current) -> AcademicPeriod:
    ordered = sorted(periods, key=lambda p: p.ordinal)
    for p in ordered:
        if p.ordinal > current.ordinal:
            return p
    return ordered[0]  # wrap around (December → next year would follow in prod)


def _mark_nearest_current(periods) -> None:
    """Fallback: mark the period whose range is nearest to today as current."""
    nearest = min(periods, key=lambda p: abs((p.start_date - TODAY).days))
    nearest.is_current = True


def _print_summary(db) -> None:
    counts = {
        "roles": db.query(Role).count(),
        "usuarios": db.query(User).count(),
        "sedes": db.query(Sede).count(),
        "tutores": db.query(TutorProfile).count(),
        "coordinadores de sede": db.query(SedeCoordinatorProfile).count(),
        "internos": db.query(Student).count(),
        "rotaciones (asignaciones)": db.query(RotationAssignment).count(),
        "evaluaciones": db.query(Evaluation).count(),
        "definiciones de actividad": db.query(ActivityDefinition).count(),
        "registros de actividad": db.query(StudentActivity).count(),
        "alertas": db.query(Alert).count(),
    }
    logger.info("Seed completado:")
    for k, v in counts.items():
        logger.info("  · %-28s %d", k, v)
    logger.info("Cuentas demo (contraseña '%s'):", DEMO_PASSWORD)
    for email in ["admin@internado360.demo", "coordinator@internado360.demo",
                  "sede@internado360.demo", "tutor@internado360.demo",
                  "student@internado360.demo"]:
        logger.info("  · %s", email)


def main() -> None:
    """CLI entry point.

    Usage:
        python -m app.seed            # safe: seed only if empty (post-migration)
        python -m app.seed --reset    # DESTRUCTIVE: rebuild demo data
    """
    import argparse

    parser = argparse.ArgumentParser(description="Seed UPeU Internado 360 demo data.")
    parser.add_argument(
        "--reset", action="store_true",
        help="Drop and recreate all tables before seeding (demo reset).",
    )
    args = parser.parse_args()
    seed(reset=args.reset)


if __name__ == "__main__":
    main()
