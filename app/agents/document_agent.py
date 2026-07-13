"""Document agent — mock drafting/triage of formal communications.

Deterministic mock logic: reports documents that are stuck in non-terminal
statuses and drafts a suggested next step. CRITICAL RULE (enforced by the
platform): no final institutional communication is ever sent automatically by
an agent — every send requires explicit human approval.
"""

from __future__ import annotations

import time
from typing import Any

from app.agents.base_agent import AgentFinding, AgentResponse, BaseAgent
from app.models.base import AgentStatus, DocumentStatus
from app.repositories.repositories import RepositoryBundle

_OPEN_STATUSES = {
    DocumentStatus.DRAFT.value,
    DocumentStatus.SUBMITTED.value,
    DocumentStatus.UNDER_REVIEW.value,
}


class DocumentAgent(BaseAgent):
    name = "document_agent"
    description = (
        "Triages formal documents in non-terminal statuses and drafts next "
        "steps. Never sends communications without human approval."
    )

    def run(self, context: dict[str, Any]) -> AgentResponse:
        started = time.perf_counter()
        repos: RepositoryBundle = context["repos"]

        pending_docs = [
            d for d in repos.documents.list() if d.status in _OPEN_STATUSES
        ]
        findings: list[AgentFinding] = [
            AgentFinding(
                code="document_in_progress",
                title=f"Documento en estado '{d.status}'",
                detail=f"[{d.code}] {d.title} — requiere seguimiento.",
                severity="info",
                entity_type="document",
                entity_id=d.id,
            )
            for d in pending_docs
        ]
        duration_ms = int((time.perf_counter() - started) * 1000)

        if not findings:
            return self._response(
                task="triage_documents",
                status=AgentStatus.NO_FINDINGS.value,
                summary="No hay documentos pendientes de gestión.",
                requires_human_approval=False,
                duration_ms=duration_ms,
            )

        return self._response(
            task="triage_documents",
            status=AgentStatus.NEEDS_REVIEW.value,
            summary=f"{len(findings)} documento(s) requieren seguimiento.",
            findings=findings,
            recommended_actions=[
                "Revisar y aprobar el envío manualmente.",
                "Confirmar la ruta de comunicación sede → universidad.",
            ],
            # Explicitly true — sending is a human decision.
            requires_human_approval=True,
            duration_ms=duration_ms,
        )
