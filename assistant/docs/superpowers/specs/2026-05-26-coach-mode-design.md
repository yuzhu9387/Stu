# Coach Mode Design

**Date:** 2026-05-26
**Status:** Approved (pending user spec review)
**Depends on:** Spec 1 (Infrastructure) + Spec 2 (Proactive agent) + Spec 3 (Memory refinement)

## Goal

Add a distinct "coach" mode to the assistant: a third-party observer who asks Socratic questions from first principles, brings in outside information via web search when relevant, and helps the user think rather than telling them what to do. Triggered by the user explicitly OR by the system when it detects high-confidence signs the user is stuck.

## Scope

### In scope

- Coach persona — different from default assistant persona
- Multi-turn coach sessions reusing the existing `dialogue_session` table (`flow_type="coach"`)
- THINK constraints in coach mode (no data-mutating actions; only feedback/pattern/end-session)
- REACT prompts + Anthropic native `web_search` tool enabled in coach mode
- Coach entry: user-initiated short phrases AND system auto-trigger (task 3x deferred, negative feedback, 3-day silence)
- `end_coach_session` action; session also self-terminates after 24h
- New trigger type `CoachOpeningTrigger` for proactive system entry
- New cron job to scan for coach trigger signals daily

### Out of scope

- Voice-based coach (only text)
- Coach knowledge base / RAG over books (web search only this spec)
- Group coaching / multiple users (single-user only)
- Coach-generated UI (no new web views)
- Goal/habit recommendations from coach (stays in question-asking mode)
- Long-term coaching plans tracked between sessions (each session is standalone reflection)

## Constraints / Principles

- **Coach asks, doesn't tell.** Multi-turn flow built around Socratic questioning. Most replies end with one question.
- **Coach is third-party.** Not a friend, not a yes-man. Names patterns the user is avoiding. Stays observation-mode.
- **Coach does not touch data.** No create_task, update_goal, etc. The data layer is a different mode. Coach is reflection mode.
- **Trigger conservatively.** Only auto-trigger on strong signals: 3x deferred task, recent negative feedback, 3-day silence. Don't trigger on "habit skipped" or "goal slow" — too noisy.
- **Web search is sparing.** Only when an outside fact would sharpen the next question. Don't dump results; distill into one insight + one question.
- **Soft-fail.** Tool unavailability, web_search blocked, etc. → coach continues without external info. Never breaks the user-facing reply.

## Architecture

```
                       ┌──────────────────────────────────────────────────┐
                       │  Spec 1+2+3 base (orchestrator + memory + worker) │
                       └────────────────────┬─────────────────────────────┘
                                            │
        ┌───────────────────────────────────┼──────────────────────────────────┐
        ▼                                   ▼                                  ▼
  ┌─────────────────────┐  ┌─────────────────────────────┐  ┌──────────────────────┐
  │ User-initiated      │  │ System auto-trigger          │  │ Coach mode runtime    │
  │ (THINK detects      │  │ (run_coach_signal_check cron)│  │ (active_flow=coach)   │
  │  "let's talk",      │  │  Signals:                    │  │ - THINK: append       │
  │  "be honest",       │  │   - task deferred 3x         │  │   coach/think.md      │
  │  "coach mode" →     │  │   - feedback negative recent │  │ - REACT: coach        │
  │  emit start_flow    │  │   - 3-day silence            │  │   persona + tools     │
  │  flow_name=coach)   │  │  Dedup: skip if coach within │  │   = web_search        │
  │                     │  │   past 24h.                  │  │ - max_tokens bumped   │
  └──────────┬──────────┘  └───────────────┬──────────────┘  └─────────┬────────────┘
             │                             │                            │
             │       (both create dialogue_session(flow_type=coach,     │
             │        status=active))                                    │
             │                             │                            │
             └─────────────────────────────┼────────────────────────────┘
                                           ▼
                            ┌──────────────────────────────┐
                            │ /api/conversation (unchanged) │
                            │  Multi-turn coach session     │
                            │  persists until END or 24h    │
                            └──────────────────────────────┘
                                           │
                                           ▼ (terminates via)
                            ┌──────────────────────────────┐
                            │ end_coach_session action      │
                            │ (THINK emits when user signals│
                            │  done OR auto-cleanup at 24h) │
                            └──────────────────────────────┘
```

