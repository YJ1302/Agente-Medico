"""Concrete repositories for the platform's core entities.

Grouped in one module for the prototype to keep the file count manageable while
still enforcing the repository boundary. Each repository exposes only the
queries the service layer needs.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.academic import AcademicPeriod, RotationAssignment, RotationType
from app.models.activity import ActivityDefinition, ActivityReview, StudentActivity
from app.models.audit import AgentExecution, AuditLog
from app.models.base import (
    AlertStatus,
    AssignmentStatus,
    EvaluationStatus,
)
from app.models.evaluation import Evaluation
from app.models.operations import Alert, DocumentRecord, Incident
from app.models.organization import (
    InstitutionType,
    Sede,
    SedeCoordinatorProfile,
    TutorProfile,
)
from app.models.student import Student
from app.models.user import Role, User
from app.repositories.base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    def get_by_email(self, email: str) -> User | None:
        stmt = (
            select(User)
            .options(selectinload(User.role))
            .where(func.lower(User.email) == email.lower())
        )
        return self.db.execute(stmt).scalar_one_or_none()


class RoleRepository(BaseRepository[Role]):
    model = Role

    def get_by_code(self, code: str) -> Role | None:
        return self.db.execute(
            select(Role).where(Role.code == code)
        ).scalar_one_or_none()


class InstitutionTypeRepository(BaseRepository[InstitutionType]):
    model = InstitutionType

    def get_by_code(self, code: str) -> InstitutionType | None:
        return self.db.execute(
            select(InstitutionType).where(InstitutionType.code == code)
        ).scalar_one_or_none()


class SedeRepository(BaseRepository[Sede]):
    model = Sede

    def active(self) -> list[Sede]:
        stmt = select(Sede).where(
            and_(Sede.is_active.is_(True), Sede.is_deleted.is_(False))
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_full(self, sede_id: int) -> Sede | None:
        stmt = (
            select(Sede)
            .options(
                selectinload(Sede.institution_type),
                selectinload(Sede.coordinators).selectinload(SedeCoordinatorProfile.user),
                selectinload(Sede.tutors).selectinload(TutorProfile.user),
                selectinload(Sede.students),
                selectinload(Sede.rotation_assignments),
            )
            .where(Sede.id == sede_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_name(self, name: str) -> Sede | None:
        return self.db.execute(
            select(Sede).where(func.lower(Sede.name) == name.strip().lower())
        ).scalar_one_or_none()

    def get_by_short_name(self, short: str) -> Sede | None:
        return self.db.execute(
            select(Sede).where(func.lower(Sede.short_name) == short.strip().lower())
        ).scalar_one_or_none()

    def search(
        self,
        *,
        query: str | None = None,
        institution_code: str | None = None,
        sede_type: str | None = None,
        active: bool | None = None,
        sede_ids: set[int] | None = None,
        include_deleted: bool = False,
    ) -> list[Sede]:
        stmt = select(Sede).options(selectinload(Sede.institution_type))
        conds = []
        if not include_deleted:
            conds.append(Sede.is_deleted.is_(False))
        if query:
            like = f"%{query.strip().lower()}%"
            conds.append(
                func.lower(Sede.name).like(like)
                | func.lower(func.coalesce(Sede.short_name, "")).like(like)
                | func.lower(func.coalesce(Sede.city, "")).like(like)
                | func.lower(func.coalesce(Sede.address, "")).like(like)
            )
        if institution_code:
            stmt = stmt.join(InstitutionType, Sede.institution_type_id == InstitutionType.id)
            conds.append(InstitutionType.code == institution_code)
        if sede_type:
            conds.append(Sede.sede_type == sede_type)
        if active is not None:
            conds.append(Sede.is_active.is_(active))
        if sede_ids is not None:
            conds.append(Sede.id.in_(sede_ids) if sede_ids else False)
        if conds:
            stmt = stmt.where(and_(*conds))
        return list(self.db.execute(stmt.order_by(Sede.name)).scalars().all())

    def active_planned_assignment_count(self, sede_id: int) -> int:
        stmt = select(func.count(RotationAssignment.id)).where(
            and_(
                RotationAssignment.sede_id == sede_id,
                RotationAssignment.is_deleted.is_(False),
                RotationAssignment.status.in_(
                    [AssignmentStatus.ACTIVE.value, AssignmentStatus.PLANNED.value]
                ),
            )
        )
        return int(self.db.execute(stmt).scalar_one())


class StudentRepository(BaseRepository[Student]):
    model = Student

    def active(self) -> list[Student]:
        stmt = (
            select(Student)
            .options(
                selectinload(Student.institution_type),
                selectinload(Student.sede),
            )
            .where(and_(Student.is_active.is_(True), Student.is_deleted.is_(False)))
        )
        return list(self.db.execute(stmt).scalars().all())

    def count_by_institution(self, institution_code: str) -> int:
        stmt = (
            select(func.count(Student.id))
            .join(InstitutionType)
            .where(
                and_(
                    InstitutionType.code == institution_code,
                    Student.is_active.is_(True),
                    Student.is_deleted.is_(False),
                )
            )
        )
        return int(self.db.execute(stmt).scalar_one())

    def incomplete_profiles(self) -> list[Student]:
        stmt = select(Student).where(
            and_(
                Student.profile_status == "incomplete",
                Student.is_deleted.is_(False),
            )
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_by_code(self, code: str) -> Student | None:
        return self.db.execute(
            select(Student).where(Student.student_code == code)
        ).scalar_one_or_none()

    def get_by_email(self, email: str) -> Student | None:
        return self.db.execute(
            select(Student).where(func.lower(Student.email) == email.lower())
        ).scalar_one_or_none()

    def get_by_document(self, document_id: str) -> Student | None:
        return self.db.execute(
            select(Student).where(Student.document_id == document_id)
        ).scalar_one_or_none()

    def get_full(self, student_id: int) -> Student | None:
        """Load a student with the relations needed by the detail page."""
        stmt = (
            select(Student)
            .options(
                selectinload(Student.institution_type),
                selectinload(Student.sede),
                selectinload(Student.rotation_assignments),
                selectinload(Student.evaluations),
                selectinload(Student.activities),
            )
            .where(Student.id == student_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def search(
        self,
        *,
        query: str | None = None,
        cycle: str | None = None,
        institution_code: str | None = None,
        sede_id: int | None = None,
        profile_status: str | None = None,
        active: bool | None = None,
        sede_ids: set[int] | None = None,
        include_deleted: bool = False,
    ) -> list[Student]:
        """Filtered student list (excludes soft-deleted unless requested).

        ``sede_ids`` restricts results to a set of sedes (used for role scope).
        """
        stmt = select(Student).options(
            selectinload(Student.institution_type),
            selectinload(Student.sede),
        )
        conds = []
        if not include_deleted:
            conds.append(Student.is_deleted.is_(False))
        if query:
            like = f"%{query.strip().lower()}%"
            conds.append(
                func.lower(Student.full_name).like(like)
                | func.lower(Student.student_code).like(like)
                | func.lower(func.coalesce(Student.document_id, "")).like(like)
                | func.lower(func.coalesce(Student.email, "")).like(like)
            )
        if cycle:
            conds.append(Student.cycle == cycle)
        if institution_code:
            stmt = stmt.join(InstitutionType, Student.institution_type_id == InstitutionType.id)
            conds.append(InstitutionType.code == institution_code)
        if sede_id is not None:
            conds.append(Student.sede_id == sede_id)
        if profile_status:
            conds.append(Student.profile_status == profile_status)
        if active is not None:
            conds.append(Student.is_active.is_(active))
        if sede_ids is not None:
            conds.append(Student.sede_id.in_(sede_ids) if sede_ids else False)
        if conds:
            stmt = stmt.where(and_(*conds))
        stmt = stmt.order_by(Student.full_name)
        return list(self.db.execute(stmt).scalars().all())


class TutorRepository(BaseRepository[TutorProfile]):
    model = TutorProfile

    def active(self) -> list[TutorProfile]:
        stmt = (
            select(TutorProfile)
            .options(selectinload(TutorProfile.user), selectinload(TutorProfile.sede))
            .where(TutorProfile.is_deleted.is_(False))
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_full(self, tutor_id: int) -> TutorProfile | None:
        stmt = (
            select(TutorProfile)
            .options(
                selectinload(TutorProfile.user),
                selectinload(TutorProfile.sede),
                selectinload(TutorProfile.rotation_assignments).selectinload(
                    RotationAssignment.student
                ),
                selectinload(TutorProfile.rotation_assignments).selectinload(
                    RotationAssignment.rotation_type
                ),
            )
            .where(TutorProfile.id == tutor_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_user(self, user_id: int) -> TutorProfile | None:
        return self.db.execute(
            select(TutorProfile).where(TutorProfile.user_id == user_id)
        ).scalar_one_or_none()

    def by_sede(self, sede_id: int) -> list[TutorProfile]:
        stmt = (
            select(TutorProfile)
            .options(selectinload(TutorProfile.user))
            .where(
                and_(
                    TutorProfile.sede_id == sede_id,
                    TutorProfile.is_deleted.is_(False),
                )
            )
        )
        return list(self.db.execute(stmt).scalars().all())

    def workload_count(self, tutor_id: int) -> int:
        """Active + planned assignments currently supervised by the tutor."""
        stmt = select(func.count(RotationAssignment.id)).where(
            and_(
                RotationAssignment.tutor_id == tutor_id,
                RotationAssignment.is_deleted.is_(False),
                RotationAssignment.status.in_(
                    [AssignmentStatus.ACTIVE.value, AssignmentStatus.PLANNED.value]
                ),
            )
        )
        return int(self.db.execute(stmt).scalar_one())

    def search(
        self,
        *,
        query: str | None = None,
        sede_id: int | None = None,
        service: str | None = None,
        active: bool | None = None,
        sede_ids: set[int] | None = None,
    ) -> list[TutorProfile]:
        stmt = (
            select(TutorProfile)
            .join(User, TutorProfile.user_id == User.id)
            .options(selectinload(TutorProfile.user), selectinload(TutorProfile.sede))
            .where(TutorProfile.is_deleted.is_(False))
        )
        conds = []
        if query:
            like = f"%{query.strip().lower()}%"
            conds.append(
                func.lower(User.full_name).like(like)
                | func.lower(User.email).like(like)
            )
        if sede_id is not None:
            conds.append(TutorProfile.sede_id == sede_id)
        if service:
            conds.append(TutorProfile.service == service)
        if active is not None:
            conds.append(TutorProfile.is_active.is_(active))
        if sede_ids is not None:
            conds.append(TutorProfile.sede_id.in_(sede_ids) if sede_ids else False)
        if conds:
            stmt = stmt.where(and_(*conds))
        return list(self.db.execute(stmt.order_by(User.full_name)).scalars().all())


class SedeCoordinatorRepository(BaseRepository[SedeCoordinatorProfile]):
    model = SedeCoordinatorProfile

    def active(self) -> list[SedeCoordinatorProfile]:
        stmt = (
            select(SedeCoordinatorProfile)
            .options(
                selectinload(SedeCoordinatorProfile.user),
                selectinload(SedeCoordinatorProfile.sede),
            )
            .where(SedeCoordinatorProfile.is_deleted.is_(False))
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_full(self, coord_id: int) -> SedeCoordinatorProfile | None:
        stmt = (
            select(SedeCoordinatorProfile)
            .options(
                selectinload(SedeCoordinatorProfile.user),
                selectinload(SedeCoordinatorProfile.sede),
            )
            .where(SedeCoordinatorProfile.id == coord_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_user(self, user_id: int) -> SedeCoordinatorProfile | None:
        return self.db.execute(
            select(SedeCoordinatorProfile).where(
                SedeCoordinatorProfile.user_id == user_id
            )
        ).scalar_one_or_none()

    def active_principal_for_sede(self, sede_id: int) -> SedeCoordinatorProfile | None:
        """The current active principal coordinator of a sede, if any."""
        stmt = (
            select(SedeCoordinatorProfile)
            .options(selectinload(SedeCoordinatorProfile.user))
            .where(
                and_(
                    SedeCoordinatorProfile.sede_id == sede_id,
                    SedeCoordinatorProfile.is_principal.is_(True),
                    SedeCoordinatorProfile.is_active.is_(True),
                    SedeCoordinatorProfile.is_deleted.is_(False),
                )
            )
        )
        return self.db.execute(stmt).scalars().first()

    def search(
        self,
        *,
        query: str | None = None,
        sede_id: int | None = None,
        active: bool | None = None,
        sede_ids: set[int] | None = None,
    ) -> list[SedeCoordinatorProfile]:
        stmt = (
            select(SedeCoordinatorProfile)
            .join(User, SedeCoordinatorProfile.user_id == User.id)
            .options(
                selectinload(SedeCoordinatorProfile.user),
                selectinload(SedeCoordinatorProfile.sede),
            )
            .where(SedeCoordinatorProfile.is_deleted.is_(False))
        )
        conds = []
        if query:
            like = f"%{query.strip().lower()}%"
            conds.append(
                func.lower(User.full_name).like(like)
                | func.lower(User.email).like(like)
            )
        if sede_id is not None:
            conds.append(SedeCoordinatorProfile.sede_id == sede_id)
        if active is not None:
            conds.append(SedeCoordinatorProfile.is_active.is_(active))
        if sede_ids is not None:
            conds.append(
                SedeCoordinatorProfile.sede_id.in_(sede_ids) if sede_ids else False
            )
        if conds:
            stmt = stmt.where(and_(*conds))
        return list(self.db.execute(stmt.order_by(User.full_name)).scalars().all())


class RotationTypeRepository(BaseRepository[RotationType]):
    model = RotationType


class AcademicPeriodRepository(BaseRepository[AcademicPeriod]):
    model = AcademicPeriod

    def current(self) -> AcademicPeriod | None:
        return self.db.execute(
            select(AcademicPeriod).where(AcademicPeriod.is_current.is_(True))
        ).scalar_one_or_none()

    def ordered(self) -> list[AcademicPeriod]:
        stmt = select(AcademicPeriod).order_by(
            AcademicPeriod.year, AcademicPeriod.ordinal
        )
        return list(self.db.execute(stmt).scalars().all())


class RotationAssignmentRepository(BaseRepository[RotationAssignment]):
    model = RotationAssignment

    def _base_active(self):
        return (
            select(RotationAssignment)
            .options(
                selectinload(RotationAssignment.student),
                selectinload(RotationAssignment.rotation_type),
                selectinload(RotationAssignment.sede),
                selectinload(RotationAssignment.tutor).selectinload(TutorProfile.user),
                selectinload(RotationAssignment.period),
            )
            .where(RotationAssignment.is_deleted.is_(False))
        )

    def all_with_relations(self) -> list[RotationAssignment]:
        return list(self.db.execute(self._base_active()).scalars().all())

    def get_full(self, assignment_id: int) -> RotationAssignment | None:
        stmt = (
            self._base_active().where(RotationAssignment.id == assignment_id)
            .options(
                selectinload(RotationAssignment.student).selectinload(Student.institution_type),
                selectinload(RotationAssignment.evaluation),
            )
        )
        return self.db.execute(stmt).scalars().first()

    def search(
        self,
        *,
        query: str | None = None,
        period_id: int | None = None,
        rotation_type_id: int | None = None,
        sede_id: int | None = None,
        tutor_id: int | None = None,
        student_id: int | None = None,
        status: str | None = None,
        institution_code: str | None = None,
        has_tutor: bool | None = None,
        sede_ids: set[int] | None = None,
        student_ids: set[int] | None = None,
        tutor_ids: set[int] | None = None,
    ) -> list[RotationAssignment]:
        stmt = self._base_active().join(Student, RotationAssignment.student_id == Student.id)
        conds = []
        if query:
            like = f"%{query.strip().lower()}%"
            conds.append(
                func.lower(Student.full_name).like(like)
                | func.lower(Student.student_code).like(like)
            )
        if period_id is not None:
            conds.append(RotationAssignment.period_id == period_id)
        if rotation_type_id is not None:
            conds.append(RotationAssignment.rotation_type_id == rotation_type_id)
        if sede_id is not None:
            conds.append(RotationAssignment.sede_id == sede_id)
        if tutor_id is not None:
            conds.append(RotationAssignment.tutor_id == tutor_id)
        if student_id is not None:
            conds.append(RotationAssignment.student_id == student_id)
        if status:
            conds.append(RotationAssignment.status == status)
        if has_tutor is True:
            conds.append(RotationAssignment.tutor_id.is_not(None))
        elif has_tutor is False:
            conds.append(RotationAssignment.tutor_id.is_(None))
        if institution_code:
            stmt = stmt.join(InstitutionType, Student.institution_type_id == InstitutionType.id)
            conds.append(InstitutionType.code == institution_code)
        if sede_ids is not None:
            conds.append(RotationAssignment.sede_id.in_(sede_ids) if sede_ids else False)
        if student_ids is not None:
            conds.append(RotationAssignment.student_id.in_(student_ids) if student_ids else False)
        if tutor_ids is not None:
            conds.append(RotationAssignment.tutor_id.in_(tutor_ids) if tutor_ids else False)
        if conds:
            stmt = stmt.where(and_(*conds))
        stmt = stmt.order_by(RotationAssignment.start_date.desc().nullslast(), Student.full_name)
        return list(self.db.execute(stmt).scalars().all())

    def active_assignments(self) -> list[RotationAssignment]:
        stmt = self._base_active().where(
            RotationAssignment.status == AssignmentStatus.ACTIVE.value
        )
        return list(self.db.execute(stmt).scalars().all())

    def ending_before(self, cutoff: date) -> list[RotationAssignment]:
        """Active assignments ending on/before the cutoff date."""
        stmt = self._base_active().where(
            and_(
                RotationAssignment.status == AssignmentStatus.ACTIVE.value,
                RotationAssignment.end_date.is_not(None),
                RotationAssignment.end_date <= cutoff,
            )
        )
        return list(self.db.execute(stmt).scalars().all())

    def missing_tutor(self) -> list[RotationAssignment]:
        stmt = self._base_active().where(
            and_(
                RotationAssignment.tutor_id.is_(None),
                RotationAssignment.status.in_(
                    [AssignmentStatus.ACTIVE.value, AssignmentStatus.PLANNED.value]
                ),
            )
        )
        return list(self.db.execute(stmt).scalars().all())

    def rotation_distribution(self) -> dict[str, int]:
        stmt = (
            select(RotationType.name, func.count(RotationAssignment.id))
            .join(RotationAssignment, RotationAssignment.rotation_type_id == RotationType.id)
            .where(RotationAssignment.is_deleted.is_(False))
            .group_by(RotationType.name)
        )
        return {name: int(count) for name, count in self.db.execute(stmt).all()}


class ActivityDefinitionRepository(BaseRepository[ActivityDefinition]):
    model = ActivityDefinition

    def get_by_code(self, code: str) -> ActivityDefinition | None:
        return self.db.execute(
            select(ActivityDefinition).where(ActivityDefinition.code == code)
        ).scalar_one_or_none()

    def for_rotation(self, rotation_type_id: int | None, *, active_only: bool = True) -> list[ActivityDefinition]:
        """Definitions applicable to a rotation: shared (rotation_type_id IS NULL)
        plus rotation-specific ones, ordered for display."""
        stmt = select(ActivityDefinition).where(
            (ActivityDefinition.rotation_type_id.is_(None))
            | (ActivityDefinition.rotation_type_id == rotation_type_id)
        )
        if active_only:
            stmt = stmt.where(ActivityDefinition.is_active.is_(True))
        stmt = stmt.order_by(ActivityDefinition.display_order, ActivityDefinition.name)
        return list(self.db.execute(stmt).scalars().all())

    def search(
        self,
        *,
        query: str | None = None,
        rotation_type_id: int | None = None,
        category: str | None = None,
        target_type: str | None = None,
        requires_verification: bool | None = None,
        active: bool | None = None,
        provisional: str | None = None,  # 'current' | 'provisional'
    ) -> list[ActivityDefinition]:
        stmt = select(ActivityDefinition).options(selectinload(ActivityDefinition.rotation_type))
        conds = []
        if query:
            like = f"%{query.strip().lower()}%"
            conds.append(func.lower(ActivityDefinition.code).like(like)
                        | func.lower(ActivityDefinition.name).like(like))
        if rotation_type_id is not None:
            conds.append(ActivityDefinition.rotation_type_id == rotation_type_id)
        if category:
            conds.append(ActivityDefinition.category == category)
        if target_type:
            conds.append(ActivityDefinition.target_type == target_type)
        if requires_verification is not None:
            conds.append(ActivityDefinition.requires_tutor_verification.is_(requires_verification))
        if active is not None:
            conds.append(ActivityDefinition.is_active.is_(active))
        if provisional == "current":
            conds.append(ActivityDefinition.is_provisional.is_(False))
        elif provisional == "provisional":
            conds.append(ActivityDefinition.is_provisional.is_(True))
        if conds:
            stmt = stmt.where(and_(*conds))
        stmt = stmt.order_by(ActivityDefinition.display_order, ActivityDefinition.name)
        return list(self.db.execute(stmt).scalars().all())

    def has_student_records(self, definition_id: int) -> bool:
        return int(self.db.execute(
            select(func.count(StudentActivity.id)).where(
                StudentActivity.definition_id == definition_id
            )
        ).scalar_one()) > 0


class StudentActivityRepository(BaseRepository[StudentActivity]):
    model = StudentActivity

    def _base(self):
        return select(StudentActivity).options(
            selectinload(StudentActivity.definition),
            selectinload(StudentActivity.student),
            selectinload(StudentActivity.assignment),
            selectinload(StudentActivity.reviews),
        )

    def get_full(self, activity_id: int) -> StudentActivity | None:
        return self.db.execute(
            self._base().where(StudentActivity.id == activity_id)
        ).scalar_one_or_none()

    def for_assignment(self, assignment_id: int) -> list[StudentActivity]:
        stmt = self._base().where(
            StudentActivity.assignment_id == assignment_id
        ).order_by(StudentActivity.created_at.desc())
        return list(self.db.execute(stmt).scalars().all())

    def for_student(self, student_id: int) -> list[StudentActivity]:
        stmt = self._base().where(
            StudentActivity.student_id == student_id
        ).order_by(StudentActivity.created_at.desc())
        return list(self.db.execute(stmt).scalars().all())

    def pending_for_tutor(self, tutor_id: int) -> list[StudentActivity]:
        stmt = (
            self._base()
            .join(RotationAssignment, StudentActivity.assignment_id == RotationAssignment.id)
            .where(
                and_(
                    RotationAssignment.tutor_id == tutor_id,
                    StudentActivity.verification_status == "pending",
                )
            )
            .order_by(StudentActivity.submitted_at)
        )
        return list(self.db.execute(stmt).scalars().all())

    def all_pending(self) -> list[StudentActivity]:
        stmt = self._base().where(StudentActivity.verification_status == "pending")
        return list(self.db.execute(stmt).scalars().all())

    def all_with_relations(self) -> list[StudentActivity]:
        return list(self.db.execute(self._base()).scalars().all())


class ActivityReviewRepository(BaseRepository[ActivityReview]):
    model = ActivityReview


class EvaluationRepository(BaseRepository[Evaluation]):
    model = Evaluation

    def pending(self) -> list[Evaluation]:
        stmt = (
            select(Evaluation)
            .options(
                selectinload(Evaluation.student),
                selectinload(Evaluation.assignment),
            )
            .where(
                and_(
                    Evaluation.status.in_(
                        [
                            EvaluationStatus.PENDING.value,
                            EvaluationStatus.IN_PROGRESS.value,
                        ]
                    ),
                    Evaluation.is_deleted.is_(False),
                )
            )
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_by_assignment(self, assignment_id: int) -> Evaluation | None:
        stmt = (
            select(Evaluation)
            .options(selectinload(Evaluation.criteria))
            .where(Evaluation.assignment_id == assignment_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def _base(self):
        return select(Evaluation).options(
            selectinload(Evaluation.student),
            selectinload(Evaluation.assignment),
            selectinload(Evaluation.criteria),
        ).where(Evaluation.is_deleted.is_(False))

    def get_full(self, evaluation_id: int) -> Evaluation | None:
        stmt = self._base().where(Evaluation.id == evaluation_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def search(
        self,
        *,
        status: str | None = None,
        tutor_id: int | None = None,
        student_id: int | None = None,
        sede_ids: set[int] | None = None,
        tutor_ids: set[int] | None = None,
        student_ids: set[int] | None = None,
    ) -> list[Evaluation]:
        stmt = self._base()
        conds = []
        if status:
            conds.append(Evaluation.status == status)
        if tutor_id is not None:
            conds.append(Evaluation.tutor_id == tutor_id)
        if student_id is not None:
            conds.append(Evaluation.student_id == student_id)
        if sede_ids is not None:
            stmt = stmt.join(RotationAssignment, Evaluation.assignment_id == RotationAssignment.id)
            conds.append(RotationAssignment.sede_id.in_(sede_ids) if sede_ids else False)
        if tutor_ids is not None:
            conds.append(Evaluation.tutor_id.in_(tutor_ids) if tutor_ids else False)
        if student_ids is not None:
            conds.append(Evaluation.student_id.in_(student_ids) if student_ids else False)
        if conds:
            stmt = stmt.where(and_(*conds))
        stmt = stmt.order_by(Evaluation.updated_at.desc())
        return list(self.db.execute(stmt).scalars().all())

    def submitted_count_for_sede(self, sede_ids: set[int]) -> int:
        if not sede_ids:
            return 0
        stmt = (
            select(func.count(Evaluation.id))
            .join(RotationAssignment, Evaluation.assignment_id == RotationAssignment.id)
            .where(and_(Evaluation.status == EvaluationStatus.SUBMITTED.value,
                       RotationAssignment.sede_id.in_(sede_ids),
                       Evaluation.is_deleted.is_(False)))
        )
        return int(self.db.execute(stmt).scalar_one())


class AlertRepository(BaseRepository[Alert]):
    model = Alert

    def open_by_category(self, category: str) -> list[Alert]:
        stmt = select(Alert).where(
            and_(
                Alert.category == category,
                Alert.status == AlertStatus.OPEN.value,
                Alert.is_deleted.is_(False),
            )
        )
        return list(self.db.execute(stmt).scalars().all())

    def open_alerts(self) -> list[Alert]:
        stmt = (
            select(Alert)
            .where(
                and_(
                    Alert.status == AlertStatus.OPEN.value,
                    Alert.is_deleted.is_(False),
                )
            )
            .order_by(Alert.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def exists_open(self, category: str, entity_type: str, entity_id: int | None) -> bool:
        """Return True if an equivalent open alert already exists (dedup)."""
        stmt = select(func.count(Alert.id)).where(
            and_(
                Alert.category == category,
                Alert.related_entity_type == entity_type,
                Alert.related_entity_id == entity_id,
                Alert.status == AlertStatus.OPEN.value,
                Alert.is_deleted.is_(False),
            )
        )
        return int(self.db.execute(stmt).scalar_one()) > 0


class DocumentRepository(BaseRepository[DocumentRecord]):
    model = DocumentRecord


class IncidentRepository(BaseRepository[Incident]):
    model = Incident

    def open_incidents(self) -> list[Incident]:
        stmt = select(Incident).where(Incident.is_deleted.is_(False))
        return list(self.db.execute(stmt).scalars().all())


class AgentExecutionRepository(BaseRepository[AgentExecution]):
    model = AgentExecution

    def recent(self, limit: int = 10) -> list[AgentExecution]:
        stmt = (
            select(AgentExecution)
            .order_by(AgentExecution.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())


class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog

    def recent(self, limit: int = 50) -> list[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars().all())


class RepositoryBundle:
    """Convenience aggregate that constructs all repositories for a session."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.roles = RoleRepository(db)
        self.institution_types = InstitutionTypeRepository(db)
        self.sedes = SedeRepository(db)
        self.students = StudentRepository(db)
        self.tutors = TutorRepository(db)
        self.sede_coordinators = SedeCoordinatorRepository(db)
        self.rotation_types = RotationTypeRepository(db)
        self.periods = AcademicPeriodRepository(db)
        self.assignments = RotationAssignmentRepository(db)
        self.activity_definitions = ActivityDefinitionRepository(db)
        self.student_activities = StudentActivityRepository(db)
        self.activity_reviews = ActivityReviewRepository(db)
        self.evaluations = EvaluationRepository(db)
        self.alerts = AlertRepository(db)
        self.documents = DocumentRepository(db)
        self.incidents = IncidentRepository(db)
        self.agent_executions = AgentExecutionRepository(db)
        self.audit_logs = AuditLogRepository(db)
