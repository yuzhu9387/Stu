# Coach Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a distinct coach mode — third-party Socratic observer with web search — that the user can invoke OR the system can offer when it detects high-confidence stuck signals (3x-deferred task / recent negative feedback / 3-day silence).

**Architecture:** A new `app/coach/` package holds the coach persona, prompt addenda, web-search tool constant, and the signal-monitor cron. Coach mode is just `dialogue_session.flow_type="coach"` (no new tables). When `ctx.active_flow=="coach"`, `think.py` appends the coach THINK addendum to its system prompt, and `react.py` swaps in the coach persona, appends the coach REACT addendum, sets `tools=[web_search]`, bumps `max_tokens=2000`, and forces `task_type="reasoning"`. `LLMRouter.complete()` is extended to accept `tools` and to extract text blocks from structured (tool-using) responses. A new `end_coach_session` action closes the active session.

**Tech Stack:** Python 3.10 · FastAPI · SQLAlchemy 2 async · APScheduler · LiteLLM (transparently forwards Anthropic `tools` param) · Anthropic native `web_search_20250305` server-side tool · pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-05-26-coach-mode-design.md`
**Predecessor plan:** `docs/superpowers/plans/2026-05-26-memory-refinement.md`

---

## Pre-flight

Before any tasks:

- [ ] Confirm baseline: `pytest tests/ -q` → 228 passed + 3 skipped (Spec 3 head on master)
- [ ] Branch:
  ```bash
  git checkout -b feat/coach-mode
  ```
- [ ] No new env vars, no new deps, no DB migration

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `app/coach/__init__.py` | empty package marker |
| `app/coach/persona.py` | `COACH_PERSONA` + `load_coach_persona(user_name)` |
| `app/coach/web_search.py` | `WEB_SEARCH_TOOL` constant + `tools_for_coach()` |
| `app/coach/signal_monitor.py` | `_detect_trigger`, `_recently_in_coach`, `run_coach_signal_check` |
| `app/coach/prompts/think.md` | THINK addendum loaded when active_flow=coach |
| `app/coach/prompts/react.md` | REACT addendum loaded when active_flow=coach |
| `tests/test_coach/__init__.py` | empty |
| `tests/test_coach/test_persona.py` | persona text smoke + name substitution |
| `tests/test_coach/test_web_search.py` | tool constant shape |
| `tests/test_coach/test_signal_monitor.py` | each signal in isolation |
| `tests/test_e2e_coach_smoke.py` | E2E multi-turn coach session via /api/conversation |

### Modified files

| Path | Change |
|---|---|
| `app/llm/router.py` | `complete()` accepts `tools` kwarg; extracts text from list-shaped content |
| `app/orchestrator/flows.py` | + `COACH` FlowDefinition + register |
| `app/orchestrator/actions.py` | + `END_COACH_SESSION` enum + `EndCoachSessionParams` + registry |
| `app/orchestrator/act.py` | + `_end_coach_session` + dispatch wiring + event mapping |
| `app/orchestrator/think.py` | append coach addendum to system prompt when `ctx.active_flow=="coach"` |
| `app/orchestrator/prompts/think.md` | + paragraph: detect coach entry phrases → emit start_flow(coach) |
| `app/orchestrator/react.py` | branch on `ctx.active_flow=="coach"`: coach persona, coach addendum, tools, max_tokens=2000, force reasoning |
| `app/orchestrator/triggers.py` | + `CoachOpeningTrigger` (Literal type, reason field), update `Trigger` union and `synthetic_message_for` |
| `app/orchestrator/proactive.py` | handle `CoachOpeningTrigger` (start_flow(coach) then REACT) |
| `app/scheduler/runtime.py` | register `run_coach_signal_check` daily 9am UTC cron |

### Not touched

- DB schema (reuses dialogue_session + events)
- pyproject.toml (no new deps)
- Spec 1/2/3 memory modules
- Frontend

---

## Task 1: Coach Persona

**Files:**
- Create: `app/coach/__init__.py` (empty)
- Create: `app/coach/persona.py`
- Create: `tests/test_coach/__init__.py` (empty)
- Create: `tests/test_coach/test_persona.py`

- [ ] **Step 1.1: Create package markers**

```bash
mkdir -p /Users/guoyuzhu/personal-assistant/app/coach
touch /Users/guoyuzhu/personal-assistant/app/coach/__init__.py
mkdir -p /Users/guoyuzhu/personal-assistant/tests/test_coach
touch /Users/guoyuzhu/personal-assistant/tests/test_coach/__init__.py
```

- [ ] **Step 1.2: Write failing test**

Create `tests/test_coach/test_persona.py`:

```python
from app.coach.persona import COACH_PERSONA, load_coach_persona


def test_persona_has_required_concepts():
    text = COACH_PERSONA.lower()
    for keyword in ["socratic", "first principles", "third-party", "ask", "don't tell"]:
        assert keyword in text, f"missing keyword: {keyword}"


def test_persona_substitutes_user_name():
    rendered = load_coach_persona("Alice")
    assert "Alice" in rendered
    assert "{user_name}" not in rendered


def test_load_coach_persona_default():
    rendered = load_coach_persona()
    assert "{user_name}" not in rendered


def test_persona_forbids_data_mutating():
    text = COACH_PERSONA.lower()
    # Persona must explicitly say it won't do transactional things
    assert "create tasks" in text or "modify goals" in text
```

- [ ] **Step 1.3: Run — expect ImportError**

```bash
source /Users/guoyuzhu/personal-assistant/.venv/bin/activate
pytest tests/test_coach/test_persona.py -v
```

- [ ] **Step 1.4: Create `app/coach/persona.py`**

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

- [ ] **Step 1.5: Run — expect PASS**

```bash
pytest tests/test_coach/test_persona.py -v
```

Expected: 4 passing.

- [ ] **Step 1.6: Full suite, commit**

```bash
pytest tests/ -q
git add app/coach/__init__.py app/coach/persona.py tests/test_coach/
git commit -m "feat: coach persona — third-party Socratic observer"
```

---

## Task 2: Coach Prompt Files

**Files:**
- Create: `app/coach/prompts/think.md`
- Create: `app/coach/prompts/react.md`

No tests — these are static text files loaded at runtime; coverage comes from Tasks 8 and 10 that exercise the loading.

- [ ] **Step 2.1: Create prompts dir**

```bash
mkdir -p /Users/guoyuzhu/personal-assistant/app/coach/prompts
```

- [ ] **Step 2.2: Create `app/coach/prompts/think.md`**

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

- [ ] **Step 2.3: Create `app/coach/prompts/react.md`**

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

- [ ] **Step 2.4: Full suite, commit**

```bash
cd /Users/guoyuzhu/personal-assistant
source .venv/bin/activate
pytest tests/ -q
git add app/coach/prompts/
git commit -m "feat: coach mode THINK + REACT prompt addenda"
```

---

## Task 3: Web Search Tool Constant

**Files:**
- Create: `app/coach/web_search.py`
- Create: `tests/test_coach/test_web_search.py`

- [ ] **Step 3.1: Write failing test**

Create `tests/test_coach/test_web_search.py`:

```python
from app.coach.web_search import WEB_SEARCH_TOOL, tools_for_coach