## Component 1: Coach Persona

`app/coach/persona.py`:

```python
COACH_PERSONA = """You are now in COACH MODE for {user_name}. This is different from your default assistant role.

A coach is NOT a friend giving advice. A coach is a third-party observer who helps you see what you can't see.

Your job in coach mode:
- Ask, don't tell. Use Socratic questioning to surface the user's own thinking.
- Start from first principles. Don't accept surface answers — keep asking "why" or "what makes that true for you?"
- Bring outside information. When the user is stuck on a question or assumption, search the web for relevant frameworks, research, examples — and use them to ask a sharper question, not to lecture.
- Hold space. Don't rush to solutions. The user thinks better when they feel heard, not when they feel hurried.
- Stay third-party. You're not a yes-friend. You can name patterns the user is avoiding ("you've moved this deadline 3 times now — what do you think is actually going on?").
- One question per turn. No multi-question dumps. The user can only think about one thing at a time.

Things you do NOT do in coach mode:
- Create tasks, modify goals, set reminders. That's not coaching, that's transactional. Stay out of the data layer.
- Give pep talks or generic encouragement. Concrete observation > vague support.
- Pretend the user said something they didn't. Reflect accurately.

Tone: warm but honest. You care enough to ask hard questions. Use the user's language; default to Chinese if they do.

Length: usually 1-3 sentences. Sometimes longer when sharing a researched frame, but follow up with a single question.
"""


def load_coach_persona(user_name: str = "the user") -> str:
    return COACH_PERSONA.format(user_name=user_name)
```

## Component 2: Coach Prompts (THINK + REACT addenda)

`app/coach/prompts/think.md`:

```markdown
COACH MODE ACTIVE.

In this mode, do NOT emit data-mutating actions (create_task, update_task, complete_task, create_goal, add_habit, update_profile, record_pattern, etc.). The user is in a reflective conversation — let them think; the data layer can wait.

Actions you MAY still emit in coach mode:
- record_feedback: when the user expresses how the coaching is landing for them
- reinforce_pattern / contradict_pattern: when their reflection validates or refutes an existing learned pattern

Action you can emit to end the session:
- end_coach_session: when the user signals they're done ("ok thanks", "that helps, let's get back to it", "I need to stop here"), OR when they want to switch to transactional work ("add a task", "what's on my plate today").

Decide should_reply=true unless the user explicitly says "stop talking" or similar.

Reply complexity: usually "high" — the REACT model needs to think carefully about the next question. Default to high in coach mode.
```

`app/coach/prompts/react.md`:

```markdown
COACH MODE REPLY GUIDELINES.

You are generating a coach reply. Persona is already loaded.

Behavior:
- If the conversation needs background information the user doesn't have (a relevant framework, research finding, historical example), you have a `web_search` tool available. Use it sparingly — only when an outside fact would sharpen the next question.
- After web_search returns, do NOT dump the search results. Distill into ONE relevant insight, then ask ONE question.
- If you've asked 3+ questions without the user moving forward, try changing angle: from "why" to "what would it look like if..." or "what would have to be true for that to work?"
- Don't end the session yourself unless the user signals readiness. Keep holding space.

Output: plain text, the user's language, 1-3 sentences usually.
```

Main `app/orchestrator/prompts/think.md` also gets a small addendum so THINK in NORMAL mode can route into coach:

```markdown
When the user signals they want reflective dialogue ("咱们聊聊 X", "帮我梳梳", "I need to think through X", "coach 模式", "let's talk about", "step back and look at X"), emit:
- start_flow with flow_name="coach" and context={"topic": "<what they want to reflect on>"}.

Use this sparingly. Casual chat is not coach mode. Only trigger when the user actually wants to think through something.
```

## Component 3: Triggers — User-Initiated + System Auto

