"""Agent Center routes: view registered agents and run them on demand.

Running an agent persists an ``AgentExecution`` and returns its structured
response. Agents only detect and recommend — the UI makes clear that any action
requires human approval.

Access (see docs/PERMISSIONS_MATRIX.md "Agent Center"): Administrator and
University Coordinator only. None of the five registered agents filter their
findings by sede — every one of them scans the whole institution
(``repos.X.all_active()`` with no ``sede_ids=`` filter) — so a Sede
Coordinator cannot be given access without leaking other sedes' data; per the
Agent Center rule, an unscoped agent must be blocked for that role rather
than reworked here. Tutor and Student have no legitimate use for this module
at all.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.agents.orchestrator import AGENT_DISPLAY_NAMES, AgentOrchestrator
from app.authorization import require_admin_or_university
from app.database import get_db
from app.dependencies import Identity
from app.repositories.repositories import RepositoryBundle
from app.templating import render

router = APIRouter(tags=["agents"])


@router.get("/agents")
def agent_center(request: Request, identity: Identity = Depends(require_admin_or_university),
                 db: Session = Depends(get_db)):
    repos = RepositoryBundle(db)
    orchestrator = AgentOrchestrator(repos)
    agents = [
        {"name": a.name, "display_name": AGENT_DISPLAY_NAMES.get(a.name, a.name),
         "description": a.description}
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
        agent_display_names=AGENT_DISPLAY_NAMES,
        recent_runs=repos.agent_executions.recent(limit=8),
    )


@router.post("/agents/run")
def run_all_agents(request: Request, identity: Identity = Depends(require_admin_or_university),
                   db: Session = Depends(get_db)):
    repos = RepositoryBundle(db)
    AgentOrchestrator(repos).run_all(triggered_by=identity.email)
    return RedirectResponse(url="/agents", status_code=303)


@router.post("/agents/{agent_name}/run")
def run_single_agent(agent_name: str, request: Request,
                     identity: Identity = Depends(require_admin_or_university),
                     db: Session = Depends(get_db)):
    repos = RepositoryBundle(db)
    orchestrator = AgentOrchestrator(repos)
    if orchestrator.get_agent(agent_name):
        orchestrator.run_agent(agent_name, triggered_by=identity.email)
    return RedirectResponse(url="/agents", status_code=303)
