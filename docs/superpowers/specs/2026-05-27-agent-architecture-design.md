# Agent Architecture Design

**Date:** 2026-05-27
**Status:** Approved

## Overview

Three-layer agent architecture for real-time legal consultation assistance. The system listens to lawyer-client dialogue, maintains a user profile of extracted facts, and proactively offers legal references and analysis at appropriate moments — without blocking or interrupting the conversation flow.

## Architecture

```
Every client sentence
  │
  └─ LegalAgent.observe(text, speaker)  →  fire-and-forget (no await, no cancel)
       │
       └─ Judge Agent (1 instance, per-sentence, lightweight)
            │  Input: user profile + recent N sentences of context
            │  Output: facts_summary + decision (none / simple / complex) + topic
            │
            ├─ none ──→ update facts_summary only, done
            │
            ├─ simple ──→ update facts_summary
            │              └─ fire-and-forget → Simple Analysis Agent
            │                                      └─ AnalysisResult → push sidebar
            │
            └─ complex ──→ update facts_summary
                           └─ push Intent Card to frontend
                                └─ lawyer clicks "confirm"
                                     └─ fire-and-forget → Executor Agent
                                                              └─ list[AnalysisResult] → push sidebar
```

All fire-and-forget tasks are independent. No agent blocks another. No agent is cancelled.

## Agents

### Judge Agent

- **Trigger:** Every client sentence (fire-and-forget from `observe()`)
- **Purpose:** Extract structured facts from the sentence, append to user profile, decide whether to intervene
- **Cost:** Minimal — narrow prompt, binary decision output
- **Tools (all non-blocking, <1ms return):**
  - `update_fact(key, value)` — append to profile dict, instant return
  - `trigger_simple_analysis(topic)` — `asyncio.create_task`, fire-and-forget
  - `trigger_complex_intent(question)` — push intent card to frontend, instant return
- **Expected behavior:** 98%+ of calls return `none`, only updating facts. 1-2 meaningful interventions per session.

### Simple Analysis Agent

- **Trigger:** Judge returns `simple`
- **Purpose:** Quick legal analysis on a specific topic — produce a statute citation, a contract clause suggestion, or a risk flag
- **Output:** `list[AnalysisResult]` — pushed directly to sidebar, no user confirmation needed

### Executor Agent

- **Trigger:** Lawyer clicks "confirm" on an intent card
- **Purpose:** Deep legal analysis — full report with statutes, contract templates, risk assessments
- **Output:** `list[AnalysisResult]` — pushed to sidebar

## Data Structures

### User Profile

Append-only dict, each key holds a list of timestamped records:

```python
user_profile = {
    "employment_date": [
        {"value": "2024.11", "ts": "2026-05-27T13:01:20"},
    ],
    "contract_signed": [
        {"value": "一年期合同，到期未续签", "ts": "2026-05-27T13:01:22"},
    ],
    ...
}
```

Facts are never overwritten. When a fact has multiple versions, deeper analysis agents prioritize the most recent timestamp.

### AnalysisResult

```python
@dataclass
class AnalysisResult:
    category: str       # "statute" | "contract" | "risk"
    title: str
    content: str
    citation: str | None
    level: str | None   # "高" | "中" | "低" (risk only)
```

### IntentResult

```python
@dataclass
class IntentResult:
    intent_id: str      # UUID
    question: str       # e.g. "需要查《劳动合同法》第82条吗？"
    context: str        # triggering dialogue excerpt
```

## WebSocket Protocol

| Direction | Type | Payload | Description |
|-----------|------|---------|-------------|
| S→C | `intent` | `{intent_id, question, context}` | Push intent card for lawyer confirmation |
| C→S | `confirm_intent` | `{intent_id}` | Lawyer confirms, triggers Executor |
| C→S | `dismiss_intent` | `{intent_id}` | Lawyer dismisses, clears pending intent |
| S→C | `analysis` | `{category, title, content, citation, level}` | Push analysis to sidebar |

Existing `transcript` and `ping/pong` messages unchanged.

## Key Design Decisions

1. **No debounce, no cancel.** Every client sentence fires a Judge task. Multiple tasks can run concurrently. Each snapshots current state at start. No LLM call is cancelled.

2. **Judge does not analyze.** It only extracts facts and decides yes/no + type. Actual legal analysis is delegated to Simple Analysis or Executor agents.

3. **Append-only user profile with timestamps.** Facts accumulate over the session. No fact is ever deleted or overwritten. Deeper agents prioritize recent timestamps.

4. **Intent cards require lawyer confirmation.** Complex analysis is never auto-executed. The lawyer retains full control over when deep analysis runs.

## Source Files

| File | Purpose |
|------|---------|
| `backend/src/agent.py` | `LegalAgent` class — observe/confirm/dismiss, state management |
| `backend/src/agno_agents.py` | Agno agent factory functions — judge, simple analysis, executor |
| `backend/main.py` | FastAPI + WebSocket, wires agent to frontend |
| `backend/tests/test_agent.py` | LegalAgent unit tests |
| `backend/tests/test_agno_agents.py` | Agno agent configuration and parser tests |