def test_web_search_tool_shape():
    assert WEB_SEARCH_TOOL["type"] == "web_search_20250305"
    assert WEB_SEARCH_TOOL["name"] == "web_search"


def test_tools_for_coach_returns_list_with_web_search():
    tools = tools_for_coach()
    assert isinstance(tools, list)
    assert len(tools) == 1
    assert tools[0]["name"] == "web_search"
```

- [ ] **Step 3.2: Run — expect ImportError**

```bash
source /Users/guoyuzhu/personal-assistant/.venv/bin/activate
pytest tests/test_coach/test_web_search.py -v
```

- [ ] **Step 3.3: Create `app/coach/web_search.py`**

```python
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}


def tools_for_coach() -> list[dict]:
    return [WEB_SEARCH_TOOL]
```

- [ ] **Step 3.4: Run — expect PASS, commit**

```bash
pytest tests/test_coach/test_web_search.py -v
pytest tests/ -q
git add app/coach/web_search.py tests/test_coach/test_web_search.py
git commit -m "feat: web_search tool constant for coach mode"
```

---

## Task 4: COACH FlowDefinition

**Files:**
- Modify: `app/orchestrator/flows.py`
- Modify: `tests/test_orchestrator/test_flows.py`

- [ ] **Step 4.1: Add failing tests**

Append to `tests/test_orchestrator/test_flows.py`:

```python
def test_coach_flow_exists_and_open_ended():
    from app.orchestrator.flows import COACH
    assert COACH.name == "coach"
    assert COACH.required_fields == ()


def test_get_flow_coach():
    coach = get_flow("coach")
    assert coach is not None
    assert coach.name == "coach"


def test_coach_flow_is_complete_with_anything():
    from app.orchestrator.flows import COACH
    # Open-ended flow → always complete; missing_fields always empty
    assert COACH.missing_fields({}) == []
    assert COACH.is_complete({}) is True
```

- [ ] **Step 4.2: Run — expect failure**

```bash
source /Users/guoyuzhu/personal-assistant/.venv/bin/activate
pytest tests/test_orchestrator/test_flows.py -v 2>&1 | tail -15
```

- [ ] **Step 4.3: Modify `app/orchestrator/flows.py`**

Read the file. After `ONBOARDING = FlowDefinition(...)` add:

```python
COACH = FlowDefinition(
    name="coach",
    required_fields=(),
)
```

Update `_REGISTRY`:

```python
_REGISTRY: dict[str, FlowDefinition] = {
    ONBOARDING.name: ONBOARDING,
    COACH.name: COACH,
}
```

- [ ] **Step 4.4: Run, commit**

```bash
pytest tests/test_orchestrator/test_flows.py -v
pytest tests/ -q
git add app/orchestrator/flows.py tests/test_orchestrator/test_flows.py
git commit -m "feat: COACH FlowDefinition (open-ended)"
```

---

## Task 5: END_COACH_SESSION Action Type

**Files:**
- Modify: `app/orchestrator/actions.py`
- Modify: `tests/test_orchestrator/test_actions.py`

- [ ] **Step 5.1: Add failing tests**

Append to `tests/test_orchestrator/test_actions.py`:

```python
from app.orchestrator.actions import EndCoachSessionParams


def test_end_coach_session_action_type_exists():
    assert ActionType.END_COACH_SESSION.value == "end_coach_session"


def test_end_coach_session_params_no_required_fields():
    p = EndCoachSessionParams()
    assert p is not None


def test_parse_action_end_coach_session():
    parsed = parse_action({"type": "end_coach_session", "params": {}})
    assert parsed.type == ActionType.END_COACH_SESSION
    assert isinstance(parsed.params, EndCoachSessionParams)
```

- [ ] **Step 5.2: Run — expect failure**

```bash
source /Users/guoyuzhu/personal-assistant/.venv/bin/activate
pytest tests/test_orchestrator/test_actions.py -v 2>&1 | tail -15
```

- [ ] **Step 5.3: Modify `app/orchestrator/actions.py`**

Read the file. In `class ActionType(str, Enum)`, append:

```python
    END_COACH_SESSION = "end_coach_session"
```

After the other Params classes (e.g. near `StartFlowParams`), add:

```python
class EndCoachSessionParams(BaseModel):
    """No params needed — finds active coach session and ends it."""
    pass
```

In `PARAM_REGISTRY`, add:

```python
    ActionType.END_COACH_SESSION: EndCoachSessionParams,
```

- [ ] **Step 5.4: Run, commit**

```bash
pytest tests/test_orchestrator/test_actions.py -v
pytest tests/ -q
git add app/orchestrator/actions.py tests/test_orchestrator/test_actions.py
git commit -m "feat: END_COACH_SESSION action type"
```

---

## Task 6: end_coach_session Dispatch in ActionExecutor

**Files:**
- Modify: `app/orchestrator/act.py`
- Modify: `tests/test_orchestrator/test_act.py`

- [ ] **Step 6.1: Add failing tests**

Append to `tests/test_orchestrator/test_act.py`:

```python
from app.models.dialogue_session import DialogueSession
from app.orchestrator.actions import EndCoachSessionParams


async def test_end_coach_session_closes_active_session(session):
    user = await _make_user(session, lark="coach_end_u1")
    s = DialogueSession(user_id=user.id, flow_type="coach", status="active")
    session.add(s)
    await session.commit()
    await session.refresh(s)

    executor = ActionExecutor(session)
    await executor.execute_all(
        user.id,
        [ParsedAction(ActionType.END_COACH_SESSION, EndCoachSessionParams())],
        conversation_id=None,
    )
    await session.refresh(s)
    assert s.status == "completed"


async def test_end_coach_session_no_active_session_is_noop(session):
    user = await _make_user(session, lark="coach_end_u2")
    executor = ActionExecutor(session)
    results = await executor.execute_all(
        user.id,
        [ParsedAction(ActionType.END_COACH_SESSION, EndCoachSessionParams())],
        conversation_id=None,
    )
    # No exception; payload reflects no-op
    assert results[0].type == ActionType.END_COACH_SESSION
    assert results[0].payload.get("ended") is False


