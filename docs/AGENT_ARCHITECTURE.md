# AGENT ARCHITECTURE — UPeU Internado 360

> **No external AI API is used in Part 1.** Agents are deterministic mocks with
> a fixed, LLM-ready interface. The design goal is that a future part can drop
> in real AI-backed agents **without changing any caller**.

## 1. Core principle: human-in-the-loop

The platform explicitly separates three stages:

```
   AUTOMATED DETECTION   →   AGENT RECOMMENDATION   →   HUMAN DECISION
   (Rule engine)             (Agents)                   (Coordinator/Admin)
```

Every agent response carries `requires_human_approval`. **No agent performs an
irreversible institutional action or sends a final communication on its own**
(BUSINESS_RULES.md BR-26, BR-27).

## 2. Components

| Component | File | Role |
|-----------|------|------|
| `BaseAgent` | `agents/base_agent.py` | Abstract interface every agent implements. |
| `AgentResponse` / `AgentFinding` | `agents/base_agent.py` | Structured, uniform result contract. |
| `RuleEngine` | `agents/rule_engine.py` | Deterministic business-rule checks. |
| `MonitoringAgent` | `agents/monitoring_agent.py` | Wraps the rule engine into a response. |
| `PlanningAgent` | `agents/planning_agent.py` | Mock rotation-coverage analysis. |
| `EvaluationAgent` | `agents/evaluation_agent.py` | Mock evaluation-completeness review. |
| `DocumentAgent` | `agents/document_agent.py` | Mock document triage (never auto-sends). |
| `AgentOrchestrator` | `agents/orchestrator.py` | Registers agents, routes tasks, persists executions. |

## 3. The response contract

Every execution returns an `AgentResponse` with exactly these fields:

```python
agent_name: str
task: str
status: str                 # success | no_findings | needs_review | error
summary: str
findings: list[AgentFinding] # code, title, detail, severity, entity_type, entity_id
recommended_actions: list[str]
requires_human_approval: bool
timestamp: str               # ISO-8601 UTC
duration_ms: int | None
```

This maps 1:1 to the `agent_executions` table, so every run is persisted and
auditable.

## 4. The rule engine (deterministic)

Rules are pure functions `(repos, today) -> list[AgentFinding]`, registered in a
single `RULES` dict. Shipped rules:

| Code | Rule | Severity |
|------|------|----------|
| `rotation_ending_soon` | Active rotation ending within **7 days**. | warning |
| `missing_tutor` | Active/planned assignment with **no tutor**. | critical |
| `pending_evaluation` | Evaluation in `pending`/`in_progress`. | warning |
| `incomplete_profile` | Student profile marked incomplete. | info |

`AlertService` runs the engine and turns findings into `Alert` rows (deduped
against existing open alerts), which drive the dashboard and notifications.

## 5. Orchestration flow

```
AgentOrchestrator.run_agent(name)
  ├─ build context { repos, ... }
  ├─ agent.run(context)  → AgentResponse   (never throws to caller)
  ├─ persist AgentExecution (findings/actions serialized to JSON)
  └─ return AgentResponse
```

`run_all()` executes every registered agent (used by the Agent Center's
"Ejecutar todos" button).

## 6. Adding a real AI agent later

1. Create `class InsightAgent(BaseAgent)` implementing `run(context)`.
2. Inside `run`, call the LLM (e.g. Claude) with data gathered via `repos`,
   parse the reply into `AgentFinding`s and `recommended_actions`.
3. Keep `requires_human_approval=True` for any actionable output.
4. Register it in `AgentOrchestrator.__init__`.

No route, service, template or persistence change is required — the contract and
orchestrator already handle it.

## 7. Safety guarantees

- Agents receive data through repositories; they do not mutate institutional
  state directly.
- The orchestrator wraps `agent.run` in error handling; a failing agent yields
  an `error` response, never a crash.
- `DocumentAgent` documents explicitly that sending is a human action.