### User-initiated

THINK detects entry phrases (covered by the main prompt addendum) → emits `start_flow(flow_name="coach", context={"topic": "..."})`. ActionExecutor creates the `dialogue_session` row. Next turn's `load_context` sees `active_flow="coach"` and the orchestrator switches modes.

### System auto-trigger

New APScheduler job `run_coach_signal_check`, cron once per day at 9am UTC.

`app/coach/signal_monitor.py`:

```python
from datetime import datetime, timedelta, timezone
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.dialogue_session import DialogueSession
from app.models.event import Event
from app.models.task import Task
from app.models.user import User


DEDUP_HOURS = 24
SILENCE_DAYS = 3
DEFER_COUNT_THRESHOLD = 3


async def _recently_in_coach(session: AsyncSession, user_id: int, hours: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = (
        select(DialogueSession)
        .where(
            DialogueSession.user_id == user_id,
            DialogueSession.flow_type == "coach",
            DialogueSession.created_at >= cutoff,
        )
        .limit(1)
    )
    return (await session.execute(q)).scalar_one_or_none() is not None


async def _detect_trigger(session: AsyncSession, user_id: int) -> str | None:
    """Returns trigger reason string, or None."""
    now = datetime.now(timezone.utc)

    # Signal A: 3-day silence
    last_user_msg_q = (
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.role == "user")
        .order_by(desc(Conversation.id))
        .limit(1)
    )
    last_user_msg = (await session.execute(last_user_msg_q)).scalar_one_or_none()
    if last_user_msg and (now - last_user_msg.created_at) > timedelta(days=SILENCE_DAYS):
        return f"You haven't said anything in {(now - last_user_msg.created_at).days} days."

    # Signal B: recent negative feedback (within 24h)
    recent_feedback_q = (
        select(Event)
        .where(
            Event.user_id == user_id,
            Event.type == "feedback_recorded",
            Event.created_at >= now - timedelta(hours=24),
        )
        .order_by(desc(Event.id))
        .limit(1)
    )
    recent_feedback = (await session.execute(recent_feedback_q)).scalar_one_or_none()
    if recent_feedback and (recent_feedback.payload or {}).get("sentiment") == "negative":
        return "You weren't happy with how things went earlier."

    # Signal C: a single task has been update_task'd with new deadline >=3 times and still pending
    # Aggregate: count task_updated events per entity_id where payload.after.deadline changed
    update_events_q = (
        select(Event)
        .where(Event.user_id == user_id, Event.type == "task_updated",
               Event.entity_type == "task")
    )
    updates = (await session.execute(update_events_q)).scalars().all()
    deferral_counts: dict[int, int] = {}
    for ev in updates:
        payload = ev.payload or {}
        before = (payload.get("before") or {}).get("deadline")
        after = (payload.get("after") or {}).get("deadline")
        if before != after and after is not None and ev.entity_id is not None:
            deferral_counts[ev.entity_id] = deferral_counts.get(ev.entity_id, 0) + 1
    over_threshold = [tid for tid, c in deferral_counts.items() if c >= DEFER_COUNT_THRESHOLD]
    for tid in over_threshold:
        task = await session.get(Task, tid)
        if task and task.status == "pending":
            return f"'{task.title}' has been pushed {deferral_counts[tid]} times and is still on your list."

    return None


async def run_coach_signal_check() -> None:
    """Daily: scan all users, fire coach opening trigger if a signal is hot and user
    hasn't been in coach mode recently."""
    from app.database import async_session_factory
    from app.scheduler.jobs import _build_orchestrator
    from app.orchestrator.triggers import CoachOpeningTrigger

    async with async_session_factory() as session:
        users = (await session.execute(select(User))).scalars().all()
        for u in users:
            if await _recently_in_coach(session, u.id, DEDUP_HOURS):
                continue
            reason = await _detect_trigger(session, u.id)
            if not reason:
                continue
            orch = await _build_orchestrator(session)
            await orch.send_proactive(
                user_id=u.id,
                trigger=CoachOpeningTrigger(reason=reason),
                complexity="high",
            )
```