async def test_end_coach_session_ignores_non_coach_flows(session):
    user = await _make_user(session, lark="coach_end_u3")
    s = DialogueSession(user_id=user.id, flow_type="onboarding", status="active")
    session.add(s)
    await session.commit()
    await session.refresh(s)

    executor = ActionExecutor(session)
    results = await executor.execute_all(
        user.id,
        [ParsedAction(ActionType.END_COACH_SESSION, EndCoachSessionParams())],
        conversation_id=None,
    )
    await session.refresh(s)
    assert s.status == "active"  # onboarding untouched
    assert results[0].payload.get("ended") is False
```

- [ ] **Step 6.2: Run — expect failure**

```bash
pytest tests/test_orchestrator/test_act.py::test_end_coach_session_closes_active_session -v
```

- [ ] **Step 6.3: Modify `app/orchestrator/act.py`**

Read the file. Imports already include `DialogueSession`, `desc` (verify with `grep -E 'DialogueSession|from sqlalchemy import' app/orchestrator/act.py`). Ensure `desc` is imported from sqlalchemy — if not, add `from sqlalchemy import desc, select, update`.

Add `EndCoachSessionParams` to the existing multi-import from `app.orchestrator.actions`:

```python
from app.orchestrator.actions import (
    ...,  # existing imports
    EndCoachSessionParams,
)
```

Add this new method on `ActionExecutor` (alongside other private dispatch methods):

```python
    async def _end_coach_session(
        self, user_id: int, p: EndCoachSessionParams
    ) -> ActionResult:
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
                type=ActionType.END_COACH_SESSION,
                entity_type="flow",
                entity_id=None,
                payload={"ended": False, "reason": "no active coach session"},
            )
        sess.status = "completed"
        await self.session.flush()
        return ActionResult(
            type=ActionType.END_COACH_SESSION,
            entity_type="flow",
            entity_id=sess.id,
            payload={"ended": True, "session_id": sess.id},
        )
```

In `_dispatch`, add (alongside other action handlers, before the trailing raise):

```python
        if action.type == ActionType.END_COACH_SESSION:
            return await self._end_coach_session(user_id, action.params)
```

In `_EVENT_TYPE_MAP` at the bottom, add:

```python
    ActionType.END_COACH_SESSION: "flow_completed",
```

(Reusing `flow_completed` event type — semantically a flow ending.)

- [ ] **Step 6.4: Run — expect PASS, commit**

```bash
pytest tests/test_orchestrator/test_act.py -v
pytest tests/ -q
git add app/orchestrator/act.py tests/test_orchestrator/test_act.py
git commit -m "feat: end_coach_session dispatch"
```

---

## Task 7: LLMRouter Tools Support

**Files:**
- Modify: `app/llm/router.py`
- Modify: `tests/test_llm/test_router.py`

- [ ] **Step 7.1: Add failing tests**

Append to `tests/test_llm/test_router.py`:

```python
from types import SimpleNamespace


async def test_complete_passes_tools_kwarg(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _FakeResponse("ok")

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    await router.complete(
        "react",
        [{"role": "user", "content": "hi"}],
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
    )
    assert captured.get("tools") == [{"type": "web_search_20250305", "name": "web_search"}]


async def test_complete_does_not_pass_tools_when_none(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _FakeResponse("ok")

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    await router.complete("react", [{"role": "user", "content": "hi"}])
    assert "tools" not in captured


async def test_complete_extracts_text_from_list_content(monkeypatch):
    """When tools are used, message.content may be a list of blocks."""
    content_blocks = [
        {"type": "tool_use", "name": "web_search", "input": {"query": "x"}},
        {"type": "tool_result", "tool_use_id": "x", "content": "search results"},
        {"type": "text", "text": "Based on my search, here's the answer."},
    ]
    fake_msg = SimpleNamespace(content=content_blocks)
    fake_choice = SimpleNamespace(message=fake_msg)
    fake_resp = SimpleNamespace(choices=[fake_choice])

    async def fake_acompletion(**kwargs):
        return fake_resp

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    result = await router.complete("react", [{"role": "user", "content": "hi"}])
    assert "Based on my search" in result
    assert "tool_use" not in result.lower()


async def test_complete_handles_multiple_text_blocks(monkeypatch):
    """Sometimes Claude emits multiple text blocks across a tool sequence."""
    content_blocks = [
        {"type": "text", "text": "Let me search first."},
        {"type": "tool_use", "name": "web_search", "input": {"query": "x"}},
        {"type": "tool_result", "tool_use_id": "x", "content": "results"},
        {"type": "text", "text": "Based on what I found, here's my reply."},
    ]
    fake_resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content_blocks))])

    async def fake_acompletion(**kwargs):
        return fake_resp

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    result = await router.complete("react", [{"role": "user", "content": "hi"}])
    assert "Let me search first" in result
    assert "Based on what I found" in result


async def test_complete_raises_when_only_tool_blocks(monkeypatch):
    """If response is all tool blocks with no text, we have nothing to return."""
    content_blocks = [
        {"type": "tool_use", "name": "web_search", "input": {"query": "x"}},
    ]
    fake_resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content_blocks))])

    async def fake_acompletion(**kwargs):
        return fake_resp

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    with pytest.raises(LLMError):
        await router.complete("react", [{"role": "user", "content": "hi"}])
