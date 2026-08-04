# Memory Refinement Design

**Date:** 2026-05-26
**Status:** Approved (pending user spec review)
**Depends on:** Spec 1 (Infrastructure bundle) + Spec 2 (Proactive agent)

## Goal

Make the assistant's memory actually behave like memory: it should not forget mid-day, it should remember relevant cross-day moments, it should clean up its own learned patterns rather than accumulating duplicates and contradictions, and goal progress should track itself automatically when related tasks complete.

## Scope

### In scope

- Pattern consolidation (LLM-driven dedupe, merge, contradiction resolution) via nightly cron
- Confidence dynamics: event-driven reinforcement and contradiction + exponential time decay
- Episodic vector search via pgvector + Voyage AI embeddings
- Today's-conversation-stays-fully-loaded + cross-day vector retrieval combined in `load_context`
- Goal progress auto-increment when linked tasks complete

### Out of scope

- Coach-mode insights (next spec)
- Re-summarizing very old conversations (rolling-window archive)
- Multi-language embedding quality tuning
- Quantitative goal progress estimation (this spec uses simple counter)
- Web frontend changes (memory is invisible to UI)

## Constraints / Principles

- **Don't forget mid-day.** Today's full conversation (both sides) goes into every turn's context, capped at a generous limit.
- **Don't drown in history.** Cross-day retrieval is similarity-gated — irrelevant matches are dropped silently.
- **Soft-fail.** Voyage outage, pgvector hiccup, consolidation LLM error → log warning, skip. Never break the conversation pipeline.
- **Fire-and-forget embeddings.** Generating an embedding for a new event/conversation runs after the main pipeline commits, in a background task. Worst case: that item won't be vector-recalled later; conversation itself is unaffected.
- **Conservative consolidation.** When dedup/merge confidence is low, KEEP both patterns. False merges damage user trust faster than redundancy does.

## Architecture

```
                              ┌───────────────────────────────────────┐
                              │  Spec 1+2 base                        │
                              │  (orchestrator + scheduler + Lark)    │
                              └────────────────┬──────────────────────┘
                                               │
                       ┌───────────────────────┼──────────────────────────┐
                       ▼                       ▼                          ▼
        ┌───────────────────────┐  ┌────────────────────┐  ┌─────────────────────┐
        │ Embedding writer      │  │ Consolidation cron │  │ Goal auto-update    │
        │ (fire-and-forget)     │  │ (nightly 3am UTC)  │  │ (act-side hook)     │
        │ on selected actions   │  │ patterns dedupe +  │  │ task_completed →    │
        │ + each user msg →     │  │   contradiction    │  │ if task.goal_id:    │
        │ embed → episodic_     │  │   resolution +     │  │   goals.current_    │
        │ embeddings row        │  │   confidence decay │  │     value += 1      │
        └───────────────────────┘  └────────────────────┘  └─────────────────────┘
                       │                       │
                       ▼                       ▼
                ┌───────────────────────────────────────────┐
                │  episodic_embeddings (NEW, pgvector)      │
                │  users.preferences.procedural (mutated)   │
                └───────────────────────────────────────────┘
                                  │
                                  ▼
                ┌───────────────────────────────────────────┐
                │  load_context (extended)                  │
                │   ├─ today's all turns (cap 60)           │
                │   ├─ yesterday tail of 5 if morning       │
                │   └─ vector top-3 cross-day (sim ≥ 0.7)   │
                └───────────────────────────────────────────┘
```

## Component 1: Embeddings + Voyage Client

### Voyage client

`app/services/voyage_client.py`:

```python
class VoyageClient:
    def __init__(self, api_key: str = settings.voyage_api_key):
        self._client = voyageai.AsyncClient(api_key=api_key)

    async def embed(self, text: str) -> list[float]:
        result = await self._client.embed([text], model="voyage-3")
        return result.embeddings[0]
```

`voyage-3` returns 1024-dim vectors. Cost: ~$0.06 per 1M tokens.

### Episodic embedding table

`app/models/episodic_embedding.py`:

```python
class EpisodicEmbedding(Base):
    __tablename__ = "episodic_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(20))   # "event" or "conversation"
    source_id: Mapped[int] = mapped_column()                # logical reference (no FK constraint)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

# Index for vector similarity search
Index("ix_episodic_embeddings_vec", "embedding",
      postgresql_using="ivfflat",
      postgresql_with={"lists": 100},
      postgresql_ops={"embedding": "vector_cosine_ops"})
```

### Alembic migration

