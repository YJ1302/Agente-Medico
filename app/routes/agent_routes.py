"""Agent Center routes: view registered agents and run them on demand.

Running an agent persists an ``AgentExecution`` and returns its structured
response. Agents only detect and recommend — the UI makes clear that any action
requires human approval.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.agents.orchestrator import AgentOrchestrator
from app.database import get_db
from app.dependencies import Identity, require_identity
from app.repositories.repositories import RepositoryBundle
from app.templating import render

router = APIRouter(tags=["agents"])


@router.get("/agents")
def agent_center(request: Request, identity: Identity = Depends(require_identity),
                 db: Session = Depends(get_db)):
    repos = RepositoryBundle(db)
    orchestrator = AgentOrchestrator(repos)
    agents = [
        {"name": a.name, "description": a.description}
        for a in orchestrator.available_agents()
    ]
    return render(
        request,
        "pages/agents.html",
        identity=identity,
        page_title="Centro de Agentes",
        page_subtitle="Agentes deterministas listos para IA (detección y recomendación).",
        page_icon="robot",
        agents=agents,
        recent_runs=repos.agent_executions.recent(limit=8),
    )


@router.post("/agents/run")
def run_all_agents(request: Request, identity: Identity = Depends(require_identity),
                   db: Session = Depends(get_db)):
    repos = RepositoryBundle(db)
    AgentOrchestrator(repos).run_all(triggered_by=identity.email)
    return RedirectResponse(url="/agents", status_code=303)


@router.post("/agents/{agent_name}/run")
def run_single_agent(agent_name: str, request: Request,
                     identity: Identity = Depends(require_identity),
                     db: Session = Depends(get_db)):
    repos = RepositoryBundle(db)
    orchestrator = AgentOrchestrator(repos)
    if orchestrator.get_agent(agent_name):
        orchestrator.run_agent(agent_name, triggered_by=identity.email)
    return RedirectResponse(url="/agents", status_code=303)