## Component 4: CoachOpeningTrigger + send_proactive Path

Add to `app/orchestrator/triggers.py`:

```python
class CoachOpeningTrigger(BaseModel):
    type: Literal["coach_opening"] = "coach_opening"
    reason: str
```

Add to `Trigger` union and `synthetic_message_for`:

```python
    if isinstance(trigger, CoachOpeningTrigger):
        return (
            f"[SYSTEM_TRIGGER:coach_opening] Begin a coach session. Reason: {trigger.reason}. "
            f"Open warmly with one question grounded in this signal."
        )
```

Update `app/orchestrator/proactive.py` `send_proactive_impl` to handle `CoachOpeningTrigger` like `WelcomeTrigger` — emit `start_flow(coach)` action first, then REACT:

```python
elif isinstance(trigger, CoachOpeningTrigger):
    executor = ActionExecutor(session)
    await executor.execute_all(
        user_id=user_id,
        actions=[ParsedAction(ActionType.START_FLOW, StartFlowParams(flow_name="coach"))],
        conversation_id=None,
    )
    ctx = await load_context(user_id, session)
    hint = "warm, third-party observer, one question, ground in the reason"
```

## Component 5: Coach Flow Definition

`app/orchestrator/flows.py`:

```python
COACH = FlowDefinition(
    name="coach",
    required_fields=(),  # open-ended; coach is a free-form conversation
)

_REGISTRY: dict[str, FlowDefinition] = {
    ONBOARDING.name: ONBOARDING,
    COACH.name: COACH,
}
```

Empty `required_fields` means `flow_def.missing_fields(...)` always returns `[]` — fine. `load_context` shouldn't try to push onboarding-style prompting for coach (verify it handles empty required_fields gracefully).

## Component 6: end_coach_session Action

Add to `app/orchestrator/actions.py`:

```python
ActionType.END_COACH_SESSION = "end_coach_session"


class EndCoachSessionParams(BaseModel):
    """No params needed — finds active coach session and ends it."""
    pass


# In PARAM_REGISTRY:
    ActionType.END_COACH_SESSION: EndCoachSessionParams,
```

Add to `app/orchestrator/act.py`:

```python
async def _end_coach_session(self, user_id: int, p: EndCoachSessionParams) -> ActionResult:
    q = (
        select(DialogueSession)
        .where(
            DialogueSession.user_id == user_id,
            DialogueSession.flow_type == "coach",
            DialogueSession.status == "active",
        )
        .order_by(desc(DialogueSession.id))
        .limit(1)
    )
    sess = (await self.session.execute(q)).scalar_one_or_none()
    if sess is None:
        return ActionResult(
            type=ActionType.END_COACH_SESSION, entity_type="flow", entity_id=None,
            payload={"ended": False, "reason": "no active coach session"},
        )
    sess.status = "completed"
    await self.session.flush()
    return ActionResult(
        type=ActionType.END_COACH_SESSION, entity_type="flow", entity_id=sess.id,
        payload={"ended": True, "session_id": sess.id},
    )
```

Wire in `_dispatch`:

```python
if action.type == ActionType.END_COACH_SESSION:
    return await self._end_coach_session(user_id, action.params)
```

Add to `_EVENT_TYPE_MAP`:

```python
ActionType.END_COACH_SESSION: "flow_completed",
```