```python
def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "episodic_embeddings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_id", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        "CREATE INDEX ix_episodic_embeddings_vec ON episodic_embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
```

Prerequisite: macOS user must `brew install pgvector` (or install via system package manager). Migration uses `CREATE EXTENSION IF NOT EXISTS` so re-runs are safe.

### Writer (`app/memory/embeddings.py`)

```python
EMBEDDABLE_EVENT_TYPES = {
    "feedback_recorded", "pattern_recorded", "profile_updated",
    "task_completed", "goal_set",
}
MIN_CONTENT_CHARS = 5
MAX_CONTENT_CHARS = 4000


async def embed_and_store(
    session: AsyncSession,
    user_id: int,
    source_type: Literal["event", "conversation"],
    source_id: int,
    content: str,
) -> None:
    if not content or len(content.strip()) < MIN_CONTENT_CHARS:
        return
    content = content[:MAX_CONTENT_CHARS]
    try:
        vec = await voyage_client.embed(content)
    except Exception as e:
        logger.warning("embed_and_store: voyage error: %s", e)
        return
    session.add(EpisodicEmbedding(
        user_id=user_id, source_type=source_type, source_id=source_id,
        content=content, embedding=vec,
    ))
    await session.commit()
```

### Integration: ActionExecutor

After `execute_all` commits successfully, schedule embedding tasks via `asyncio.create_task` (fire-and-forget). Each task opens its own DB session, calls `embed_and_store`. Failure logs but doesn't bubble back.

```python
# pseudo (real code uses session_factory)
for r in results:
    if r.type.value in EMBEDDABLE_EVENT_TYPES:
        asyncio.create_task(_background_embed(...))
```

### Integration: ConversationOrchestrator

After persisting the user message:

```python
asyncio.create_task(_background_embed(
    source_type="conversation", source_id=user_msg.id, content=user_msg.content,
))
```

Assistant replies are NOT embedded — keeps embedding noise lower; assistant text is recoverable from the user-message → reply link in conversations table if needed.

## Component 2: Retrieval (load_context Rewrite)

`app/orchestrator/context.py` constants:

```python
TODAY_TURNS_CAP = 60
YESTERDAY_TAIL = 5
EPISODIC_TOP_K = 3
EPISODIC_SIMILARITY_THRESHOLD = 0.7
MORNING_HOUR_CUTOFF = 12
```

### Signature change

```python
async def load_context(user_id: int, session: AsyncSession, query_text: str = "") -> Context: ...
```

`query_text` is the current user message (for vector search). When empty (e.g., proactive paths), vector search is skipped.

### Context fields (additions)

```python
@dataclass
class Context:
    # ... existing fields ...
    recent_turns: list[dict]              # CHANGED: today's all + yesterday tail
    episodic_recall: list[dict]           # NEW: cross-day vector top-3
```

`recent_turns` replaces the prior "last 10 turns" implementation. Yesterday tail is included only if both (a) today's turn count < YESTERDAY_TAIL and (b) it's before noon local time — heuristic for "user just woke up; carry over yesterday's tail."

### Cross-day vector recall

```python
async def _episodic_recall(session, user_id, query_text):
    if not query_text or len(query_text.strip()) < 5:
        return []
    try:
        query_vec = await voyage_client.embed(query_text)
    except Exception as e:
        logger.warning("recall embed failed: %s", e)
        return []
    q = (
        select(EpisodicEmbedding)
        .where(
            EpisodicEmbedding.user_id == user_id,
            EpisodicEmbedding.embedding.cosine_distance(query_vec) <= 1.0 - EPISODIC_SIMILARITY_THRESHOLD,
        )
        .order_by(EpisodicEmbedding.embedding.cosine_distance(query_vec))
        .limit(EPISODIC_TOP_K)
    )
    rows = (await session.execute(q)).scalars().all()
    return [
        {"source_type": r.source_type, "content": r.content, "date": r.created_at.isoformat()}
        for r in rows
    ]
```

### Today filter

User-timezone-aware. `today_start = now.astimezone(user_tz).replace(hour=0, ...).astimezone(UTC)`.

### THINK and REACT both see `episodic_recall`

THINK prompt addendum:

```markdown
<episodic_recall> is a small list of past events/messages the system retrieved as potentially relevant to the user's current message. It is NOT a complete history — only the top-3 vector-similar items above threshold. Use it to ground references like "as I mentioned last week" or to recall preferences the user already expressed. If the recall list is empty, do not pretend to remember.
```