```

(The existing tests use `_FakeResponse` already defined in this file. `pytest` already imported. `LLMError` likely already imported; if not, append `from app.llm.router import LLMError`.)

- [ ] **Step 7.2: Run — expect failures**

```bash
source /Users/guoyuzhu/personal-assistant/.venv/bin/activate
pytest tests/test_llm/test_router.py -v 2>&1 | tail -25
```

- [ ] **Step 7.3: Modify `app/llm/router.py`**

Replace the `complete()` method body. Current implementation is:

```python
    async def complete(
        self,
        task_type: TaskType,
        messages: list[dict],
        max_tokens: int = 1500,
        response_format: Optional[dict] = None,
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
        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as e:
            raise LLMError(f"LLM call failed: {e}") from e
        content = response.choices[0].message.content
        if content is None:
            raise LLMError("LLM returned empty content")
        return content
```

Replace with:

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
            text_parts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            content = "\n".join(p for p in text_parts if p)
        if content is None or content == "":
            raise LLMError("LLM returned empty content")
        return content
```

- [ ] **Step 7.4: Run — expect PASS, commit**

```bash
pytest tests/test_llm/test_router.py -v
pytest tests/ -q
git add app/llm/router.py tests/test_llm/test_router.py
git commit -m "feat: LLMRouter accepts tools + extracts text from list content"
```

---

## Task 8: THINK Coach Addendum Wiring

**Files:**
- Modify: `app/orchestrator/think.py`
- Modify: `tests/test_orchestrator/test_think.py`

- [ ] **Step 8.1: Add failing test**

Append to `tests/test_orchestrator/test_think.py`:

```python
async def test_think_appends_coach_addendum_when_active_flow_is_coach():
    router = _FakeRouter({
        "intent": "reflecting", "actions": [], "should_reply": True,
        "reply_complexity": "high", "reply_hint": "", "reasoning": "",
    })
    ctx = _empty_ctx(active_flow="coach")
    await think(ctx, "I'm stuck", router)
    system_msg = router.calls[0]["messages"][0]["content"]
    assert "COACH MODE ACTIVE" in system_msg
    # Default think prompt content also present (additive, not replacement)
    assert "personal assistant" in system_msg.lower() or "decision module" in system_msg.lower()


async def test_think_does_not_append_coach_addendum_in_normal_mode():
    router = _FakeRouter({
        "intent": "hi", "actions": [], "should_reply": True,
        "reply_complexity": "low", "reply_hint": "", "reasoning": "",
    })
    ctx = _empty_ctx(active_flow=None)
    await think(ctx, "hello", router)
    system_msg = router.calls[0]["messages"][0]["content"]
    assert "COACH MODE ACTIVE" not in system_msg
```

- [ ] **Step 8.2: Run — expect failure**

```bash
source /Users/guoyuzhu/personal-assistant/.venv/bin/activate
pytest tests/test_orchestrator/test_think.py::test_think_appends_coach_addendum_when_active_flow_is_coach -v
```

- [ ] **Step 8.3: Modify `app/orchestrator/think.py`**

Read the file. After the existing `_PROMPT_PATH` / `_SYSTEM_PROMPT` block, add:

```python
_COACH_ADDENDUM_PATH = Path(__file__).parent.parent / "coach" / "prompts" / "think.md"
_COACH_ADDENDUM: Optional[str] = None


def _load_coach_addendum() -> str:
    global _COACH_ADDENDUM
    if _COACH_ADDENDUM is None:
        _COACH_ADDENDUM = _COACH_ADDENDUM_PATH.read_text()
    return _COACH_ADDENDUM
```

Find the `async def think(...)` function. Locate this line (it builds the messages):

```python
async def think(ctx: Context, message: str, llm: LLMRouter) -> ThinkResult:
    messages = [
        {"role": "system", "content": _load_system_prompt()},
        {"role": "user", "content": _build_user_content(ctx, message)},
    ]
```

Replace the messages list construction with:

```python
async def think(ctx: Context, message: str, llm: LLMRouter) -> ThinkResult:
    system_prompt = _load_system_prompt()
    if ctx.active_flow == "coach":
        system_prompt = system_prompt + "\n\n" + _load_coach_addendum()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _build_user_content(ctx, message)},
    ]
```

- [ ] **Step 8.4: Run — expect PASS, commit**

```bash
pytest tests/test_orchestrator/test_think.py -v
pytest tests/ -q
git add app/orchestrator/think.py tests/test_orchestrator/test_think.py
git commit -m "feat: THINK appends coach addendum when active_flow=coach"
```

---

## Task 9: THINK Main Prompt — Coach Entry Detection

**Files:**
- Modify: `app/orchestrator/prompts/think.md`

No code test (prompts are text-only; runtime behavior verified by E2E in Task 16). Append the entry-detection paragraph at the end of the file.

- [ ] **Step 9.1: Append to `app/orchestrator/prompts/think.md`**

Append at the end with one blank line before:

```markdown

When the user signals they want reflective dialogue ("咱们聊聊 X", "帮我梳梳", "I need to think through X", "coach 模式", "let's talk about", "step back and look at X"), emit:
- `start_flow` with `flow_name="coach"` and context containing the topic.

Use this sparingly. Casual chat is not coach mode. Only trigger when the user actually wants to think through something.
```

- [ ] **Step 9.2: Run full suite, commit**

```bash
source /Users/guoyuzhu/personal-assistant/.venv/bin/activate
pytest tests/ -q
git add app/orchestrator/prompts/think.md
git commit -m "feat: THINK detects coach entry phrases → start_flow(coach)"
```

---

## Task 10: REACT Coach Mode Branch

**Files:**
- Modify: `app/orchestrator/react.py`
- Modify: `tests/test_orchestrator/test_react.py`

This is the largest single edit in this plan. Take care.

- [ ] **Step 10.1: Add failing tests**

Append to `tests/test_orchestrator/test_react.py`:

```python
async def test_react_uses_coach_persona_when_active_flow_coach():
    router = _FakeRouter("a coach reply")
    ctx = _ctx()
    ctx.active_flow = "coach"
    from app.orchestrator.react import react
    await react(ctx, "I'm stuck", action_results=[], hint=None, complexity="low", llm=router)
    sys_msg = router.calls[0]["messages"][0]["content"]
    assert "COACH MODE" in sys_msg or "coach mode" in sys_msg.lower()
    # Coach prompts/react.md content also present
    assert "Socratic" in sys_msg or "first principles" in sys_msg.lower()


async def test_react_passes_web_search_tool_in_coach_mode():
    router = _FakeRouter("ok")
    ctx = _ctx()
    ctx.active_flow = "coach"
    from app.orchestrator.react import react
    await react(ctx, "I'm stuck", action_results=[], hint=None, complexity="low", llm=router)
    call_kwargs = router.calls[0].get("kwargs", {})
    tools = call_kwargs.get("tools")
    assert tools is not None
    assert len(tools) == 1
    assert tools[0]["name"] == "web_search"


async def test_react_forces_reasoning_model_in_coach_mode():
    router = _FakeRouter("ok")
    ctx = _ctx()
    ctx.active_flow = "coach"
    from app.orchestrator.react import react
    await react(ctx, "I'm stuck", action_results=[], hint=None, complexity="low", llm=router)
    # Even though complexity="low", coach mode forces reasoning
    assert router.calls[0]["task_type"] == "reasoning"


async def test_react_normal_mode_no_tools():
    router = _FakeRouter("ok")
    ctx = _ctx()  # active_flow is None or non-coach
    from app.orchestrator.react import react
    await react(ctx, "hi", action_results=[], hint=None, complexity="low", llm=router)
    call_kwargs = router.calls[0].get("kwargs", {})
    assert call_kwargs.get("tools") is None
```

**Important**: the existing `_FakeRouter.complete` signature in `test_react.py` only captures `task_type` and `messages`. For these new tests to assert on `tools`, we need to update `_FakeRouter` to capture `**kwargs`. Read the existing class first; if it's:

```python
class _FakeRouter:
    def __init__(self, output): ...
    async def complete(self, task_type, messages):
        self.calls.append({"task_type": task_type, "messages": messages})
        return self.output
```

Modify it to:

```python
class _FakeRouter:
    def __init__(self, output): ...
    async def complete(self, task_type, messages, **kwargs):
        self.calls.append({"task_type": task_type, "messages": messages, "kwargs": kwargs})
        return self.output
```

(Don't remove anything other tests use; the new "kwargs" key is additive.)

- [ ] **Step 10.2: Run — expect failures**

```bash
source /Users/guoyuzhu/personal-assistant/.venv/bin/activate
pytest tests/test_orchestrator/test_react.py -v 2>&1 | tail -30
```

- [ ] **Step 10.3: Modify `app/orchestrator/react.py`**

Read the current file. Add to imports:

```python
from app.coach.persona import load_coach_persona
from app.coach.web_search import tools_for_coach
```

Add coach addendum loading helper (alongside `_load_template`):

```python
_COACH_REACT_ADDENDUM_PATH = Path(__file__).parent.parent / "coach" / "prompts" / "react.md"
_COACH_REACT_ADDENDUM: Optional[str] = None


def _load_coach_addendum() -> str:
    global _COACH_REACT_ADDENDUM
    if _COACH_REACT_ADDENDUM is None:
        _COACH_REACT_ADDENDUM = _COACH_REACT_ADDENDUM_PATH.read_text()
    return _COACH_REACT_ADDENDUM
```

Rewrite `react_or_raise` (replacing the existing function):

```python
async def react_or_raise(
    ctx: Context,
    message: str,
    action_results: list[dict],
    hint: Optional[str],
    complexity: Literal["low", "high"],
    llm: LLMRouter,
) -> str:
    """Same work as react() but propagates LLMError instead of returning a fallback."""
    is_coach = ctx.active_flow == "coach"

    if is_coach:
        system_prompt = load_coach_persona(ctx.user_name) + "\n\n" + _load_coach_addendum()
        tools = tools_for_coach()
        max_tokens = 2000
        task_type = "reasoning"
    else:
        system_prompt = _load_template().replace("{persona}", load_persona(ctx.user_name))
        tools = None
        max_tokens = 1500
        task_type = "reasoning" if complexity == "high" else "react"

    history = "\n".join(f"{t['role']}: {t['content']}" for t in ctx.recent_turns)
    recall_block = json.dumps(ctx.episodic_recall, ensure_ascii=False)
    user_content = (
        f"<conversation_history>\n{history}\n</conversation_history>\n"
        f"<episodic_recall>{recall_block}</episodic_recall>\n"
        f"<user_message>{message}</user_message>\n"
        f"<actions_completed>{json.dumps(action_results, ensure_ascii=False)}</actions_completed>\n"
        f"<hint>{hint or ''}</hint>"
    )

    return (await llm.complete(
        task_type,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_tokens=max_tokens,
        tools=tools,
    )).strip()
```

(`react()` wrapper stays unchanged — still calls `react_or_raise` and catches `LLMError`.)

- [ ] **Step 10.4: Run — expect PASS, commit**

```bash
pytest tests/test_orchestrator/test_react.py -v
pytest tests/ -q
git add app/orchestrator/react.py tests/test_orchestrator/test_react.py
git commit -m "feat: REACT coach mode — coach persona, web_search tool, reasoning model"
```

---

## Task 11: CoachOpeningTrigger Type

**Files:**
- Modify: `app/orchestrator/triggers.py`
- Modify: `tests/test_orchestrator/test_triggers.py`

- [ ] **Step 11.1: Add failing tests**

Append to `tests/test_orchestrator/test_triggers.py`:

```python
def test_coach_opening_trigger_requires_reason():
    from app.orchestrator.triggers import CoachOpeningTrigger
    with pytest.raises(ValidationError):
        CoachOpeningTrigger()


def test_coach_opening_trigger_carries_reason():
    from app.orchestrator.triggers import CoachOpeningTrigger
    t = CoachOpeningTrigger(reason="3-day silence")
    assert t.type == "coach_opening"
    assert t.reason == "3-day silence"


def test_synthetic_message_coach_opening_includes_reason():
    from app.orchestrator.triggers import CoachOpeningTrigger
    t = CoachOpeningTrigger(reason="task 'X' pushed 3 times")
    s = synthetic_message_for(t)
    assert "coach_opening" in s.lower() or "coach" in s.lower()
    assert "task 'X' pushed 3 times" in s
```

- [ ] **Step 11.2: Run — expect failure**

```bash
source /Users/guoyuzhu/personal-assistant/.venv/bin/activate
pytest tests/test_orchestrator/test_triggers.py -v 2>&1 | tail -15
```

- [ ] **Step 11.3: Modify `app/orchestrator/triggers.py`**

Read the file. Add a new pydantic class near the other trigger classes:

```python
class CoachOpeningTrigger(BaseModel):
    type: Literal["coach_opening"] = "coach_opening"
    reason: str
```

Update the `Trigger` union to include it:

```python
Trigger = Union[
    WelcomeTrigger,
    TaskCheckinTrigger,
    MorningBriefTrigger,
    EveningRecapTrigger,
    CoachOpeningTrigger,
]
```

In `synthetic_message_for`, add a branch (place near other isinstance branches):

```python
    if isinstance(trigger, CoachOpeningTrigger):
        return (
            f"[SYSTEM_TRIGGER:coach_opening] Begin a coach session. Reason: {trigger.reason}. "
            f"Open warmly with one question grounded in this signal."
        )
```

- [ ] **Step 11.4: Run, commit**

```bash
pytest tests/test_orchestrator/test_triggers.py -v
pytest tests/ -q
git add app/orchestrator/triggers.py tests/test_orchestrator/test_triggers.py
git commit -m "feat: CoachOpeningTrigger trigger type"
```

---

## Task 12: send_proactive handles CoachOpeningTrigger

**Files:**
- Modify: `app/orchestrator/proactive.py`
- Modify: `tests/test_orchestrator/test_proactive.py`

- [ ] **Step 12.1: Add failing tests**

Append to `tests/test_orchestrator/test_proactive.py`:

```python
async def test_send_proactive_coach_opening_starts_coach_flow(session):
    user = await _make_user(session, lark="coach_proactive_u1")
    router = _Router(react_text="Hey, I noticed something — want to take a look?")
    orch = ConversationOrchestrator(session=session, llm=router)
    from app.orchestrator.triggers import CoachOpeningTrigger
    out = await orch.send_proactive(
        user_id=user.id,
        trigger=CoachOpeningTrigger(reason="task X pushed 3 times"),
        complexity="high",
    )
    assert out is not None and "want to take a look" in out

    from sqlalchemy import select
    from app.models.dialogue_session import DialogueSession
    flows = (await session.execute(
        select(DialogueSession).where(DialogueSession.user_id == user.id)
    )).scalars().all()
    assert len(flows) == 1
    assert flows[0].flow_type == "coach"
    assert flows[0].status == "active"

    from app.models.event import Event
    events = (await session.execute(
        select(Event).where(Event.user_id == user.id)
    )).scalars().all()
    types = [e.type for e in events]
    assert "flow_started" in types
    assert "coach_opening_sent" in types


async def test_send_proactive_coach_opening_uses_reasoning_model(session):
    user = await _make_user(session, lark="coach_proactive_u2")
    router = _Router(react_text="reply")
    orch = ConversationOrchestrator(session=session, llm=router)
    from app.orchestrator.triggers import CoachOpeningTrigger
    await orch.send_proactive(
        user_id=user.id,
        trigger=CoachOpeningTrigger(reason="negative feedback"),
        complexity="high",
    )
    assert router.react_task_types == ["reasoning"]
```

- [ ] **Step 12.2: Run — expect failures**

```bash
source /Users/guoyuzhu/personal-assistant/.venv/bin/activate
pytest tests/test_orchestrator/test_proactive.py -v 2>&1 | tail -20
```

- [ ] **Step 12.3: Modify `app/orchestrator/proactive.py`**

Read the file. Find `send_proactive_impl`. It currently has an `isinstance(trigger, WelcomeTrigger)` branch that emits `start_flow(onboarding)` first.

Add a new branch right after the `WelcomeTrigger` block (or wherever fits), parallel structure:

```python
    elif isinstance(trigger, CoachOpeningTrigger):
        executor = ActionExecutor(session)
        await executor.execute_all(
            user_id=user_id,
            actions=[ParsedAction(
                ActionType.START_FLOW, StartFlowParams(flow_name="coach")
            )],
            conversation_id=None,
        )
        ctx = await load_context(user_id, session)
        hint = "warm, third-party observer; open with one question grounded in the reason"
```

Add to imports:

```python
from app.orchestrator.triggers import CoachOpeningTrigger
```

(If there's an existing `from app.orchestrator.triggers import ...` line, merge it in.)

- [ ] **Step 12.4: Run — expect PASS, commit**

```bash
pytest tests/test_orchestrator/test_proactive.py -v
pytest tests/ -q
git add app/orchestrator/proactive.py tests/test_orchestrator/test_proactive.py
git commit -m "feat: send_proactive handles CoachOpeningTrigger"
```

---

## Task 13: Coach Signal Monitor

**Files:**
- Create: `app/coach/signal_monitor.py`
- Test: `tests/test_coach/test_signal_monitor.py`

- [ ] **Step 13.1: Write failing tests**

Create `tests/test_coach/test_signal_monitor.py`:

```python
import pytest
from datetime import datetime, timedelta, timezone

from app.models.conversation import Conversation
from app.models.dialogue_session import DialogueSession
from app.models.event import Event
from app.models.task import Task
from app.models.user import User


async def test_detect_trigger_3day_silence(session):
    from app.coach.signal_monitor import _detect_trigger

    user = User(name="A", lark_user_id="sig_silence_u", preferences={})
    session.add(user)
    await session.commit()
    # Last user msg 4 days ago
    old = Conversation(user_id=user.id, role="user", content="hi")
    session.add(old)
    await session.commit()
    # Backdate it
    old.created_at = datetime.now(timezone.utc) - timedelta(days=4)
    await session.commit()

    reason = await _detect_trigger(session, user.id)
    assert reason is not None
    assert "days" in reason.lower() or "haven't" in reason.lower()


async def test_detect_trigger_no_silence_when_recent(session):
    from app.coach.signal_monitor import _detect_trigger

    user = User(name="A", lark_user_id="sig_recent_u", preferences={})
    session.add(user)
    await session.commit()
    msg = Conversation(user_id=user.id, role="user", content="hi")
    session.add(msg)
    await session.commit()

    reason = await _detect_trigger(session, user.id)
    # Recent message → silence signal doesn't fire (other signals also off)
    assert reason is None


async def test_detect_trigger_negative_feedback(session):
    from app.coach.signal_monitor import _detect_trigger

    user = User(name="A", lark_user_id="sig_neg_u", preferences={})
    session.add(user)
    await session.commit()
    # Recent user message (so silence signal off)
    session.add(Conversation(user_id=user.id, role="user", content="hi"))
    # Negative feedback within 24h
    session.add(Event(
        user_id=user.id, type="feedback_recorded",
        entity_type="feedback", entity_id=None,
        payload={"sentiment": "negative", "content": "this isn't helping"},
    ))
    await session.commit()

    reason = await _detect_trigger(session, user.id)
    assert reason is not None
    assert "happy" in reason.lower() or "feedback" in reason.lower() or "went" in reason.lower()


async def test_detect_trigger_3x_deferred_task(session):
    from app.coach.signal_monitor import _detect_trigger

    user = User(name="A", lark_user_id="sig_defer_u", preferences={})
    session.add(user)
    await session.commit()
    # Recent activity to silence the silence signal
    session.add(Conversation(user_id=user.id, role="user", content="hi"))
    # A pending task
    task = Task(user_id=user.id, title="write report", status="pending",
                deadline=datetime.now(timezone.utc) + timedelta(days=1))
    session.add(task)
    await session.commit()
    # 3 task_updated events with deadline changes
    for i in range(3):
        session.add(Event(
            user_id=user.id, type="task_updated",
            entity_type="task", entity_id=task.id,
            payload={
                "before": {"deadline": f"2026-05-{20+i}T00:00:00+00:00"},
                "after": {"deadline": f"2026-05-{21+i}T00:00:00+00:00"},
            },
        ))
    await session.commit()

    reason = await _detect_trigger(session, user.id)
    assert reason is not None
    assert "write report" in reason


async def test_detect_trigger_no_signal_returns_none(session):
    from app.coach.signal_monitor import _detect_trigger

    user = User(name="A", lark_user_id="sig_clean_u", preferences={})
    session.add(user)
    await session.commit()
    session.add(Conversation(user_id=user.id, role="user", content="hi"))
    await session.commit()

    reason = await _detect_trigger(session, user.id)
    assert reason is None


async def test_recently_in_coach_true_when_session_within_24h(session):
    from app.coach.signal_monitor import _recently_in_coach

    user = User(name="A", lark_user_id="sig_recent_coach_u", preferences={})
    session.add(user)
    await session.commit()
    sess = DialogueSession(user_id=user.id, flow_type="coach", status="completed")
    session.add(sess)
    await session.commit()

    assert await _recently_in_coach(session, user.id, hours=24) is True


async def test_recently_in_coach_false_when_no_session(session):
    from app.coach.signal_monitor import _recently_in_coach

    user = User(name="A", lark_user_id="sig_no_coach_u", preferences={})
    session.add(user)
    await session.commit()

    assert await _recently_in_coach(session, user.id, hours=24) is False
```

- [ ] **Step 13.2: Run — expect ImportError**

```bash
source /Users/guoyuzhu/personal-assistant/.venv/bin/activate
pytest tests/test_coach/test_signal_monitor.py -v
```

- [ ] **Step 13.3: Create `app/coach/signal_monitor.py`**

```python
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.dialogue_session import DialogueSession
from app.models.event import Event
from app.models.task import Task
from app.models.user import User

logger = logging.getLogger(__name__)

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


async def _detect_trigger(session: AsyncSession, user_id: int) -> Optional[str]:
    """Returns a trigger-reason string, or None if no signal is hot."""
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
        days = (now - last_user_msg.created_at).days
        return f"You haven't said anything in {days} days."

    # Signal B: recent negative feedback within 24h
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

    # Signal C: a single task has been task_updated'd with a deadline change >=3 times
    # and is still pending
    update_events_q = select(Event).where(
        Event.user_id == user_id,
        Event.type == "task_updated",
        Event.entity_type == "task",
    )
    updates = (await session.execute(update_events_q)).scalars().all()
    deferral_counts: dict[int, int] = {}
    for ev in updates:
        payload = ev.payload or {}
        before_deadline = (payload.get("before") or {}).get("deadline")
        after_deadline = (payload.get("after") or {}).get("deadline")
        if before_deadline != after_deadline and after_deadline is not None and ev.entity_id is not None:
            deferral_counts[ev.entity_id] = deferral_counts.get(ev.entity_id, 0) + 1
    over_threshold = sorted(
        [tid for tid, c in deferral_counts.items() if c >= DEFER_COUNT_THRESHOLD]
    )
    for tid in over_threshold:
        task = await session.get(Task, tid)
        if task and task.status == "pending":
            return f"'{task.title}' has been pushed {deferral_counts[tid]} times and is still on your list."

    return None


async def run_coach_signal_check() -> None:
    """Daily: scan all users, fire coach opening trigger if a signal is hot and user
    hasn't been in coach mode recently."""
    from app.database import async_session_factory
    from app.orchestrator.triggers import CoachOpeningTrigger
    from app.scheduler.jobs import _build_orchestrator

    async with async_session_factory() as session:
        users = (await session.execute(select(User))).scalars().all()
        for u in users:
            try:
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
            except Exception as e:
                logger.warning("coach signal check failed for user %s: %s", u.id, e)
```

- [ ] **Step 13.4: Run, commit**

```bash
pytest tests/test_coach/test_signal_monitor.py -v
pytest tests/ -q
git add app/coach/signal_monitor.py tests/test_coach/test_signal_monitor.py
git commit -m "feat: coach signal monitor — silence / negative feedback / 3x deferred task"
```

---

## Task 14: Register Coach Signal Cron

**Files:**
- Modify: `app/scheduler/runtime.py`
- Modify: `tests/test_scheduler/test_runtime.py`

- [ ] **Step 14.1: Add failing test**

Append to `tests/test_scheduler/test_runtime.py`:

```python
def test_register_jobs_includes_coach_signal_check():
    from app.scheduler.runtime import scheduler, register_jobs, _clear_jobs_for_test
    _clear_jobs_for_test()
    register_jobs()
    ids = {job.id for job in scheduler.get_jobs()}
    assert "coach_signal_check" in ids
    _clear_jobs_for_test()
```

- [ ] **Step 14.2: Run — expect failure**

```bash
source /Users/guoyuzhu/personal-assistant/.venv/bin/activate
pytest tests/test_scheduler/test_runtime.py::test_register_jobs_includes_coach_signal_check -v
```

- [ ] **Step 14.3: Modify `app/scheduler/runtime.py`**

In `register_jobs()`, add the import inside the existing `from app.scheduler.jobs import ...` block AND a fresh import for the coach module, then add a new `add_job` call. Final state should look like:

```python
def register_jobs() -> None:
    """Add interval + cron jobs. Idempotent: replaces existing job ids."""
    from app.scheduler.jobs import (
        run_scan_reminders,
        run_orchestrate_daily,
        run_expire_stale_checkins,
        run_memory_consolidation,
    )
    from app.coach.signal_monitor import run_coach_signal_check

    scheduler.add_job(run_scan_reminders, "interval", minutes=1,
                      id="scan_reminders", replace_existing=True)
    scheduler.add_job(run_orchestrate_daily, "cron", minute=0,
                      id="orchestrate_daily", replace_existing=True)
    scheduler.add_job(run_expire_stale_checkins, "interval", hours=1,
                      id="expire_stale_checkins", replace_existing=True)
    scheduler.add_job(run_memory_consolidation, "cron", hour=3, minute=0,
                      id="memory_consolidation", replace_existing=True)
    scheduler.add_job(run_coach_signal_check, "cron", hour=9, minute=0,
                      id="coach_signal_check", replace_existing=True)
```

- [ ] **Step 14.4: Run, commit**

```bash
pytest tests/test_scheduler/test_runtime.py -v
pytest tests/ -q
git add app/scheduler/runtime.py tests/test_scheduler/test_runtime.py
git commit -m "feat: register coach_signal_check daily cron"
```

---

## Task 15: E2E Coach Smoke

**Files:**
- Create: `tests/test_e2e_coach_smoke.py`

- [ ] **Step 15.1: Write the smoke test**

Create `tests/test_e2e_coach_smoke.py`:

```python
import pytest
from sqlalchemy import select

from app.models.dialogue_session import DialogueSession
from app.models.event import Event
from app.models.user import User


async def test_coach_session_full_loop(client, session, monkeypatch):
    """E2E: user invokes coach, has a multi-turn reflection, then ends the session."""

    user = User(name="X", lark_user_id="coach_e2e_u1", preferences={})
    session.add(user)
    await session.commit()

    think_script = [
        # Turn 1: user invokes coach
        {
            "intent": "user wants reflective dialogue about Q2 report",
            "actions": [{
                "type": "start_flow",
                "params": {"flow_name": "coach"},
            }],
            "should_reply": True, "reply_complexity": "high",
            "reply_hint": "open with one question", "reasoning": "",
        },
        # Turn 2: user replies (in coach mode now)
        {
            "intent": "user reflects",
            "actions": [],  # coach mode → no data mutations
            "should_reply": True, "reply_complexity": "high",
            "reply_hint": "ask one deeper question", "reasoning": "",
        },
        # Turn 3: user signals done
        {
            "intent": "user wants to end coach session",
            "actions": [{"type": "end_coach_session", "params": {}}],
            "should_reply": True, "reply_complexity": "low",
            "reply_hint": "warm closing", "reasoning": "",
        },
    ]
    react_script = [
        "Q2 报告这事儿挺重的——你觉得你真正卡在哪儿？",
        "嗯，那如果时间不是问题，你最担心的还是什么？",
        "好的，慢慢消化，需要再聊随时找我。",
    ]

    class _Router:
        def __init__(self, **_): pass
        async def complete_json(self, *a, **kw):
            return think_script.pop(0)
        async def complete(self, task_type, messages, **kw):
            return react_script.pop(0)
    monkeypatch.setattr("app.routers.conversation.LLMRouter", _Router)

    # Turn 1: invoke coach
    r1 = await client.post("/api/conversation",
                           json={"user_id": user.id, "message": "咱们聊聊 Q2 报告"})
    assert r1.status_code == 200
    flows = (await session.execute(
        select(DialogueSession).where(DialogueSession.user_id == user.id)
    )).scalars().all()
    assert len(flows) == 1
    assert flows[0].flow_type == "coach"
    assert flows[0].status == "active"

    # Turn 2: reflect
    r2 = await client.post("/api/conversation",
                           json={"user_id": user.id, "message": "我也不知道，就是不想开始"})
    assert r2.status_code == 200

    # Turn 3: end
    r3 = await client.post("/api/conversation",
                           json={"user_id": user.id, "message": "好，先这样，谢谢"})
    assert r3.status_code == 200

    await session.refresh(flows[0])
    assert flows[0].status == "completed"

    # Verify the events trail
    events = (await session.execute(
        select(Event).where(Event.user_id == user.id).order_by(Event.id)
    )).scalars().all()
    types = [e.type for e in events]
    assert "flow_started" in types
    assert types.count("flow_completed") >= 1  # end_coach_session emits flow_completed
```

- [ ] **Step 15.2: Run, expect PASS**

```bash
source /Users/guoyuzhu/personal-assistant/.venv/bin/activate
pytest tests/test_e2e_coach_smoke.py -v
```

If it fails:
- Confirm the START_FLOW action with `flow_name="coach"` actually creates a `DialogueSession` (Spec 1 `_start_flow` should do this; verify with `grep -A 6 "_start_flow" app/orchestrator/act.py`).
- Confirm `END_COACH_SESSION` finds the active coach session (Task 6).
- If THINK isn't called for the first turn (because the start_flow happens in ACT, not THINK), check the orchestrator pipeline ordering.

- [ ] **Step 15.3: Full suite, commit**

```bash
pytest tests/ -q
git add tests/test_e2e_coach_smoke.py
git commit -m "test: end-to-end coach session — invoke → reflect → end"
```

---

## Task 16: Live Sanity Check

Manual smoke test. Requires `PA_ANTHROPIC_API_KEY`. Optional: Anthropic web_search tool (verify it actually runs with real key).

- [ ] **Step 16.1: Boot server**

```bash
pkill -f "uvicorn app.main" 2>/dev/null
sleep 1
source /Users/guoyuzhu/personal-assistant/.venv/bin/activate
PA_PROACTIVE_DRY_RUN=true PA_ENABLE_SCHEDULER=true uvicorn app.main:app --port 8004 > /tmp/pa-coach-sanity.log 2>&1 &
sleep 5
curl -s http://localhost:8004/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 16.2: Create user + invoke coach**

```bash
USER_ID=$(psql -d my_assistant -tAc "INSERT INTO users (name, lark_user_id, preferences, created_at) VALUES ('CoachSanity', 'coach-sanity-$(date +%s)', '{}'::jsonb, now()) RETURNING id;" 2>/dev/null | head -1 | tr -d '[:space:]')
echo "user_id=[$USER_ID]"

curl -s -X POST http://localhost:8004/api/conversation \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":$USER_ID,\"message\":\"咱们聊聊我最近为什么提不起劲做事\"}" \
  | python3 -m json.tool
```

Expected: reply with a coach-style opening question. The DialogueSession table should show a new `coach` active flow.

```bash
psql -d my_assistant -tAc "SELECT flow_type, status FROM dialogue_sessions WHERE user_id=$USER_ID ORDER BY id DESC LIMIT 1;"
```

- [ ] **Step 16.3: Multi-turn**

```bash
curl -s -X POST http://localhost:8004/api/conversation \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":$USER_ID,\"message\":\"就是觉得这些事不重要，但又必须做\"}" \
  | python3 -m json.tool
```

Watch for Socratic question, no list dump, no task creation (verify no new tasks for this user).

- [ ] **Step 16.4: End session**

```bash
curl -s -X POST http://localhost:8004/api/conversation \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":$USER_ID,\"message\":\"行了，先这样，回头再说\"}" \
  | python3 -m json.tool

psql -d my_assistant -tAc "SELECT flow_type, status FROM dialogue_sessions WHERE user_id=$USER_ID ORDER BY id DESC LIMIT 1;"
```

Expected: flow status now `completed`.

- [ ] **Step 16.5: (Optional) Test signal monitor with simulated state**

Backdate a conversation to 4 days ago to trigger silence signal:

```bash
psql -d my_assistant -c "UPDATE conversations SET created_at = now() - interval '4 days' WHERE user_id=$USER_ID;"
```

Then run the signal monitor manually:

```bash
python3 - <<'PYEOF'
import asyncio
from app.coach.signal_monitor import run_coach_signal_check
asyncio.run(run_coach_signal_check())
print("done")
PYEOF
```

Check the new coach session got created (would normally push to Lark; in dry-run mode it just logs):

```bash
psql -d my_assistant -tAc "SELECT flow_type, status, created_at FROM dialogue_sessions WHERE user_id=$USER_ID ORDER BY id DESC LIMIT 2;"
```

- [ ] **Step 16.6: Stop server**

```bash
pkill -f "uvicorn app.main"
```

No commit — config-only.

---

## Plan Summary

After all tasks:

- ✅ Coach persona — third-party Socratic observer (Task 1)
- ✅ THINK + REACT coach prompt addenda (Task 2)
- ✅ Web search tool constant (Task 3)
- ✅ COACH flow definition (Task 4)
- ✅ END_COACH_SESSION action type (Task 5)
- ✅ end_coach_session ActionExecutor dispatch (Task 6)
- ✅ LLMRouter `tools` kwarg + structured content extraction (Task 7)
- ✅ THINK appends coach addendum when active_flow=coach (Task 8)
- ✅ Main THINK prompt detects coach entry phrases (Task 9)
- ✅ REACT coach mode branch (persona + tools + max_tokens + reasoning) (Task 10)
- ✅ CoachOpeningTrigger trigger type (Task 11)
- ✅ send_proactive handles CoachOpeningTrigger (Task 12)
- ✅ Coach signal monitor (3 signals) (Task 13)
- ✅ coach_signal_check cron registered (Task 14)
- ✅ E2E coach session smoke (Task 15)
- ✅ Live sanity guidance (Task 16)

Next: backlog items (no spec yet) — `_create_goal` schema fix, voice coach, RAG over user-curated knowledge.
