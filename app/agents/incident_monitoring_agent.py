"""Incident monitoring agent — deterministic triage of incidents (Batch 2E).

Summarizes open incidents by severity/status, highlights critical and overdue
cases, and recommends human follow-up. It never resolves, closes, dismisses or
otherwise mutates an incident — detection and recommendation only.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

from app.agents.base_agent import AgentFinding, AgentResponse, BaseAgent
from app.models.base import AgentStatus, IncidentSeverity, IncidentStatus
from app.repositories.repositories import RepositoryBundle

_TERMINAL = {IncidentStatus.CLOSED.value, IncidentStatus.DISMISSED.value}


class IncidentMonitoringAgent(BaseAgent):
    name = "incident_monitoring_agent"
    description = (
        "Monitorea incidencias abiertas: prioriza las críticas y vencidas y "
        "recomienda seguimiento humano. No resuelve ni cierra incidencias."
    )

    def run(self, context: dict[str, Any]) -> AgentResponse:
        started = time.perf_counter()
        repos: RepositoryBundle = context["repos"]
        today: date = context.get("today") or date.today()

        findings: list[AgentFinding] = []
        for inc in repos.incidents.all_active():
            if inc.status in _TERMINAL:
                continue
            critical = inc.severity == IncidentSeverity.CRITICAL.value
            overdue = inc.due_date and inc.due_date < today \
                and inc.status != IncidentStatus.RESOLVED.value
            if critical:
                findings.append(AgentFinding(
                    code="critical_incident", title=f"[{inc.code}] Incidencia crítica",
                    detail=f"{inc.title} — requiere atención prioritaria.",
                    severity="critical", entity_type="incident", entity_id=inc.id))
            elif inc.severity == IncidentSeverity.HIGH.value:
                findings.append(AgentFinding(
                    code="high_severity_incident", title=f"[{inc.code}] Severidad alta",
                    detail=f"{inc.title} — sin resolver.",
                    severity="warning", entity_type="incident", entity_id=inc.id))
            if overdue:
                findings.append(AgentFinding(
                    code="incident_overdue", title=f"[{inc.code}] Incidencia vencida",
                    detail=f"{inc.title} — venció el {inc.due_date:%d/%m/%Y}.",
                    severity="critical", entity_type="incident", entity_id=inc.id))

        duration_ms = int((time.perf_counter() - started) * 1000)
        if not findings:
            return self._response(
                task="monitor_incidents", status=AgentStatus.NO_FINDINGS.value,
                summary="No hay incidencias críticas o vencidas abiertas.",
                requires_human_approval=False, duration_ms=duration_ms)
        return self._response(
            task="monitor_incidents", status=AgentStatus.NEEDS_REVIEW.value,
            summary=f"{len(findings)} incidencia(s) requieren seguimiento humano.",
            findings=findings,
            recommended_actions=[
                "Atender primero las incidencias críticas y vencidas.",
                "Asignar un responsable y una fecha límite a cada incidencia abierta.",
                "Registrar la resolución antes de cerrar cualquier incidencia.",
            ],
            requires_human_approval=True, duration_ms=duration_ms)
