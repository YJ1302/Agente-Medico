"""Agent-ready architecture package.

Part 1 ships a fully working *deterministic* agent layer with mock reasoning —
no external AI API is called. The interfaces (``BaseAgent``, ``AgentResponse``,
``AgentOrchestrator``, ``RuleEngine``) are designed so that a future part can
drop in LLM-backed agents without changing the callers.

Core principle enforced here: the platform separates
    automated detection  →  agent recommendation  →  human decision
Every agent response carries ``requires_human_approval`` and no agent performs
an irreversible institutional action on its own.
"""
