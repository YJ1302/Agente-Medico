"""Document agent — deterministic triage of formal communications (Batch 2E).

No LLM, no randomness. The agent inspects current document state and produces:

* documents awaiting review (submitted),
* rejected documents awaiting correction,
* overdue documents (stuck in gestión beyond the configured window),

and recommends the next responsible role for each. CRITICAL RULE: the agent
never approves, rejects, sends or otherwise mutates a document — every action
requires explicit human approval (SECURITY_AND_PRIVACY_RULES.md).
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

from app.agents.base_agent import AgentFinding, AgentResponse, BaseAgent
from app.config import settings
from app.models.base import AgentStatus, DocumentStatus
from app.repositories.repositories import RepositoryBundle

# doc status -> next responsible role (recommendation only).
_NEXT_ROLE = {
    DocumentStatus.DRAFT.value: "Autor (completar y enviar)",
    DocumentStatus.SUBMITTED.value: "Coordinador de Sede / Universitario (iniciar revisión)",
    DocumentStatus.UNDER_REVIEW.value: "Coordinador Universitario (aprobar o rechazar)",
    DocumentStatus.REJECTED.value: "Autor (corregir y reenviar)",
    DocumentStatus.APPROVED.value: "Coordinador Universitario (archivar)",
}


class DocumentAgent(BaseAgent):
    name = "document_agent"
    description = (
        "Triage determinista de documentos formales: identifica documentos en "
        "espera de revisión, rechazados sin corregir y vencidos, y recomienda el "
        "siguiente rol responsable. Nunca envía ni aprueba documentos."
    )

    def run(self, context: dict[str, Any]) -> AgentResponse:
        started = time.perf_counter()
        repos: RepositoryBundle = context["repos"]
        today: date = context.get("today") or date.today()
        overdue_cutoff = today - timedelta(days=settings.document_overdue_days)

        findings: list[AgentFinding] = []
        for d in repos.documents.all_active():
            if d.status == DocumentStatus.SUBMITTED.value:
                findings.append(AgentFinding(
                    code="document_waiting_review",
                    title=f"[{d.code}] En espera de revisión",
                    detail=f"{d.title} — próximo responsable: {_NEXT_ROLE[d.status]}.",
                    severity="info", entity_type="document", entity_id=d.id))
            elif d.status == DocumentStatus.REJECTED.value:
                findings.append(AgentFinding(
                    code="document_rejected_pending_correction",
                    title=f"[{d.code}] Rechazado sin corregir",
                    detail=f"{d.title} — próximo responsable: {_NEXT_ROLE[d.status]}.",
                    severity="warning", entity_type="document", entity_id=d.id))
            # Overdue (independent of the above buckets).
            if d.status in (DocumentStatus.SUBMITTED.value, DocumentStatus.UNDER_REVIEW.value):
                stale = d.submitted_at and d.submitted_at.date() <= overdue_cutoff
                past_due = d.due_date and d.due_date < today
                if stale or past_due:
                    findings.append(AgentFinding(
                        code="document_overdue",
                        title=f"[{d.code}] Documento vencido en gestión",
                        detail=f"{d.title} — requiere decisión ({_NEXT_ROLE.get(d.status, '—')}).",
                        severity="critical", entity_type="document", entity_id=d.id))

        duration_ms = int((time.perf_counter() - started) * 1000)
        if not findings:
            return self._response(
                task="triage_documents", status=AgentStatus.NO_FINDINGS.value,
                summary="No hay documentos pendientes de gestión.",
                requires_human_approval=False, duration_ms=duration_ms)

        recommendations = [
            "Revisar los documentos en espera y decidir manualmente (aprobar/rechazar).",
            "Priorizar los documentos vencidos y rechazados sin corregir.",
            "Confirmar la ruta de comunicación sede → universidad antes de cualquier envío.",
        ]
        return self._response(
            task="triage_documents", status=AgentStatus.NEEDS_REVIEW.value,
            summary=f"{len(findings)} documento(s) requieren seguimiento humano.",
            findings=findings, recommended_actions=recommendations,
            requires_human_approval=True, duration_ms=duration_ms)
