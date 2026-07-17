"""Planning agent — mock reasoning about rotation scheduling coverage.

Part 1 uses deterministic mock logic (no AI): it inspects assignments per
period and per rotation type and flags coverage gaps as recommendations for a
human planner. The interface is ready for an LLM-backed planner later.
"""

from __future__ import annotations

import time
from typing import Any

from app.agents.base_agent import AgentFinding, AgentResponse, BaseAgent
from app.models.base import AgentStatus
from app.repositories.repositories import RepositoryBundle


class PlanningAgent(BaseAgent):
    name = "planning_agent"
    description = (
        "Analiza la cobertura de rotaciones por periodo y tipo, y propone "
        "ajustes de planificación sujetos a aprobación humana."
    )

    def run(self, context: dict[str, Any]) -> AgentResponse:
        started = time.perf_counter()
        repos: RepositoryBundle = context["repos"]

        distribution = repos.assignments.rotation_distribution()
        rotation_types = repos.rotation_types.list()
        findings: list[AgentFinding] = []

        # Mock rule: a core rotation with zero assignments is a coverage gap.
        for rt in rotation_types:
            if rt.is_core and distribution.get(rt.name, 0) == 0:
                findings.append(
                    AgentFinding(
                        code="coverage_gap",
                        title="Rotación core sin asignaciones",
                        detail=f"La rotación '{rt.name}' no tiene asignaciones activas.",
                        severity="warning",
                        entity_type="rotation_type",
                        entity_id=rt.id,
                    )
                )

        duration_ms = int((time.perf_counter() - started) * 1000)
        total = sum(distribution.values())

        if not findings:
            return self._response(
                task="analyze_rotation_coverage",
                status=AgentStatus.SUCCESS.value,
                summary=(
                    f"Cobertura de rotaciones equilibrada sobre {total} asignación(es). "
                    "Sin brechas detectadas."
                ),
                recommended_actions=[
                    "Mantener el cronograma actual.",
                    "Revisar proyecciones para el siguiente bimestre.",
                ],
                requires_human_approval=True,
                duration_ms=duration_ms,
            )

        return self._response(
            task="analyze_rotation_coverage",
            status=AgentStatus.NEEDS_REVIEW.value,
            summary=f"Se identificaron {len(findings)} brecha(s) de cobertura.",
            findings=findings,
            recommended_actions=[
                "Balancear asignaciones entre rotaciones core.",
                "Coordinar con las sedes la apertura de cupos faltantes.",
            ],
            requires_human_approval=True,
            duration_ms=duration_ms,
        )
