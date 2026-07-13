"""Aggregate model imports.

Importing this package registers every ORM model on ``Base.metadata`` so that
``init_db`` can create the full schema in a single call. Keep every model
class exported here.
"""

from app.models.academic import AcademicPeriod, RotationAssignment, RotationType
from app.models.activity import ActivityDefinition, ActivityReview, StudentActivity
from app.models.audit import AgentExecution, AuditLog
from app.models.evaluation import Evaluation, EvaluationCriterion
from app.models.operations import Alert, DocumentRecord, Incident
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
    "Evaluation",
    "EvaluationCriterion",
    "Alert",
    "DocumentRecord",
    "Incident",
    "InstitutionType",
    "Sede",
    "SedeCoordinatorProfile",
    "TutorProfile",
    "Student",
    "Role",
    "User",
]