REACT prompt addendum (in `prompts/react.md`):

```markdown
When `<episodic_recall>` contains items, you may naturally reference them when relevant ("yeah, like you mentioned X last week..."). Don't list them. Don't fabricate dates.
```

### Caller updates

- `ConversationOrchestrator.handle(user_id, message)` → calls `load_context(user_id, session, query_text=message)`
- `send_proactive(user_id, trigger, complexity)` → calls `load_context(user_id, session)` (no query_text; proactive doesn't need user-message-driven recall)

## Component 3: Pattern Consolidation (Nightly Cron)

### Schedule

New APScheduler job registered in `app/scheduler/runtime.py`:

```python
scheduler.add_job(run_memory_consolidation, "cron", hour=3, minute=0,
                  id="memory_consolidation", replace_existing=True)
```

3am UTC = night for Asia/Shanghai (~11am — daytime, not ideal), 7pm previous day for US Pacific. **For single-user MVP this is acceptable; future spec can per-user-tz the cron.**

### Wrapper

```python
async def run_memory_consolidation() -> None:
    async with async_session_factory() as session:
        users = (await session.execute(select(User))).scalars().all()
        for u in users:
            try:
                await consolidate_patterns(session, u.id)
                await decay_pattern_confidence(session, u.id)
            except Exception as e:
                logger.warning("memory consolidation failed for user %s: %s", u.id, e)
```

### consolidate_patterns (LLM-driven)

`app/memory/consolidation.py`:

```python
CONSOLIDATION_PROMPT = """You are a memory curator. Below is a user's accumulated procedural patterns
(things the assistant has learned about the user). Some may be:
- Near-duplicates: similar meaning, different wording → MERGE
- Contradictions: one says X, a newer one says NOT X → KEEP the newer, drop the older
- Stale: a pattern hasn't been validated by recent behavior → leave for time decay (don't touch here)

Input: list of patterns with id, text, confidence, learned_at.
Output ONLY JSON: {
  "drop_ids": [<int>...],
  "merged": [{"original_ids": [<int>...], "new_text": "<str>", "new_confidence": <float>}],
  "keep_unchanged": <bool>
}

Be conservative — when in doubt, KEEP both. Bias toward stability.
"""


async def consolidate_patterns(session: AsyncSession, user_id: int) -> dict:
    user = await session.get(User, user_id)
    prefs = UserPreferences.from_jsonb(user.preferences or {})
    if len(prefs.procedural) < 3:
        return {"unchanged": True}

    payload = [
        {"id": i, "pattern": p.pattern, "confidence": p.confidence, "learned_at": p.learned_at}
        for i, p in enumerate(prefs.procedural)
    ]
    try:
        result = await llm_router.complete_json("think", [
            {"role": "system", "content": CONSOLIDATION_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ])
    except Exception as e:
        logger.warning("consolidation LLM call failed: %s", e)
        return {"error": str(e)}

    new_procedural = _apply_consolidation(prefs.procedural, result)
    if len(new_procedural) == len(prefs.procedural):
        return {"unchanged": True}

    user.preferences = {**(user.preferences or {}), "procedural": [p.model_dump() for p in new_procedural]}
    session.add(Event(
        user_id=user_id, type="memory_consolidated", entity_type="memory", entity_id=None,
        payload={"before_count": len(prefs.procedural), "after_count": len(new_procedural)},
    ))
    await session.commit()
    return {"before": len(prefs.procedural), "after": len(new_procedural)}


def _apply_consolidation(original_patterns, result):
    drop_ids = set(result.get("drop_ids", []))
    merged = result.get("merged", [])
    merged_origin_ids = {oid for m in merged for oid in m.get("original_ids", [])}

    survivors = []
    for i, p in enumerate(original_patterns):
        if i in drop_ids or i in merged_origin_ids:
            continue
        survivors.append(p)

    now_iso = datetime.now(timezone.utc).isoformat()
    for m in merged:
        survivors.append(Pattern(
            pattern=m["new_text"],
            confidence=float(m.get("new_confidence", 0.5)),
            learned_at=now_iso,
            last_reinforced_at=now_iso,
        ))
    return survivors
```

### Model

THINK task type (Haiku in current router config). Cheap, JSON-out, suits taxonomy.

## Component 4: Confidence Dynamics

### Schema additions

`app/schemas/preferences.py`:

```python
class Pattern(BaseModel):
    pattern: str
    confidence: float = 0.5
    learned_at: Optional[str] = None
    last_reinforced_at: Optional[str] = None  # NEW
```

`last_reinforced_at` is set on creation (= `learned_at`) and refreshed by `reinforce_pattern` / `contradict_pattern` actions. Decay uses this as the elapsed-time baseline.

### Decay

`app/memory/confidence.py`:

```python
DAILY_DECAY_RATE = 0.99   # 1% per day; after ~70 days at full confidence, would drop to MIN
MIN_CONFIDENCE = 0.1


async def decay_pattern_confidence(session: AsyncSession, user_id: int) -> int:
    user = await session.get(User, user_id)
    prefs = UserPreferences.from_jsonb(user.preferences or {})
    survivors = []
    dropped = 0
    now = datetime.now(timezone.utc)
    for p in prefs.procedural:
        base = p.last_reinforced_at or p.learned_at
        try:
            base_dt = datetime.fromisoformat(base) if base else now
        except (ValueError, TypeError):
            base_dt = now
        days = max(0, (now - base_dt).days)
        new_conf = p.confidence * (DAILY_DECAY_RATE ** days)
        if new_conf < MIN_CONFIDENCE:
            dropped += 1
            continue
        survivors.append(Pattern(
            pattern=p.pattern, confidence=new_conf,
            learned_at=p.learned_at, last_reinforced_at=p.last_reinforced_at,
        ))
    if dropped:
        user.preferences = {**(user.preferences or {}), "procedural": [p.model_dump() for p in survivors]}
        await session.commit()
    return dropped
```

### Event-driven reinforce / contradict

New action types in `app/orchestrator/actions.py`:

```python
ActionType.REINFORCE_PATTERN = "reinforce_pattern"
ActionType.CONTRADICT_PATTERN = "contradict_pattern"


class ReinforcePatternParams(BaseModel):
    pattern_substring: str   # substring matcher to find existing pattern
    delta: float = 0.1


class ContradictPatternParams(BaseModel):
    pattern_substring: str
    delta: float = 0.3
```

`ActionExecutor._reinforce_pattern` / `_contradict_pattern` find the pattern by substring match (first match wins), bump confidence ±delta (clamped 0.0–1.0), refresh `last_reinforced_at`, persist users.preferences. They emit `pattern_reinforced` / `pattern_contradicted` events.

THINK prompt addendum:

```markdown
You can also emit:
- reinforce_pattern (params: pattern_substring, delta default 0.1): emit when the user's current behavior validates an existing learned pattern (look at <learned_patterns>). The substring should uniquely identify which pattern.
- contradict_pattern (params: pattern_substring, delta default 0.3): emit when the user's current behavior contradicts an existing learned pattern. Larger default delta because contradiction signal is stronger.

Do not emit reinforce/contradict if no specific existing pattern is the target. Don't emit them speculatively.
```

## Component 5: Goal Progress Auto-Increment

`app/orchestrator/act.py` `_complete_task` extension:

```python
async def _complete_task(self, user_id, p):
    task = await self.session.get(Task, p.task_id)
    if task is None or task.user_id != user_id:
        raise ValueError(f"task {p.task_id} not found for user")
    task.status = "done"
    await self.session.execute(
        update(Reminder)
        .where(Reminder.linked_task_id == p.task_id, Reminder.status == "pending")
        .values(status="cancelled")
    )
    # NEW: increment linked goal
    if task.goal_id is not None:
        goal = await self.session.get(Goal, task.goal_id)
        if goal is not None and goal.status == "active":
            goal.current_value = (goal.current_value or 0) + 1
    await self.session.flush()
    return ActionResult(
        type=ActionType.COMPLETE_TASK, entity_type="task", entity_id=task.id,
        payload={"completed_at": _now_iso(), "goal_incremented": task.goal_id is not None},
    )
```

This treats each linked task completion as +1 goal progress. UI displays `current_value / target_value <unit>` (e.g., "5 / 50 blog posts"). For quantitative goals where +1 is wrong (e.g., "run 42 km"), the user is expected to log distance manually via "I ran 5km today" → THINK emits a separate `update_goal` action. Future spec can let LLM estimate quantitative contribution.

## File Organization

### New files

```
app/memory/
├── __init__.py
├── embeddings.py
├── retrieval.py
├── consolidation.py
└── confidence.py

app/services/voyage_client.py
app/models/episodic_embedding.py
alembic/versions/<rev>_memory_refinement.py

tests/test_memory/
├── __init__.py
├── test_embeddings.py
├── test_retrieval.py
├── test_consolidation.py
└── test_confidence.py
tests/test_services/test_voyage_client.py
tests/test_models/test_episodic_embedding.py
```

### Modified files

| Path | Change |
|---|---|
| `pyproject.toml` | + `voyageai>=0.2.0`, + `pgvector>=0.2.0` |
| `app/config.py` | + `voyage_api_key: str = ""` |
| `app/schemas/preferences.py` | + `last_reinforced_at` field on `Pattern` |
| `app/orchestrator/actions.py` | + REINFORCE_PATTERN, CONTRADICT_PATTERN enums + param schemas |
| `app/orchestrator/act.py` | + `_reinforce_pattern`, `_contradict_pattern`; + goal increment in `_complete_task`; + post-commit fire-and-forget embed |
| `app/orchestrator/context.py` | Rewrite `recent_turns`, add `episodic_recall`, accept `query_text` |
| `app/orchestrator/conversation.py` | Pass `query_text=message` to `load_context`; fire-and-forget embed user message |
| `app/orchestrator/prompts/think.md` | + reinforce/contradict guidance + episodic_recall section |
| `app/orchestrator/prompts/react.md` | + episodic_recall usage guidance |
| `app/scheduler/jobs.py` | + `run_memory_consolidation` wrapper |
| `app/scheduler/runtime.py` | + register memory_consolidation cron in `register_jobs()` |

### Not touched

- Frontend
- Spec 2 worker / Lark integration
- Existing models (Goal, Habit, Task) — no schema changes needed (counter logic uses existing `current_value`)

## Testing Strategy

- **Unit**: each `app/memory/*` module with mocked Voyage + LLM. Confidence math, decay math, consolidation result-application logic.
- **Integration (sqlite)**: ActionExecutor goal increment, conversation orchestrator passing `query_text` through, `_reinforce_pattern` mutations. Vector tests SKIP on sqlite (pgvector is PG-only); add `@pytest.mark.skipif(database_url is sqlite, ...)` for those.
- **Integration (real PG)**: embedding writes + retrieval round-trip. Optional, gated on environment.
- **End-to-end smoke**: user creates goal → creates task linked to it → completes → goal.current_value increments.

`PA_VOYAGE_API_KEY` left empty in test env → embed silently returns and tests assert "no embedding row but no error."

## Implementation Order

1. `pyproject.toml` deps + `app/config.py` voyage env var
2. Alembic migration (CREATE EXTENSION + episodic_embeddings table)
3. `app/models/episodic_embedding.py`
4. `app/services/voyage_client.py` + tests
5. `app/memory/embeddings.py` (embed_and_store + EMBEDDABLE_EVENT_TYPES) + tests
6. ActionExecutor: fire-and-forget embed for embeddable event types
7. ConversationOrchestrator: fire-and-forget embed for user messages
8. `app/memory/retrieval.py` (vector search) + tests
9. `app/orchestrator/context.py` rewrite: today-all + yesterday-tail + episodic_recall + query_text param + tests
10. `app/orchestrator/conversation.py` pass query_text + tests
11. THINK prompt + REACT prompt addenda
12. `app/orchestrator/act.py` `_complete_task` goal increment + tests
13. `app/schemas/preferences.py` `last_reinforced_at` + tests
14. `app/orchestrator/actions.py` + REINFORCE_PATTERN, CONTRADICT_PATTERN
15. ActionExecutor: `_reinforce_pattern`, `_contradict_pattern` + tests
16. THINK prompt: reinforce/contradict guidance
17. `app/memory/confidence.py`: decay_pattern_confidence + tests
18. `app/memory/consolidation.py`: consolidate_patterns + _apply_consolidation + tests
19. `app/scheduler/jobs.py` `run_memory_consolidation` + `app/scheduler/runtime.py` register cron + tests
20. End-to-end smoke: user → goal → task → completion → progress; pattern → reinforce → confidence up
21. Live sanity check (manual)

## Roadmap (updated)

| Spec | Topic | Status |
|---|---|---|
| 1 | Infrastructure bundle | shipped |
| 2 | Proactive agent + Lark + daily prompts | shipped |
| 3 (this) | Memory refinement (consolidation, vector, decay, goal progress) | designing |
| 4 (was 5) | Coach mode / insight features | future |

## Persona compatibility

Memory refinement doesn't change persona text. But REACT now has richer context: `episodic_recall` makes natural references possible ("yeah, like last week when you mentioned X..."). The persona instruction "show, don't tell" applies — don't dump recall content verbatim; weave it.
