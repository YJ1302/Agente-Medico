"""Academic period management — the yearly rollover workflow.

The internship calendar is divided into six bimonthly ``AcademicPeriod`` blocks
(Ene-Feb … Nov-Dic). At year end the coordination does **not** delete anything:
interns, sedes, tutors, coordinators, rotation types and user accounts all carry
over untouched. Only period-scoped records (rotation assignments and the
evaluations attached to them) are created fresh against the new year's periods.

This service lets an Administrator or University Coordinator:

* create the next year's six periods in one action (``generate_year``),
* add / edit a single period,
* mark which period is the *current* one (drives ``AcademicPeriodRepository.
  current()`` and the default filters across the platform),
* delete an empty period (blocked once any rotation references it).

Everything mutating is scoped to global viewers and writes an audit entry, in
line with the rest of the codebase (see ``sede_service.py``).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.authorization import ensure, is_global_viewer
from app.models.academic import AcademicPeriod
from app.repositories.repositories import RepositoryBundle
from app.services import audit_service as audit
from app.services.audit_service import AuditService
from app.services.auth_service import Identity
from app.services.validators import FieldValidator, ValidationError

# The six official bimonthly blocks: (name, code prefix, ordinal, start, end).
# ``start``/``end`` are (month, day) tuples applied to whichever year is chosen.
STANDARD_BIMESTERS: list[tuple[str, str, int, tuple[int, int], tuple[int, int]]] = [
    ("Enero - Febrero", "ENE-FEB", 1, (1, 1), (2, 28)),
    ("Marzo - Abril", "MAR-ABR", 2, (3, 1), (4, 30)),
    ("Mayo - Junio", "MAY-JUN", 3, (5, 1), (6, 30)),
    ("Julio - Agosto", "JUL-AGO", 4, (7, 1), (8, 31)),
    ("Setiembre - Octubre", "SET-OCT", 5, (9, 1), (10, 31)),
    ("Noviembre - Diciembre", "NOV-DIC", 6, (11, 1), (12, 31)),
]

MIN_YEAR = 2000
MAX_YEAR = 2100


class PeriodService:
    def __init__(self, db: Session, identity: Identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)
        self.audit = AuditService(db)

    # -- scope ----------------------------------------------------------------
    def can_manage(self) -> bool:
        """Only Administrator and University Coordinator manage the calendar."""
        return is_global_viewer(self.identity)

    def _ensure_manage(self, reason: str) -> None:
        ensure(self.can_manage(), "No puede gestionar los periodos académicos.", reason)

    # -- listing ------------------------------------------------------------
    def list_by_year(self) -> list[dict]:
        """All periods grouped by year, newest year first, with usage counts."""
        periods = self.repos.periods.ordered()
        by_year: dict[int, list[AcademicPeriod]] = {}
        for p in periods:
            by_year.setdefault(p.year, []).append(p)
        groups = []
        for year in sorted(by_year, reverse=True):
            rows = [
                {"period": p, "assignments": self.repos.periods.assignment_count(p.id)}
                for p in by_year[year]
            ]
            groups.append({
                "year": year,
                "rows": rows,
                "has_current": any(r["period"].is_current for r in rows),
                "complete": len(rows) >= len(STANDARD_BIMESTERS),
            })
        return groups

    def get(self, period_id: int) -> AcademicPeriod:
        p = self.repos.periods.get(period_id)
        ensure(p is not None, "Periodo no encontrado.", "not_found")
        return p

    def next_year_suggestion(self) -> int:
        latest = self.repos.periods.latest()
        return (latest.year + 1) if latest else date.today().year

    # -- validation -------------------------------------------------------
    def _validate(self, data: dict, *, existing: AcademicPeriod | None) -> dict:
        v = FieldValidator()
        name = " ".join((data.get("name") or "").split())
        code = " ".join((data.get("code") or "").split()).upper()
        if not name:
            v.add("name", "El nombre es obligatorio.")
        if not code:
            v.add("code", "El código es obligatorio.")
        year = v.int_field("year", data.get("year"), "El año", min_v=MIN_YEAR,
                           max_v=MAX_YEAR)
        if not year:
            v.add("year", "El año es obligatorio.")
        ordinal = v.int_field("ordinal", data.get("ordinal"), "El orden",
                              min_v=1, max_v=len(STANDARD_BIMESTERS))
        if not ordinal:
            v.add("ordinal", f"El orden debe estar entre 1 y {len(STANDARD_BIMESTERS)}.")
        start = v.date("start_date", data.get("start_date"), "La fecha de inicio")
        end = v.date("end_date", data.get("end_date"), "La fecha de término")
        if not start:
            v.add("start_date", "La fecha de inicio es obligatoria.")
        if not end:
            v.add("end_date", "La fecha de término es obligatoria.")
        if start and end and end <= start:
            v.add("end_date", "La fecha de término debe ser posterior a la de inicio.")

        if code:
            dup = self.repos.periods.by_code(code)
            if dup and (existing is None or dup.id != existing.id):
                v.add("code", "Ya existe un periodo con ese código.")
        if year and ordinal:
            clash = next((p for p in self.repos.periods.for_year(year)
                          if p.ordinal == ordinal
                          and (existing is None or p.id != existing.id)), None)
            if clash:
                v.add("ordinal", f"El año {year} ya tiene un periodo con orden {ordinal}.")

        v.raise_if_errors()
        return {"name": name, "code": code, "year": year, "ordinal": ordinal,
                "start_date": start, "end_date": end}

    # -- mutations -------------------------------------------------------
    def create(self, data: dict, ip: str | None = None) -> AcademicPeriod:
        self._ensure_manage("create_period_denied")
        clean = self._validate(data, existing=None)
        period = AcademicPeriod(is_current=False, **clean)
        self.db.add(period)
        self.db.flush()
        self.audit.record(audit.CREATE_ACADEMIC_PERIOD, identity=self.identity,
                          entity_type="academic_period", entity_id=period.id,
                          detail={"code": period.code}, ip_address=ip, commit=False)
        self.db.commit()
        return period

    def update(self, period_id: int, data: dict, ip: str | None = None) -> AcademicPeriod:
        self._ensure_manage("edit_period_denied")
        period = self.get(period_id)
        clean = self._validate(data, existing=period)
        for field, value in clean.items():
            setattr(period, field, value)
        self.db.flush()
        self.audit.record(audit.UPDATE_ACADEMIC_PERIOD, identity=self.identity,
                          entity_type="academic_period", entity_id=period.id,
                          detail={"code": period.code}, ip_address=ip, commit=False)
        self.db.commit()
        return period

    def set_current(self, period_id: int, ip: str | None = None) -> AcademicPeriod:
        self._ensure_manage("set_current_period_denied")
        period = self.get(period_id)
        if not period.is_current:
            self.repos.periods.clear_current()
            period.is_current = True
        self.db.flush()
        self.audit.record(audit.SET_CURRENT_ACADEMIC_PERIOD, identity=self.identity,
                          entity_type="academic_period", entity_id=period.id,
                          detail={"code": period.code}, ip_address=ip, commit=False)
        self.db.commit()
        return period

    def delete(self, period_id: int, ip: str | None = None) -> None:
        self._ensure_manage("delete_period_denied")
        period = self.get(period_id)
        used = self.repos.periods.assignment_count(period.id)
        if used:
            raise ValidationError({"period": f"No se puede eliminar: el periodo tiene "
                                             f"{used} rotación(es) asociada(s)."})
        if period.is_current:
            raise ValidationError({"period": "No se puede eliminar el periodo actual. "
                                             "Marque otro periodo como actual primero."})
        code = period.code
        self.db.delete(period)
        self.db.flush()
        self.audit.record(audit.DELETE_ACADEMIC_PERIOD, identity=self.identity,
                          entity_type="academic_period", entity_id=period_id,
                          detail={"code": code}, ip_address=ip, commit=False)
        self.db.commit()

    def generate_year(self, year: int, ip: str | None = None,
                      set_current: bool = False) -> dict:
        """Create every still-missing standard bimester for ``year``.

        Idempotent: an existing code is left untouched, so re-running only fills
        gaps. Returns ``{"created": [...codes], "skipped": [...codes]}``.
        """
        self._ensure_manage("generate_year_denied")
        v = FieldValidator()
        y = v.int_field("year", str(year), "El año", min_v=MIN_YEAR, max_v=MAX_YEAR)
        v.raise_if_errors()
        assert y is not None

        created: list[str] = []
        skipped: list[str] = []
        first_new: AcademicPeriod | None = None
        for name, prefix, ordinal, (sm, sd), (em, ed) in STANDARD_BIMESTERS:
            code = f"{prefix}-{y}"
            if self.repos.periods.by_code(code):
                skipped.append(code)
                continue
            period = AcademicPeriod(
                name=f"{name} {y}", code=code, year=y, ordinal=ordinal,
                start_date=date(y, sm, sd), end_date=date(y, em, ed),
                is_current=False,
            )
            self.db.add(period)
            created.append(code)
            if first_new is None:
                first_new = period

        if not created:
            raise ValidationError({"year": f"El año {y} ya tiene sus seis periodos."})

        self.db.flush()
        if set_current and first_new is not None:
            self.repos.periods.clear_current()
            first_new.is_current = True
        self.audit.record(audit.GENERATE_ACADEMIC_YEAR, identity=self.identity,
                          entity_type="academic_period",
                          entity_id=first_new.id if first_new else None,
                          detail={"year": y, "created": ",".join(created),
                                  "set_current": bool(set_current and first_new)},
                          ip_address=ip, commit=False)
        self.db.commit()
        return {"created": created, "skipped": skipped}
