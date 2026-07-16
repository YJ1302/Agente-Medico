# AI COORDINATOR ASSISTANT ARCHITECTURE — UPeU Internado 360 (Phase 3A/3B)

> The assistant answers natural-language questions using **only** deterministic
> database queries, scoped exactly like every other module in this codebase.
> An external LLM is used **only** to phrase an already-computed result as
> prose — it never queries the database and never sees data outside what was
> already retrieved for the caller's role.

## 1. Core principle: query first, phrase second

```
  QUESTION (free text)
        │
        ▼
  DETERMINISTIC INTENT MATCH        (keyword/substring match against the
        │                            caller's own scoped records — no LLM)
        ▼
  DETERMINISTIC QUERY                (RepositoryBundle, scoped exactly like
        │                            ReportService / GradeService)
        ▼
  STRUCTURED RESULT (headers, rows,  ← this is the only thing ever shown to
  sources, counts, notes)             a human, and the only thing ever sent
        │                             to the LLM
        ▼
  OPTIONAL LLM SUMMARY               (phrasing only; never invents data;
        │                             disabled/unavailable → deterministic
        │                             fallback narrative used instead)
        ▼
  ANSWER (always produced, online or offline)
```

No step above ever lets the free-text question reach the database directly,
and the LLM step is purely cosmetic — removing it changes only the wording of
the answer, never its content or correctness.

## 2. Components

| Component | File | Role |
|-----------|------|------|
| `AIAssistantService` | `app/services/ai_assistant_service.py` | Intent matching, scoped query builders, rate limiting, audit, orchestration. |
| `AssistantAnswer` / `AssistantSource` | `app/services/ai_assistant_service.py` | Structured, uniform result contract (mirrors `AgentResponse`/`ReportResult`). |
| `AssistantLLMClient` | `app/agents/assistant_llm_client.py` | Optional LLM summarization; always fails safe to `None`. |
| `RateLimiter` | `app/services/rate_limiter.py` | In-process sliding-window limiter, per user. |
| Assistant routes | `app/routes/assistant_routes.py` | Thin controller: `GET /assistant`, `POST /assistant/ask`. |

## 3. Supported questions (11)

| Key | Question | Roles |
|-----|----------|-------|
| `pending_evaluations` | Students with pending evaluations | Admin, University, Sede Coordinator |
| `low_activity` | Students with low activity progress | Admin, University, Sede Coordinator |
| `rotations_ending_soon` | Rotations ending soon | Admin, University, Sede Coordinator |
| `students_without_tutor` | Students without tutors | Admin, University, Sede Coordinator |
| `tutor_backlog` | Tutors with a verification backlog | Admin, University, Sede Coordinator |
| `open_incidents` | Open high/critical incidents | Admin, University, Sede Coordinator |
| `documents_awaiting_review` | Documents awaiting review | Admin, University, Sede Coordinator |
| `grade_components_missing` | Missing/inconsistent grade components | Admin, University **only** |
| `cross_sheet_inconsistencies` | Cross-sheet grade inconsistencies | Admin, University **only** |
| `student_summary` | Summary of one student's internship | Admin, University, Sede Coordinator (own sede) |
| `sede_summary` | Summary by sede | Admin, University, Sede Coordinator (own sede) |

The two grade-related questions are restricted to Admin/University Coordinator
only — the same boundary `GradeService`/`/grades` already enforces (Sede
Coordinators never see the raw grade matrix; see `GRADE_COMPONENT_MODEL.md`
and `USER_ROLES_AND_PERMISSIONS.md` Batch 2F).

## 4. Deterministic intent matching (no LLM involved)

`AIAssistantService.match_intent()` normalizes the question (lowercase,
accent-stripped, whitespace-collapsed) and checks it against:

1. **Entity extraction** — if the question mentions "resumen"/"informe" plus a
   student name/code or sede name/short-name that exists in the caller's *own
   scoped list* (`scoped_students()` / `scoped_sedes()`), it resolves to
   `student_summary` / `sede_summary` for that entity. A name that is not in
   the caller's scope can never be resolved — there is nothing to compare it
   against.
2. **Keyword substrings** — an ordered list of natural Spanish phrases per
   intent (e.g. "sin tutor", "evaluaciones pendientes", "entre hojas"). First
   match wins.
3. **No match** → `intent="unknown"`, `found=False`, and the answer lists the
   11 supported questions so the user can rephrase.

This routing is 100% deterministic and reversible by reading the code — a
malicious or confusing question can, at worst, fail to match anything. It can
never expand what the caller is allowed to query, because every builder below
still applies the caller's own role/sede scope regardless of how the intent
was matched.

## 5. Query builders (deterministic, scoped)

Each `_q_<intent>` method on `AIAssistantService` mirrors `ReportService`'s
established scope pattern:

* `is_global_viewer()` (Admin/University) sees everything.
* Sede Coordinator queries are filtered to `_own_sede_ids()` — an empty set
  becomes `{-1}` so the query returns nothing rather than "no filter".
