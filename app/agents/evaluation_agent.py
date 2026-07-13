"""Evaluation agent — mock analysis of evaluation completeness.

Deterministic mock logic: counts pending evaluations and recommends follow-up.
A future version could summarize qualitative comments or detect scoring
anomalies with an LLM, but any resulting decision still requires human approval.
"""

from __future__ import annotations

import time
from typing import Any

from app.agents.base_agent import AgentFinding, AgentResponse, BaseAgent
from app.models.base import AgentStatus
from app.repositories.repositories import RepositoryBundle


class EvaluationAgent(BaseAgent):
    name = "evaluation_agent"
    description = (
        "Reviews rotation evaluations, flags pending submissions and prepares "
        "consolidation summaries for human approval."
    )

    def run(self, context: dict[str, Any]) -> AgentResponse:
        started = time.perf_counter()
        repos: RepositoryBundle = context["repos"]

        pending = repos.evaluations.pending()
        findings: list[AgentFinding] = [
            AgentFinding(
                code="pending_evaluation",
                title="Evaluación pendiente de envío",
                detail=(
                    f"{ev.student.full_name if ev.student else 'Interno'}: "
                    "la evaluación de fin de rotación aún no ha sido enviada."
                ),
                severity="warning",
                entity_type="evaluation",
                entity_id=ev.id,
            )
            for ev in pending
        ]
        duration_ms = int((time.perf_counter() - started) * 1000)

        if not findings:
            return self._response(
                task="review_evaluations",
                status=AgentStatus.NO_FINDINGS.value,
                summary="Todas las evaluaciones están al día.",
                requires_human_approval=False,
                duration_ms=duration_ms,
            )

        return self._response(
            task="review_evaluations",
            status=AgentStatus.NEEDS_REVIEW.value,
            summary=f"Hay {len(findings)} evaluación(es) pendiente(s) de envío.",
            findings=findings,
            recommended_actions=[
                "Notificar a los tutores responsables (con aprobación del coordinador).",
                "Verificar plazos de cierre de rotación.",
            ],
            requires_human_approval=True,
            duration_ms=duration_ms,
        )
