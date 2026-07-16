"""Aggregate model imports.

Importing this package registers every ORM model on ``Base.metadata`` so that
``init_db`` can create the full schema in a single call. Keep every model
class exported here.
"""

from app.models.academic import AcademicPeriod, RotationAssignment, RotationType
from app.models.activity import ActivityDefinition, ActivityReview, StudentActivity
from app.models.audit import AgentExecution, AuditLog
from app.models.grades import (
    GradeComponentDefinition,
    GradeComponentHistory,
    GradeScheme,
    StudentGradeComponent,
)
from app.models.imports import ImportBatch, ImportRow
from app.models.evaluation import Evaluation, EvaluationCriterion
from app.models.operations import (
    Alert,
    Attachment,
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
from app.models.user import Role, User

__all__ = [
    "AcademicPeriod",
    "RotationAssignment",
    "RotationType",
    "ActivityDefinition",
    "ActivityReview",
    "StudentActivity",
    "AgentExecution",
    "AuditLog",
    "GradeComponentDefinition",
    "GradeComponentHistory",
    "GradeScheme",
    "StudentGradeComponent",
    "ImportBatch",
    "ImportRow",
    "Evaluation",
    "EvaluationCriterion",
    "Alert",
    "Attachment",
    "DocumentRecord",
    "DocumentSequence",
    "DocumentTemplate",
    "Incident",
    "StatusHistory",
    "InstitutionType",
    "Sede",
    "SedeCoordinatorProfile",
    "TutorProfile",
    "Student",
    "Role",
    "User",
]
