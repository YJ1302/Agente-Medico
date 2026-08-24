"""Admin-only account & role management: list users, grant/revoke roles.

Sede Coordinator and Tutor grants delegate to ``CoordinatorService.create()``
/ ``TutorService.create()`` (via ``existing_user=``) since those roles need a
profile row (sede, specialty) — the same validation and profile-creation
logic already used for brand-new accounts and for bulk import. Admin and
University Coordinator carry no profile row, so they're granted/revoked
directly here.

Student is intentionally not managed from this screen: a Student record can
pre-exist without a login (bulk-imported before an account is provisioned),
and account creation for one flows through the "Crear cuenta" action on the
student detail page instead — a different linking pattern than the other
roles, kept separate rather than forced into this one.
"""

from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from app.authorization import ensure, is_admin
from app.config import settings
from app.models.user import (
    ROLE_ADMIN,
    ROLE_SEDE_COORDINATOR,
    ROLE_TUTOR,
    ROLE_UNIVERSITY_COORDINATOR,
    User,
)
from app.repositories.repositories import RepositoryBundle
from app.security import hash_password
from app.services import audit_service as audit
from app.services.audit_service import AuditService
from app.services.auth_service import Identity
from app.services.validators import FieldValidator, ValidationError

# Roles manageable from the Users & Roles screen (see module docstring for
# why Student is excluded).
MANAGED_ROLE_CODES = (ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR, ROLE_TUTOR)
# Roles with no profile row — granted/revoked directly, no extra fields.
PROFILE_FREE_ROLES = {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR}
# Roles that need a profile row (Sede Coordinator/Tutor create() handles
# creating it) — granting these always needs sede_id at minimum.
PROFILE_ROLES = {ROLE_SEDE_COORDINATOR, ROLE_TUTOR}


class UserAdminService:
    def __init__(self, db: Session, identity: Identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)
        self.audit = AuditService(db)

    def can_manage(self) -> bool:
        return is_admin(self.identity)

    def list_users(self, query: str | None = None) -> list[User]:
        return self.repos.users.search(query)

    def get(self, user_id: int) -> User | None:
        return self.repos.users.get(user_id)

    def roles_for(self, user: User) -> list:
        return self.repos.user_roles.roles_for_user(user.id)

    def create_profile_free_user(self, data: dict, role_code: str,
                                 ip: str | None = None) -> tuple[User, str]:
        """Create a brand-new account holding a profile-free role (Admin or
        University Coordinator) — the counterpart to ``CoordinatorService.create()``
        / ``TutorService.create()`` for roles that carry no profile row.
        Returns (user, generated_password) so the caller can show the
        temporary password once, same as the other staff-creation flows.
        """
        ensure(self.can_manage(), "No puede crear usuarios.", "create_user_denied")
        if role_code not in PROFILE_FREE_ROLES:
            raise ValidationError({"role": "Este rol requiere datos adicionales (sede)."})
        v = FieldValidator()
        full_name = v.required("full_name", data.get("full_name"), "El nombre")
        email = v.email("email", data.get("email"))
        if not email:
            v.add("email", "El correo es obligatorio.")
        elif self.repos.users.get_by_email(email) is not None:
            v.add("email", "El correo ya está registrado.")
        v.raise_if_errors()
        phone = (data.get("phone") or "").strip() or None

        role = self.repos.roles.get_by_code(role_code)
        ensure(role is not None, "Rol no configurado.", "role_missing")
        password = (data.get("password") or "").strip()
        generated = ""
        if not password:
            password = "Demo123!" if settings.demo_mode else secrets.token_urlsafe(9)
            generated = password
        user = User(email=email, full_name=full_name, phone=phone,
                    hashed_password=hash_password(password), role_id=role.id)
        self.repos.users.add(user)
        self.db.flush()
        self.repos.user_roles.grant(user.id, role.id)
        self.audit.record(audit.CREATE_USER, identity=self.identity, entity_type="user",
                          entity_id=user.id, detail={"email": email, "role": role_code},
                          ip_address=ip, commit=False)
        self.db.commit()
        return user, generated

    def grant_profile_free_role(self, user_id: int, role_code: str,
                                ip: str | None = None) -> None:
        ensure(self.can_manage(), "No autorizado.", "grant_role_denied")
        if role_code not in PROFILE_FREE_ROLES:
            raise ValidationError({"role": "Este rol requiere datos adicionales (sede)."})
        user = self.repos.users.get(user_id)
        if user is None:
            raise ValidationError({"user": "Usuario no encontrado."})
        role = self.repos.roles.get_by_code(role_code)
        if role is None:
            raise ValidationError({"role": "Rol no configurado."})
        granted = self.repos.user_roles.grant(user_id, role.id)
        if granted is not None:
            self.audit.record(audit.GRANT_ROLE, identity=self.identity, entity_type="user",
                              entity_id=user_id, detail={"role": role_code},
                              ip_address=ip, commit=False)
            self.db.commit()

    def revoke_role(self, user_id: int, role_code: str, ip: str | None = None) -> None:
        ensure(self.can_manage(), "No autorizado.", "revoke_role_denied")
        user = self.repos.users.get(user_id)
        if user is None:
            raise ValidationError({"user": "Usuario no encontrado."})
        role = self.repos.roles.get_by_code(role_code)
        if role is None:
            raise ValidationError({"role": "Rol no configurado."})
        current = self.roles_for(user)
        if role_code not in {r.code for r in current}:
            raise ValidationError({"role": "La cuenta no tiene ese rol."})
        if len(current) <= 1:
            raise ValidationError({"role": "La cuenta debe conservar al menos un rol."})
        self.repos.user_roles.revoke(user_id, role.id)
        # Deactivate (never delete) the associated profile so evaluation and
        # rotation history tied to it stays intact.
        if role_code == ROLE_SEDE_COORDINATOR and user.sede_coordinator_profile:
            user.sede_coordinator_profile.is_active = False
        if role_code == ROLE_TUTOR and user.tutor_profile:
            user.tutor_profile.is_active = False
        self.db.flush()
        self.audit.record(audit.REVOKE_ROLE, identity=self.identity, entity_type="user",
                          entity_id=user_id, detail={"role": role_code},
                          ip_address=ip, commit=False)
        self.db.commit()
