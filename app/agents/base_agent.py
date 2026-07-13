"""Common agent interface and structured response contract.

Every agent — mock today, LLM-backed tomorrow — implements ``BaseAgent`` and
returns an ``AgentResponse``. The response shape is fixed so the orchestrator,
persistence layer and UI can treat all agents uniformly.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AgentFinding:
    """A single structured finding produced by an agent."""

    code: str
    title: str
    detail: str
    severity: str = "info"  # info | warning | critical
    entity_type: str | None = None
    entity_id: int | None = None


@dataclass
class AgentResponse:
    """The uniform structured result returned by every agent execution.

    Fields mirror the contract required by the platform spec so responses are
    self-describing and can be persisted to ``AgentExecution`` verbatim.
    """

    agent_name: str
    task: str
    status: str  # maps to AgentStatus values
    summary: str
    findings: list[AgentFinding] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    requires_human_approval: bool = True
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def findings_json(self) -> str:
        return json.dumps([asdict(f) for f in self.findings], ensure_ascii=False)

    def actions_json(self) -> str:
        return json.dumps(self.recommended_actions, ensure_ascii=False)


class BaseAgent(ABC):
    """Abstract base every agent must implement.

    Subclasses declare a stable ``name`` and implement ``run`` to return an
    ``AgentResponse``. Agents receive a ``context`` dict (typically carrying a
    ``RepositoryBundle`` and parameters) rather than reaching for globals, so
    they remain testable and side-effect explicit.
    """

    name: str = "base_agent"
    description: str = "Abstract base agent."

    @abstractmethod
    def run(self, context: dict[str, Any]) -> AgentResponse:
        """Execute the agent's task and return a structured response."""
        raise NotImplementedError

    # -- helpers ----------------------------------------------------------
    def _response(
        self,
        task: str,
        status: str,
        summary: str,
        findings: list[AgentFinding] | None = None,
        recommended_actions: list[str] | None = None,
        requires_human_approval: bool = True,
        duration_ms: int | None = None,
    ) -> AgentResponse:
        return AgentResponse(
            agent_name=self.name,
            task=task,
            status=status,
            summary=summary,
            findings=findings or [],
            recommended_actions=recommended_actions or [],
            requires_human_approval=requires_human_approval,
            duration_ms=duration_ms,
        )