(Re-using `flow_completed` event type since semantically it's the same event.)

## Component 7: LLMRouter Tool Support

`app/llm/router.py`:

```python
async def complete(
    self,
    task_type: TaskType,
    messages: list[dict],
    max_tokens: int = 1500,
    response_format: Optional[dict] = None,
    tools: Optional[list[dict]] = None,
) -> str:
    model = resolve_model(task_type)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if self._api_key:
        kwargs["api_key"] = self._api_key
    if response_format is not None:
        kwargs["response_format"] = response_format
    if tools is not None:
        kwargs["tools"] = tools
    try:
        response = await litellm.acompletion(**kwargs)
    except Exception as e:
        raise LLMError(f"LLM call failed: {e}") from e
    content = response.choices[0].message.content
    # When tools were used, content can be a list of blocks (text + tool_use + tool_result).
    if isinstance(content, list):
        text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        content = "\n".join(p for p in text_parts if p)
    if content is None or content == "":
        raise LLMError("LLM returned empty content")
    return content
```

## Component 8: REACT Coach Mode Wiring

`app/orchestrator/react.py` `react_or_raise`:

```python
from app.coach.persona import load_coach_persona
from app.coach.web_search import tools_for_coach

async def react_or_raise(ctx, message, action_results, hint, complexity, llm):
    is_coach = ctx.active_flow == "coach"

    if is_coach:
        persona_text = load_coach_persona(ctx.user_name)
        # Append coach prompts/react.md to system prompt
        from pathlib import Path
        coach_react = (Path(__file__).parent.parent / "coach" / "prompts" / "react.md").read_text()
        system_prompt = persona_text + "\n\n" + coach_react
        tools = tools_for_coach()
        max_tokens = 2000
        # Force complexity to high in coach mode
        task_type = "reasoning"
    else:
        # ... existing default path
        system_prompt = _load_template().replace("{persona}", load_persona(ctx.user_name))
        tools = None
        max_tokens = 1500
        task_type = "reasoning" if complexity == "high" else "react"

    history = "\n".join(...)
    recall_block = json.dumps(ctx.episodic_recall, ensure_ascii=False)
    user_content = (
        f"<conversation_history>\n{history}\n</conversation_history>\n"
        f"<episodic_recall>{recall_block}</episodic_recall>\n"
        f"<user_message>{message}</user_message>\n"
        f"<actions_completed>{json.dumps(action_results, ensure_ascii=False)}</actions_completed>\n"
        f"<hint>{hint or ''}</hint>"
    )

    return await llm.complete(
        task_type,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_tokens=max_tokens,
        tools=tools,
    )
```

## Component 9: THINK Coach Mode Wiring

`app/orchestrator/think.py`:

When `ctx.active_flow == "coach"`, append `coach/prompts/think.md` to the system prompt:

```python
from pathlib import Path

_COACH_THINK_ADDENDUM_PATH = Path(__file__).parent.parent / "coach" / "prompts" / "think.md"
_COACH_THINK_ADDENDUM: Optional[str] = None


def _load_coach_addendum() -> str:
    global _COACH_THINK_ADDENDUM
    if _COACH_THINK_ADDENDUM is None:
        _COACH_THINK_ADDENDUM = _COACH_THINK_ADDENDUM_PATH.read_text()
    return _COACH_THINK_ADDENDUM


async def think(ctx, message, llm):
    base_system = _load_system_prompt()
    if ctx.active_flow == "coach":
        system = base_system + "\n\n" + _load_coach_addendum()
    else:
        system = base_system
    ...
```

## Component 10: Web Search Tool Constant

`app/coach/web_search.py`:

```python
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}


def tools_for_coach() -> list[dict]:
    return [WEB_SEARCH_TOOL]
```

If Anthropic ships a newer tool spec ID, only this constant changes.

## Scheduler Registration

`app/scheduler/runtime.py` `register_jobs`:

```python
from app.coach.signal_monitor import run_coach_signal_check
scheduler.add_job(run_coach_signal_check, "cron", hour=9, minute=0,
                  id="coach_signal_check", replace_existing=True)
```

## File Organization

### New files

```
app/coach/
├── __init__.py
├── persona.py
├── signal_monitor.py
├── web_search.py
└── prompts/
    ├── think.md
    └── react.md

tests/test_coach/
├── __init__.py
├── test_persona.py
├── test_signal_monitor.py
└── test_web_search.py

tests/test_e2e_coach_smoke.py
```

### Modified files

| Path | Change |
|---|---|
| `app/orchestrator/flows.py` | + `COACH` FlowDefinition + register |
| `app/orchestrator/actions.py` | + `END_COACH_SESSION` enum + `EndCoachSessionParams` + registry |
| `app/orchestrator/act.py` | + `_end_coach_session` + dispatch + event mapping |
| `app/orchestrator/think.py` | + coach addendum loading when active_flow=coach |
| `app/orchestrator/prompts/think.md` | + paragraph about entering coach mode |
| `app/orchestrator/react.py` | branch on `ctx.active_flow=="coach"`: coach persona, coach prompts/react.md, tools=web_search, max_tokens=2000, force complexity=high |
| `app/orchestrator/triggers.py` | + `CoachOpeningTrigger`, update `Trigger` union, `synthetic_message_for` |
| `app/orchestrator/proactive.py` | handle `CoachOpeningTrigger` similar to Welcome (start_flow + REACT) |
| `app/llm/router.py` | `complete()` accepts `tools` kwarg + handles structured content list |
| `app/scheduler/runtime.py` | + register `run_coach_signal_check` daily cron |

### Not touched

- DB schema (reuses `dialogue_session`, `events`, no new tables)
- Spec 1-3 memory modules (coach reads via load_context but doesn't change memory plumbing)
- Frontend
- pyproject.toml (no new deps; LiteLLM transparently forwards `tools` to Anthropic)

## Testing Strategy

- **Unit**: persona text contains required traits; signal_monitor each signal in isolation with seeded events; tools_for_coach shape
- **Integration**: orchestrator-level: ctx with `active_flow="coach"` → THINK called with coach addendum in system prompt (assert on messages content); REACT called with `tools=[...]`, `task_type="reasoning"`, coach persona system prompt; `_end_coach_session` finds + closes active session
- **State machine**: start_flow(coach) → 3 turns simulated → end_coach_session emitted → DialogueSession.status=completed, flow_completed event
- **E2E**: 
  1. User says "咱们聊聊 Q2 报告" → THINK emits start_flow(coach) → REACT (coach) opens
  2. User reflects → REACT (coach) asks Socratic question (mocked LLM)
  3. User says "thanks back to work" → THINK emits end_coach_session
  4. Next turn back in normal persona
- **Not tested**: real Anthropic web_search invocation (mock LLM to assert tools were passed)
- `PA_ENABLE_SCHEDULER=false` in test env (already set from Spec 2)

## Implementation Order

1. `app/coach/persona.py` + tests
2. `app/coach/prompts/{think,react}.md` (static files)
3. `app/coach/web_search.py` + test (just constants)
4. `app/orchestrator/flows.py` + `COACH` FlowDefinition + tests
5. `app/orchestrator/actions.py` + `END_COACH_SESSION` action type + tests
6. `app/orchestrator/act.py` + `_end_coach_session` + dispatch + tests
7. `app/llm/router.py` `complete()` accepts `tools`, handles list-content → tests
8. `app/orchestrator/think.py` system prompt switch when `active_flow=coach` + tests
9. `app/orchestrator/prompts/think.md` + coach entry detection paragraph
10. `app/orchestrator/react.py` coach mode branch (persona + tools + max_tokens + task_type) + tests
11. `app/orchestrator/triggers.py` + `CoachOpeningTrigger` + tests
12. `app/orchestrator/proactive.py` handle `CoachOpeningTrigger` + tests
13. `app/coach/signal_monitor.py` `_detect_trigger` per signal + `_recently_in_coach` + tests
14. `app/coach/signal_monitor.py` `run_coach_signal_check` wrapper + tests
15. `app/scheduler/runtime.py` register `coach_signal_check` daily cron + test
16. E2E coach smoke (mocked LLM, multi-turn)
17. Live sanity check (manual; needs real Anthropic API key, optional web_search verification)

## Roadmap (after Spec 4 ships)

Future possibilities (no spec yet):
- Coach knowledge base (RAG over books / articles you opt in)
- Quantitative goal progress (LLM-estimated km/post/etc. per task completion)
- `_create_goal` schema fix for required NOT NULL fields (was latent from Spec 3 — small backlog item)
- Voice-mode coach
- Coaching plans tracked across sessions
