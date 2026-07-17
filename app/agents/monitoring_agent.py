"""Monitoring agent — surfaces operational risks from deterministic rules.

This agent wraps the ``RuleEngine``: it runs every rule, converts the findings
into a structured ``AgentResponse`` and proposes human-review actions. It never
resolves anything itself — detection and recommendation only.
"""

from __future__ import annotations

import time
from typing import Any

from app.agents.base_agent import AgentResponse, BaseAgent
from app.agents.rule_engine import RuleEngine
from app.models.base import AgentStatus
from app.repositories.repositories import RepositoryBundle


class MonitoringAgent(BaseAgent):
    name = "monitoring_agent"
    description = (
        "Ejecuta reglas de negocio deterministas para detectar rotaciones por "
        "finalizar, tutores faltantes, evaluaciones pendientes y perfiles "
        "incompletos."
    )

    def run(self, context: dict[str, Any]) -> AgentResponse:
        started = time.perf_counter()
        repos: RepositoryBundle = context["repos"]
        engine = RuleEngine(repos)
        findings = engine.run_all(today=context.get("today"))

        duration_ms = int((time.perf_counter() - started) * 1000)

        if not findings:
            return self._response(
                task="monitor_operational_risks",
                status=AgentStatus.NO_FINDINGS.value,
                summary="No se detectaron incidencias en las reglas de negocio.",
                requires_human_approval=False,
                duration_ms=duration_ms,
            )

        critical = [f for f in findings if f.severity == "critical"]
        actions = [
            "Revisar cada hallazgo en el panel de Alertas.",
            "Asignar responsables para las rotaciones sin tutor.",
            "Confirmar el envío de evaluaciones pendientes a los tutores.",
        ]
        summary = (
            f"Se detectaron {len(findings)} incidencia(s), "
            f"{len(critical)} crítica(s), que requieren revisión humana."
        )
        return self._response(
            task="monitor_operational_risks",
            status=AgentStatus.NEEDS_REVIEW.value,
            summary=summary,
            findings=findings,
            recommended_actions=actions,
            requires_human_approval=True,
            duration_ms=duration_ms,
        )