* Confidential incidents/documents are redacted (title replaced with
  `"(incidencia confidencial)"`, or the row dropped entirely for documents)
  before they are ever assembled into the answer — the LLM and the audit log
  only ever see the already-redacted result.
* `grade_components_missing` and `cross_sheet_inconsistencies` never compute a
  final grade; they only ever report the same "pending confirmation" signals
  `GradeService.final_grade_note()` already uses. See §7.

## 6. The LLM summarization step (two interchangeable providers)

`AssistantLLMClient.summarize(question, payload)` supports two providers,
selected by `AI_ASSISTANT_PROVIDER`:

| Provider | Value | SDK | Model setting example |
|----------|-------|-----|------------------------|
| Anthropic (default) | `anthropic` | `anthropic` (official Python SDK) | `claude-3-5-haiku-20241022` |
| Google Gemini | `gemini` | `google-genai` (official Python SDK) | `gemini-2.0-flash` |

Both branches (`_call_anthropic` / `_call_gemini`) are private methods on
`AssistantLLMClient` and receive the **exact same** `_user_content(question,
payload)` string and the **exact same** `SYSTEM_PROMPT` — only the transport
call differs. Switching providers is a configuration change
(`AI_ASSISTANT_PROVIDER` + the matching API key + a model id valid for that
provider); no other part of the assistant changes.

`summarize()`:

* Is only called with `payload` — the *already computed* headers/rows/count
  for one intent, truncated to 20 rows. It never receives database access,
  connection strings, or any other user's data, regardless of provider.
* Is skipped entirely (`available()` returns `False`) when
  `AI_ASSISTANT_ENABLED` is false, the selected provider's key
  (`ANTHROPIC_API_KEY` or `GEMINI_API_KEY`) is unset, or
  `AI_ASSISTANT_PROVIDER` is not one of the two recognized values.
* Is skipped (returns `None`) when that provider's SDK package is not
  installed (`anthropic` or `google-genai`, both lazy-imported), the call
  raises for any reason (invalid key, quota exhaustion, network error,
  malformed response, or any other provider error), or the provider is
  unreachable.
* Runs under a **uniform, provider-independent timeout**
  (`AI_ASSISTANT_TIMEOUT_SECONDS`): the call is submitted to a
  single-worker `ThreadPoolExecutor` and `future.result(timeout=...)` is used
  to bound it, so a slow provider can never hang a request even if that
  provider's own SDK doesn't expose (or honor) a timeout parameter.
* Is wrapped in a second `try/except` at the call site
  (`AIAssistantService.answer()`) as a defense-in-depth safety net, in
  addition to the `try/except` inside `summarize()` itself.
* Uses one shared system prompt (see the file) that explicitly instructs the
  model to treat the question and payload as content to describe, never as
  instructions — see `SECURITY_AND_PRIVACY_RULES.md` §9 for the full
  prompt-injection posture. Identical for both providers.

When the LLM step is skipped or fails — for *any* reason, on *either*
provider — `AIAssistantService._narrative()` supplies a deterministic
templated sentence ("Se encontraron N resultado(s) para: <title>." / "No se
encontraron resultados para: <title>.") so the assistant **always** answers,
online or offline, regardless of which provider is configured.

## 7. Never invents grade weights or final grades

`_q_grade_components_missing` only reports two deterministic facts already
modeled elsewhere in the schema: a required component with `weight_percent IS
NULL`, or a required component row with `score IS NULL`. It never multiplies
a score by a weight and never proposes one. `_q_cross_sheet_inconsistencies`
delegates entirely to the existing, already-tested
`GradeService.cross_sheet_report()` (Batch 2F) — no new grade logic was
introduced for this phase.

## 8. Rate limiting, timeouts and audit

* `RateLimiter` (in-process, sliding window) rejects excess calls per user
  (`AI_ASSISTANT_RATE_LIMIT_PER_MINUTE`, default 10/min) before any query
  runs, and the rejection itself is audited (`ai_assistant_rate_limited`).
* Every call to `AIAssistantService.answer()` writes **two** audit entries:
  `ai_assistant_query` (intent + truncated question + result count) before
  any LLM call, and `ai_assistant_response` (intent + whether the LLM summary
  was used + result count) after. Neither entry stores the full row data —
  only counts and the intent key — so confidential content already redacted
  from the answer is never re-exposed through the audit trail.

## 9. Safety guarantees (recap)

- The assistant never creates, edits, approves, grades, closes an incident,
  or sends a document — it is read-only end to end. There is no `POST`
  endpoint other than `/assistant/ask`, which only returns an answer.
- No agent output is auto-actioned; there is nothing to approve because the
  assistant makes no recommendations requiring action, only informational
  summaries.
- The assistant's own route guard (`require_management`) and the
  per-intent `can_ask()` check both enforce role scope — a Sede Coordinator
  cannot reach the grade questions even by crafting a matching question text.
