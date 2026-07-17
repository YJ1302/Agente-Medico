"""Agent orchestrator — routes a task to the right agent and persists results.

The orchestrator is the single entry point the service layer uses to run
agents. It:
  * maintains a registry of available agents,
  * routes a task name to the matching agent,
  * persists every execution to ``AgentExecution`` (transparency requirement),
  * returns the structured ``AgentResponse`` to the caller.

No agent output is auto-actioned; the caller/human decides what to do with the
recommendations.
"""

from __future__ import annotations

from typing import Any

from app.agents.base_agent import AgentResponse, BaseAgent
from app.agents.document_agent import DocumentAgent
from app.agents.evaluation_agent import EvaluationAgent
from app.agents.incident_monitoring_agent import IncidentMonitoringAgent
from app.agents.monitoring_agent import MonitoringAgent
from app.agents.planning_agent import PlanningAgent
from app.logging_config import get_logger
from app.models.audit import AgentExecution
from app.models.base import AgentStatus
from app.repositories.repositories import RepositoryBundle

logger = get_logger(__name__)

# Professional Spanish display names for the UI. Internal identifiers
# (``agent.name``, used for run URLs, persistence and audit) are preserved
# unchanged — only what a coordinator reads on screen is translated.
AGENT_DISPLAY_NAMES: dict[str, str] = {
    "monitoring_agent": "Agente de Monitoreo Operativo",
    "planning_agent": "Agente de Planificación de Rotaciones",
    "evaluation_agent": "Agente de Revisión de Evaluaciones",
    "document_agent": "Agente de Triage de Documentos",
    "incident_monitoring_agent": "Agente de Monitoreo de Incidencias",
}


class AgentOrchestrator:
    """Registers agents and dispatches tasks to them."""

    def __init__(self, repos: RepositoryBundle) -> None:
        self.repos = repos
        self._agents: dict[str, BaseAgent] = {
            agent.name: agent
            for agent in (
                MonitoringAgent(),
                PlanningAgent(),
                EvaluationAgent(),
                DocumentAgent(),
                IncidentMonitoringAgent(),
            )
        }

    # -- introspection ----------------------------------------------------
    def available_agents(self) -> list[BaseAgent]:
        return list(self._agents.values())

    def get_agent(self, name: str) -> BaseAgent | None:
        return self._agents.get(name)

    # -- execution --------------------------------------------------------
    def run_agent(
        self,
        name: str,
        triggered_by: str = "system",
        extra_context: dict[str, Any] | None = None,
    ) -> AgentResponse:
        """Run a single agent by name, persist the execution and return it."""
        agent = self._agents.get(name)
        if agent is None:
            raise KeyError(f"Unknown agent: {name}")

        context: dict[str, Any] = {"repos": self.repos}
        if extra_context:
            context.update(extra_context)

        try:
            response = agent.run(context)
        except Exception as exc:  # defensive: never crash the caller
            logger.exception("Agent %s failed", name)
            response = AgentResponse(
                agent_name=agent.name,
                task="unknown",
                status=AgentStatus.ERROR.value,
                summary=f"Error ejecutando el agente: {exc}",
                requires_human_approval=True,
            )

        self._persist(response, triggered_by)
        return response

    def run_all(self, triggered_by: str = "system") -> list[AgentResponse]:
        """Run every registered agent (used by the Agent Center demo)."""
        return [self.run_agent(name, triggered_by) for name in self._agents]

    # -- persistence ------------------------------------------------------
    def _persist(self, response: AgentResponse, triggered_by: str) -> None:
        record = AgentExecution(
            agent_name=response.agent_name,
            task=response.task,
            status=response.status,
            summary=response.summary,
            findings_json=response.findings_json(),
            recommended_actions_json=response.actions_json(),
            requires_human_approval=response.requires_human_approval,
            duration_ms=response.duration_ms,
            triggered_by=triggered_by,
        )
        self.repos.agent_executions.add(record)
        self.repos.db.commit()
        logger.info(
            "Agent %s executed (status=%s, findings=%d)",
            response.agent_name,
            response.status,
            len(response.findings),
        )
