"""AI Coordinator Assistant routes (Phase 3A). Thin controller.

Only Admin, University Coordinator and Sede Coordinator may reach this
router — ``require_management`` blocks Students and Tutors with a 403 that is
audited (``authorization_denied``), matching every other management-only
module in this codebase (reports, grades, imports).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.authorization import require_management
from app.csrf import csrf_protect
from app.database import get_db
from app.dependencies import Identity
from app.services.ai_assistant_service import QUESTIONS, AIAssistantService
from app.services.audit_service import client_ip
from app.templating import render

router = APIRouter(tags=["assistant"])


def _questions_for(identity: Identity) -> list[tuple[str, str]]:
    return [(k, title) for k, (title, roles) in QUESTIONS.items() if identity.role_code in roles]


@router.get("/assistant")
def assistant_home(request: Request, identity: Identity = Depends(require_management),
                   db: Session = Depends(get_db)):
    return render(
        request, "pages/assistant.html", identity=identity,
        page_title="Asistente IA del Coordinador",
        page_subtitle="Consultas en lenguaje natural sobre datos existentes, con fuentes y conteos.",
        page_icon="stars", questions=_questions_for(identity), answer=None, question_text="",
    )


@router.post("/assistant/ask")
def assistant_ask(request: Request, question: str = Form(...),
                  identity: Identity = Depends(require_management),
                  db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = AIAssistantService(db, identity)
    answer = svc.answer(question.strip()[:500], ip=client_ip(request))
    return render(
        request, "pages/assistant.html", identity=identity,
        page_title="Asistente IA del Coordinador",
        page_subtitle="Consultas en lenguaje natural sobre datos existentes, con fuentes y conteos.",
        page_icon="stars", questions=_questions_for(identity), answer=answer,
        question_text=question,
    )
