# Unified ReAct Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the Web assistant and Lark bot to one durable, account-aware ReAct runtime backed by LiteLLM, PostgreSQL, Redis/Celery, and live Web APIs.

**Architecture:** Both transports submit authenticated commands to `ConversationHub`, which persists an idempotent run before queueing it. A worker executes a bounded read-only ReAct loop, stores one structured final response, and lets each transport render it; mutations are available only through signed, single-use suggested-action clicks.

**Tech Stack:** Python 3.12, FastAPI 0.139, Pydantic 2.13, SQLAlchemy 2.0, Alembic 1.18, LiteLLM 1.90, Celery 5.6, Redis 8, PostgreSQL 17, Next.js 16, React 19, TypeScript 5.9, Vitest, Playwright, Pytest, Ruff, and mypy.

## Global Constraints

- The primary model is `openai/gpt-5.1` with `reasoning_effort=high`; the fallback is `openai/gpt-5-mini`.
- Web and Lark use the same `ConversationHub`, ReAct runtime, read-only tool registry, and final-response schema.
- The ReAct loop performs at most five iterations and never exposes private chain-of-thought.
- Natural-language requests cannot mutate business data; only a verified Web or Lark button click may execute a suggested action.
- One account represents one user. One family contains multiple accounts, and account-owned data is never merged.
- Family-visible records preserve `owner_account_id`; private conversations, runs, uploads, and feedback remain account-scoped.
- All source code, schema fields, API payloads, tests, and operational documentation are written in English.
- Existing local data must migrate without deletion.
- Every new behavior follows red-green-refactor TDD.

---

## File Structure

- `migrations/versions/0007_unified_runtime.py`: family membership, ownership, invitations, run state, and suggested-action schema migration.
- `src/recipe_agent/domain/identity/`: account/family membership, invitations, Lark linking, and session resolution.
- `src/recipe_agent/domain/conversation/`: durable run contracts, hub, bounded ReAct loop, and suggested actions.
- `src/recipe_agent/infrastructure/ai/react_model.py`: LiteLLM planner/final-answer adapter.
- `src/recipe_agent/infrastructure/db/`: run repository and transaction-safe queue publication.
- `src/recipe_agent/infrastructure/jobs/agent_runs.py`: Celery run execution and Lark completion delivery.
- `src/recipe_agent/infrastructure/lark/`: tenant token, inbound identity resolution, cards, and action callbacks.
- `src/recipe_agent/api/v1/`: auth, family, agent, action, and live feature-read endpoints.
- `web/src/lib/`: authenticated API client and polling hooks.
- `web/src/features/`: login, chat, settings, and live record components.
- `docs/runbooks/local-end-to-end.md`: local startup and complete manual test flow.

---

### Task 1: Family Membership, Ownership, and Durable Run Schema

**Files:**
- Create: `migrations/versions/0007_unified_runtime.py`
- Modify: `src/recipe_agent/domain/identity/models.py`
- Modify: `src/recipe_agent/domain/imports/contracts.py`
- Modify: `src/recipe_agent/domain/recipes/models.py`
- Modify: `src/recipe_agent/domain/planning/models.py`
- Modify: `src/recipe_agent/domain/feedback/models.py`
- Test: `tests/integration/db/test_unified_runtime_migration.py`
- Preserve: `src/recipe_agent/infrastructure/db/migrations.py`
- Preserve: `tests/unit/db/test_migrations.py`

**Interfaces:**
- Produces: `FamilyMembership`, `FamilyInvite`, expanded `Conversation`, expanded `AgentRun`, `SuggestedActionRecord`, and owner/visibility columns.
- Consumes: existing `Account`, `Household`, recipe, import, plan, feedback, and share tables.

- [ ] **Step 1: Write a failing migration integration test**

```python
async def test_migration_backfills_owner_membership_and_preserves_records(postgres_database) -> None:
    await postgres_database.upgrade("0006_operations")
    account_id, family_id, recipe_id = await postgres_database.seed_legacy_family_recipe()
    await postgres_database.upgrade("head")

    membership = await postgres_database.fetch_one(
        "SELECT account_id, household_id, role FROM family_memberships"
    )
    recipe = await postgres_database.fetch_one(
        "SELECT owner_account_id, visibility FROM recipes WHERE id = :id",
        {"id": recipe_id},
    )
    assert membership == (account_id, family_id, "owner")
    assert recipe == (account_id, "family")
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.venv/bin/python -m pytest tests/integration/db/test_unified_runtime_migration.py -v`

Expected: FAIL because revision `0007_unified_runtime` and `family_memberships` do not exist.

- [ ] **Step 3: Add the migration and matching ORM models**

The migration must create membership and invite tables, expand run persistence, and backfill ownership before setting new columns non-null:

```python
revision = "0007_unified_runtime"
down_revision = "0006_operations"

def upgrade() -> None:
    op.create_table(
        "family_memberships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("household_id", sa.Uuid(), sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.UniqueConstraint("account_id", "household_id", name="uq_family_membership"),
    )
    op.create_table(
        "family_invites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("household_id", sa.Uuid(), sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_by_account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="SET NULL")),
    )
```

Add `owner_account_id` and `visibility` to recipes and plans, `owner_account_id` to private imports/feedback/conversations, and the following run fields: `account_id`, `household_id`, `transport`, `idempotency_key`, `status`, `request_json`, `response_json`, `error_code`, `started_at`, and `completed_at`. Add a unique constraint on `(account_id, transport, idempotency_key)`. Create `suggested_actions` with token hash, run/account/family IDs, action type, arguments JSON, expiration, and consumption fields.

- [ ] **Step 4: Run migration tests and model tests GREEN**

Run: `.venv/bin/python -m pytest tests/integration/db/test_unified_runtime_migration.py tests/unit/db/test_migrations.py -v`

Expected: all tests pass and the legacy recipe remains present with an owner.

- [ ] **Step 5: Commit the schema slice**

```bash
git add migrations/versions/0007_unified_runtime.py src/recipe_agent/domain tests/integration/db/test_unified_runtime_migration.py src/recipe_agent/infrastructure/db/migrations.py tests/unit/db/test_migrations.py pyproject.toml uv.lock migrations/env.py
git commit -m "feat: add family ownership and agent run schema"
```

---

### Task 2: Sessions, Family Invitations, and Lark Account Linking

**Files:**
- Create: `src/recipe_agent/api/session.py`
- Create: `src/recipe_agent/api/v1/families.py`
- Modify: `src/recipe_agent/domain/identity/repository.py`
- Modify: `src/recipe_agent/domain/identity/service.py`
- Modify: `src/recipe_agent/api/v1/auth.py`
- Modify: `src/recipe_agent/api/dependencies.py`
- Modify: `src/recipe_agent/app.py`
- Test: `tests/e2e/test_identity_family_and_lark_linking.py`
- Test: `tests/security/test_session_scope.py`

**Interfaces:**
- Produces: `SessionScopeMiddleware`, `IdentityService.create_family_invite()`, `accept_family_invite()`, `create_lark_link_code()`, `resolve_lark_identity()`, and family APIs.
- Consumes: Task 1 membership/invite models and `HouseholdScope(account_id, household_id)`.

- [ ] **Step 1: Write failing identity and security tests**

```python
async def test_two_accounts_join_one_family_without_merging_identity(identity_service) -> None:
    owner = await identity_service.create_account("owner@example.com")
    member = await identity_service.create_account("member@example.com")
    invite = await identity_service.create_family_invite(owner.scope)
    joined = await identity_service.accept_family_invite(member.account.id, invite.code)
    assert joined.household_id == owner.scope.household_id
    assert joined.account_id == member.account.id
    assert joined.account_id != owner.scope.account_id

def test_session_cookie_resolves_account_and_family_scope(client, seeded_session) -> None:
    response = client.get("/api/v1/auth/session", cookies={"recipe_session": seeded_session.token})
    assert response.status_code == 200
    assert response.json()["account_id"] == str(seeded_session.account_id)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest tests/e2e/test_identity_family_and_lark_linking.py tests/security/test_session_scope.py -v`

Expected: FAIL because membership invite APIs and session middleware are missing.

- [ ] **Step 3: Implement identity services and middleware**

```python
class SessionScopeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        token = request.cookies.get("recipe_session")
        if token:
            request.state.household_scope = await self._identity.resolve_web_session(token)
        return await call_next(request)

class FamilyInviteResponse(BaseModel):
    code: str
    expires_at: datetime

@router.post("/invites", response_model=FamilyInviteResponse)
async def create_invite(scope: ScopeDependency, service: IdentityDependency) -> FamilyInviteResponse:
    return FamilyInviteResponse.model_validate(await service.create_family_invite(scope))
```

Add `POST /api/v1/families/invites`, `POST /api/v1/families/invites/accept`, `GET /api/v1/families/current`, `POST /api/v1/auth/lark-link-codes`, `GET /api/v1/auth/session`, and `DELETE /api/v1/auth/session`. In development only, `POST /magic-links` may include `development_token`; production always returns only `status=accepted`.

- [ ] **Step 4: Run identity, security, and existing auth tests GREEN**

Run: `.venv/bin/python -m pytest tests/e2e/test_identity_family_and_lark_linking.py tests/security/test_session_scope.py tests/integration/identity -v`

Expected: all pass; different accounts share one family scope without sharing account IDs.

- [ ] **Step 5: Commit the identity slice**

```bash
git add src/recipe_agent/api src/recipe_agent/domain/identity src/recipe_agent/app.py tests/e2e/test_identity_family_and_lark_linking.py tests/security/test_session_scope.py
git commit -m "feat: add family membership and identity linking flows"
```

---

### Task 3: Durable Conversation Hub and Queue Boundary

**Files:**
- Create: `src/recipe_agent/domain/conversation/hub.py`
- Create: `src/recipe_agent/domain/conversation/repository.py`
- Create: `src/recipe_agent/api/v1/agent.py`
- Create: `src/recipe_agent/infrastructure/jobs/agent_runs.py`
- Modify: `src/recipe_agent/domain/conversation/contracts.py`
- Modify: `src/recipe_agent/worker.py`
- Modify: `pyproject.toml`
- Test: `tests/integration/conversation/test_hub.py`
- Test: `tests/e2e/test_agent_runs_api.py`

**Interfaces:**
- Produces: `ConversationHub.submit_message()`, `AgentRunRepository.claim()`, `complete()`, `fail()`, `POST /api/v1/agent/runs`, and `GET /api/v1/agent/runs/{id}`.
- Consumes: Task 1 run schema and Task 2 authenticated scope.

- [ ] **Step 1: Write failing hub idempotency and ownership tests**

```python
async def test_submit_persists_before_publish_and_deduplicates(hub, publisher, command) -> None:
    first = await hub.submit_message(command)
    second = await hub.submit_message(command)
    assert first.id == second.id
    assert publisher.run_ids == [first.id]

def test_account_cannot_read_another_accounts_private_run(client, alice_run, bob_cookie) -> None:
    response = client.get(f"/api/v1/agent/runs/{alice_run.id}", cookies=bob_cookie)
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest tests/integration/conversation/test_hub.py tests/e2e/test_agent_runs_api.py -v`

Expected: FAIL because `ConversationHub` and the run router do not exist.

- [ ] **Step 3: Implement the hub, repository, API, and Celery task contract**

```python
class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class ConversationHub:
    async def submit_message(self, command: ConversationCommand) -> AgentRunView:
        run, created = await self._repository.create_idempotent(command)
        if created:
            await self._publisher.publish(run.id)
        return run

@router.post("/runs", status_code=202, response_model=AgentRunView)
async def submit_run(payload: SubmitRun, scope: ScopeDependency, hub: HubDependency) -> AgentRunView:
    return await hub.submit_message(payload.to_command(scope, transport="web"))
```

Add `celery>=5.6,<6` and `redis>=6,<7`. The Celery task accepts only a run UUID, creates its dependencies inside the worker process, claims the run atomically, and delegates execution. Queue publication must use the existing transactional outbox so a committed run can be republished after a transient broker failure.

- [ ] **Step 4: Run hub/API tests GREEN**

Run: `.venv/bin/python -m pytest tests/integration/conversation/test_hub.py tests/e2e/test_agent_runs_api.py tests/integration/db/test_outbox.py -v`

Expected: all pass; duplicate submissions publish one task and private runs return 404 to another account.

- [ ] **Step 5: Commit the durable hub slice**

```bash
git add pyproject.toml uv.lock src/recipe_agent/domain/conversation src/recipe_agent/api/v1/agent.py src/recipe_agent/infrastructure/jobs src/recipe_agent/worker.py tests/integration/conversation tests/e2e/test_agent_runs_api.py
git commit -m "feat: add durable shared conversation hub"
```

---

### Task 4: LiteLLM Bounded ReAct Runtime

**Files:**
- Create: `src/recipe_agent/domain/conversation/react.py`
- Create: `src/recipe_agent/domain/conversation/responses.py`
- Create: `src/recipe_agent/infrastructure/ai/react_model.py`
- Modify: `src/recipe_agent/config.py`
- Modify: `.env.example`
- Test: `tests/unit/conversation/test_react.py`
- Test: `tests/contract/ai/test_react_model.py`

**Interfaces:**
- Produces: `ReactAgent.run(context) -> FinalAgentResponse`, `ReactDecision`, `SuggestedActionDraft`, and `LiteLLMReactModel.decide()`.
- Consumes: Task 3 claimed run and a `ReadOnlyToolRegistry` delivered by Task 5.

- [ ] **Step 1: Write failing bounded-loop and output-safety tests**

```python
async def test_react_stops_after_five_tool_iterations(model, tools) -> None:
    model.always_call("search_family_recipes", {"query": "dinner"})
    response = await ReactAgent(model=model, tools=tools, max_iterations=5).run(context())
    assert tools.calls == 5
    assert response.answer
    assert response.private_reasoning is None

async def test_model_cannot_request_mutation_tool(model, tools) -> None:
    model.call_tool("save_recipe", {})
    with pytest.raises(UnknownReadOnlyToolError):
        await ReactAgent(model=model, tools=tools).run(context())
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest tests/unit/conversation/test_react.py tests/contract/ai/test_react_model.py -v`

Expected: FAIL because ReAct contracts and model adapter do not exist.

- [ ] **Step 3: Implement the state machine and LiteLLM adapter**

```python
class FinalAgentResponse(BaseModel):
    thinking: str = Field(min_length=1, max_length=800)
    plan: str = Field(min_length=1, max_length=1200)
    act: str = Field(min_length=1, max_length=1200)
    answer: str = Field(min_length=1, max_length=8000)
    suggested_actions: tuple[SuggestedActionDraft, ...] = Field(default=(), max_length=3)

class ReactAgent:
    async def run(self, context: AgentContext) -> FinalAgentResponse:
        observations: list[ToolObservation] = []
        for _ in range(self._max_iterations):
            decision = await self._model.decide(context, tuple(observations))
            if decision.final is not None:
                return decision.final
            observations.append(await self._tools.execute(decision.tool_call))
        return await self._model.finish(context, tuple(observations))
```

`LiteLLMReactModel` passes `model`, `reasoning_effort`, timeout, structured response schema, and read-only tool definitions to `litellm.acompletion`. It performs bounded retry, switches once to the fallback model on provider failure, and makes one schema-repair call. Settings fields are `litellm_chat_model`, `litellm_fallback_model`, `litellm_reasoning_effort`, `litellm_timeout_seconds`, `litellm_max_retries`, and `react_max_iterations`.

- [ ] **Step 4: Run ReAct and existing LiteLLM contract tests GREEN**

Run: `.venv/bin/python -m pytest tests/unit/conversation/test_react.py tests/contract/ai -v`

Expected: all pass; no mutation tool is callable and the sixth iteration never runs.

- [ ] **Step 5: Commit the ReAct slice**

```bash
git add src/recipe_agent/domain/conversation src/recipe_agent/infrastructure/ai src/recipe_agent/config.py .env.example tests/unit/conversation/test_react.py tests/contract/ai/test_react_model.py
git commit -m "feat: add bounded LiteLLM ReAct runtime"
```

---

### Task 5: Read-only Agent Tools and Live Feature APIs

**Files:**
- Create: `src/recipe_agent/domain/conversation/read_tools.py`
- Create: `src/recipe_agent/api/v1/recipes.py`
- Create: `src/recipe_agent/api/v1/imports.py`
- Create: `src/recipe_agent/api/v1/settings.py`
- Create: `src/recipe_agent/api/v1/feature_reads.py`
- Modify: existing recipe, planning, sharing, feedback repositories
- Test: `tests/integration/conversation/test_read_tools.py`
- Test: `tests/e2e/test_live_feature_apis.py`
- Test: `tests/security/test_family_visibility.py`

**Interfaces:**
- Produces: `ReadOnlyToolRegistry`, live list/detail endpoints, and owner-attributed resource DTOs.
- Consumes: Task 1 ownership columns and Task 2 scope.

- [ ] **Step 1: Write failing owner-attribution and isolation tests**

```python
async def test_family_recipe_search_keeps_each_owner(tools, alice, bob, shared_family) -> None:
    rows = await tools.execute(call("search_family_recipes", {"query": "tomato"}), alice.scope)
    assert {row["owner_account_id"] for row in rows.data["recipes"]} == {alice.id, bob.id}

def test_live_recipe_api_rejects_other_family(client, alice_cookie, outsider_recipe) -> None:
    response = client.get(f"/api/v1/recipes/{outsider_recipe.id}", cookies=alice_cookie)
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest tests/integration/conversation/test_read_tools.py tests/e2e/test_live_feature_apis.py tests/security/test_family_visibility.py -v`

Expected: FAIL because tools and list/read endpoints are missing.

- [ ] **Step 3: Implement read tools and DTO endpoints**

```python
READ_ONLY_TOOLS: dict[str, ReadOnlyTool] = {
    "search_own_recipes": SearchOwnRecipesTool(recipe_queries),
    "search_family_recipes": SearchFamilyRecipesTool(recipe_queries),
    "read_dietary_preferences": ReadDietaryPreferencesTool(settings_queries),
    "read_plans": ReadPlansTool(plan_queries),
    "read_shopping_lists": ReadShoppingListsTool(shopping_queries),
    "recommend_three": RecommendThreeTool(recommendation_service),
    "preview_recipe_import": PreviewRecipeImportTool(import_service),
    "preview_plan_change": PreviewPlanChangeTool(planning_service),
}
```

Add authenticated DTO endpoints for recipes, plans, shopping lists, imports, shares, settings, members, and Lark binding status. Every list item includes `owner_account_id`, `owner_display_name`, and `is_owned_by_current_account`; private endpoints filter by account before family.

- [ ] **Step 4: Run tools, API, and security tests GREEN**

Run: `.venv/bin/python -m pytest tests/integration/conversation/test_read_tools.py tests/e2e/test_live_feature_apis.py tests/security/test_family_visibility.py -v`

Expected: all pass; family results contain both owners while cross-family/private records stay hidden.

- [ ] **Step 5: Commit the read-model slice**

```bash
git add src/recipe_agent/domain src/recipe_agent/api/v1 tests/integration/conversation/test_read_tools.py tests/e2e/test_live_feature_apis.py tests/security/test_family_visibility.py
git commit -m "feat: add family-aware read tools and live APIs"
```

---

### Task 6: Signed Suggested Actions and Explicit-click Mutations

**Files:**
- Create: `src/recipe_agent/domain/conversation/actions.py`
- Create: `src/recipe_agent/api/v1/actions.py`
- Modify: `src/recipe_agent/infrastructure/lark/crypto.py`
- Modify: `src/recipe_agent/domain/conversation/repository.py`
- Test: `tests/e2e/test_suggested_actions.py`
- Test: `tests/security/test_suggested_action_security.py`

**Interfaces:**
- Produces: `SuggestedActionService.issue()`, `consume()`, and `POST /api/v1/agent/actions/{token}`.
- Consumes: Task 4 `SuggestedActionDraft` and existing domain mutation services.

- [ ] **Step 1: Write failing one-time consent tests**

```python
def test_natural_language_run_does_not_write_recipe(client, authenticated_cookie) -> None:
    run = submit_and_complete(client, "Save this recipe", authenticated_cookie)
    assert run["suggested_actions"][0]["type"] == "save_recipe"
    assert count_recipes() == 0

def test_action_click_executes_once(client, issued_action, authenticated_cookie) -> None:
    first = client.post(f"/api/v1/agent/actions/{issued_action.token}", cookies=authenticated_cookie)
    second = client.post(f"/api/v1/agent/actions/{issued_action.token}", cookies=authenticated_cookie)
    assert first.status_code == 200
    assert second.status_code == 409
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest tests/e2e/test_suggested_actions.py tests/security/test_suggested_action_security.py -v`

Expected: FAIL because action issuance and consumption do not exist.

- [ ] **Step 3: Implement issuance, verification, dispatch, and audit**

```python
class SuggestedActionService:
    async def consume(self, token: str, actor: HouseholdScope) -> ActionResult:
        claims = self._signer.loads(token)
        action = await self._repository.claim_once(hash_token(token), actor, claims)
        handler = self._handlers[action.action_type]
        result = await handler.execute(actor=actor, arguments=action.arguments)
        await self._repository.complete(action.id, actor.account_id, result)
        return result
```

Allow only `save_recipe`, `create_plan`, `replace_plan_item`, and `create_share`. The repository atomically sets consumption state before execution and stores completion or failure. Account/family/run claims must match the authenticated actor. Tokens expire after the configured lifetime.

- [ ] **Step 4: Run action and security tests GREEN**

Run: `.venv/bin/python -m pytest tests/e2e/test_suggested_actions.py tests/security/test_suggested_action_security.py -v`

Expected: all pass; text alone writes nothing, a valid click writes once, and forged/replayed tokens fail.

- [ ] **Step 5: Commit the action slice**

```bash
git add src/recipe_agent/domain/conversation src/recipe_agent/api/v1/actions.py src/recipe_agent/infrastructure/lark/crypto.py tests/e2e/test_suggested_actions.py tests/security/test_suggested_action_security.py
git commit -m "feat: require explicit clicks for agent mutations"
```

---

### Task 7: Lark Runtime Composition and Shared Hub Delivery

**Files:**
- Create: `src/recipe_agent/infrastructure/lark/token.py`
- Create: `src/recipe_agent/infrastructure/lark/delivery.py`
- Modify: `src/recipe_agent/api/lark.py`
- Modify: `src/recipe_agent/infrastructure/lark/normalizer.py`
- Modify: `src/recipe_agent/infrastructure/lark/renderer.py`
- Modify: `src/recipe_agent/infrastructure/lark/client.py`
- Modify: `src/recipe_agent/infrastructure/jobs/agent_runs.py`
- Test: `tests/contract/lark/test_shared_hub.py`
- Test: `tests/e2e/test_lark_bound_conversation.py`

**Interfaces:**
- Produces: `LarkTenantTokenProvider`, identity-aware inbound event handling, final cards, and card-action execution.
- Consumes: Tasks 2, 3, 4, and 6.

- [ ] **Step 1: Write failing linked/unlinked and shared-hub tests**

```python
async def test_bound_lark_message_submits_to_shared_hub(handler, hub, bound_open_id, event) -> None:
    result = await handler.handle(event)
    assert result == {"status": "accepted"}
    assert hub.commands[0].transport == "lark"
    assert hub.commands[0].account_id == bound_open_id.account_id

async def test_unbound_sender_receives_linking_instructions(handler, lark_client, event) -> None:
    await handler.handle(event)
    assert "link" in lark_client.sent_text.casefold()
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest tests/contract/lark/test_shared_hub.py tests/e2e/test_lark_bound_conversation.py -v`

Expected: FAIL because the handler still uses a statically constructed normalizer and has no token provider/completion delivery.

- [ ] **Step 3: Implement Lark identity resolution, token acquisition, and cards**

```python
class LarkTenantTokenProvider:
    async def tenant_access_token(self) -> str:
        response = await self._http.post(
            f"{self._base_url}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        return TenantTokenResponse.model_validate(response.json()).tenant_access_token

class LarkInboundService:
    async def receive(self, event: NormalizedLarkEvent) -> None:
        scope = await self._identity.resolve_lark_identity(event.open_id)
        if scope is None:
            await self._delivery_queue.publish_linking_instructions(
                event.chat_id,
                event.locale,
                event.event_id,
            )
            return
        await self._hub.submit_message(event.to_command(scope))
```

The webhook performs no outbound Lark API call and acknowledges within three seconds after durable publication. A delivery worker sends linking instructions for an unbound sender. Agent worker completion renders `Thinking`, `Plan`, `Act`, `Answer`, and up to three signed action buttons. Card callbacks resolve the clicking Open ID and call the same Task 6 action service.

- [ ] **Step 4: Run all Lark tests GREEN**

Run: `.venv/bin/python -m pytest tests/contract/lark tests/unit/lark tests/e2e/test_lark_bound_conversation.py -v`

Expected: all pass; inbound Web/Lark commands have the same hub contract and action clicks preserve actor identity.

- [ ] **Step 5: Commit the Lark slice**

```bash
git add src/recipe_agent/api/lark.py src/recipe_agent/infrastructure/lark src/recipe_agent/infrastructure/jobs/agent_runs.py tests/contract/lark tests/e2e/test_lark_bound_conversation.py
git commit -m "feat: connect Lark bot to shared ReAct hub"
```

---

### Task 8: FastAPI Composition Root and Local Runtime

**Files:**
- Create: `src/recipe_agent/bootstrap.py`
- Modify: `src/recipe_agent/app.py`
- Modify: `src/recipe_agent/config.py`
- Modify: `src/recipe_agent/worker.py`
- Modify: `infra/compose.yaml`
- Modify: `Makefile`
- Test: `tests/integration/test_runtime_composition.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `build_runtime(settings) -> Runtime`, populated `app.state`, worker dependency factory, and local commands.
- Consumes: all prior backend tasks.

- [ ] **Step 1: Write a failing composition smoke test**

```python
def test_development_app_wires_every_required_service(test_settings) -> None:
    app = create_app(test_settings)
    for name in (
        "identity_service", "conversation_hub", "agent_run_service",
        "suggested_action_service", "recommendation_service", "planning_service",
        "lark_handler",
    ):
        assert getattr(app.state, name) is not None
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest tests/integration/test_runtime_composition.py tests/unit/test_config.py -v`

Expected: FAIL because the current app wires only identity and metrics.

- [ ] **Step 3: Implement one composition root for API and worker**

```python
@dataclass
class Runtime:
    identity_service: IdentityService
    conversation_hub: ConversationHub
    agent_run_service: AgentRunService
    suggested_action_service: SuggestedActionService
    recommendation_service: RecommendationService
    planning_service: PlanningService
    lark_handler: LarkWebhookHandler

def build_runtime(settings: Settings) -> Runtime:
    session_factory = create_session_factory(settings)
    return Runtime(...)
```

`create_app()` installs security and session middleware, assigns every runtime service to `app.state`, and includes every router. `create_worker()` uses the same factory. Add `make run-worker`, `make run-web`, and `make local-up`; compose must provide health-checked PostgreSQL, Redis, and MinIO without embedding production secrets.

- [ ] **Step 4: Run composition and API smoke tests GREEN**

Run: `.venv/bin/python -m pytest tests/integration/test_runtime_composition.py tests/unit/test_config.py tests/unit/test_app.py -v`

Expected: all pass and every router dependency resolves without manual test overrides.

- [ ] **Step 5: Commit the runtime slice**

```bash
git add src/recipe_agent/bootstrap.py src/recipe_agent/app.py src/recipe_agent/config.py src/recipe_agent/worker.py infra/compose.yaml Makefile tests/integration/test_runtime_composition.py tests/unit/test_config.py
git commit -m "feat: wire complete local application runtime"
```

---

### Task 9: Web Authentication and Real Agent Chat

**Files:**
- Create: `web/src/lib/api.ts`
- Create: `web/src/lib/use-agent-run.ts`
- Create: `web/src/features/auth/login.tsx`
- Create: `web/src/features/chat/chat-thread.tsx`
- Create: `web/src/features/chat/suggested-actions.tsx`
- Modify: `web/src/features/chat/chat-home.tsx`
- Modify: `web/src/app/chat/page.tsx`
- Modify: `web/src/i18n/en-US.json`
- Modify: `web/src/i18n/zh-CN.json`
- Test: `web/tests/chat-runtime.test.tsx`
- Test: `web/tests/auth.test.tsx`

**Interfaces:**
- Produces: cookie-authenticated API client, run polling, real chat thread, and action buttons.
- Consumes: Tasks 2, 3, and 6 HTTP APIs.

- [ ] **Step 1: Write failing Web interaction tests**

```tsx
it("submits a message, polls the run, and renders one structured answer", async () => {
  server.queueRun({ status: "queued" }, completedRun);
  render(<ChatHome />);
  await user.type(screen.getByRole("textbox"), "Recommend dinner");
  await user.click(screen.getByRole("button", { name: "Ask assistant" }));
  expect(await screen.findByText("Thinking")).toBeVisible();
  expect(screen.getByText(completedRun.response.answer)).toBeVisible();
});

it("does not execute a suggested action until its button is clicked", async () => {
  renderCompletedRunWithAction();
  expect(server.actionCalls).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "Save recipe" }));
  expect(server.actionCalls).toHaveLength(1);
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pnpm --dir web test -- chat-runtime.test.tsx auth.test.tsx`

Expected: FAIL because Chat is static and there is no API client or login flow.

- [ ] **Step 3: Implement login, polling, structured response, and buttons**

```ts
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { "content-type": "application/json", ...init?.headers },
  });
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.status === 204 ? (undefined as T) : response.json();
}
```

`useAgentRun` posts once with a stable idempotency key, polls queued/running runs, stops on completed/failed, and cancels timers on unmount. Render one localized page and keep the section labels consistent across Web and Lark.

- [ ] **Step 4: Run Web unit, type, and lint checks GREEN**

Run: `pnpm --dir web test && pnpm --dir web typecheck && pnpm --dir web lint`

Expected: all pass with no timer leaks or TypeScript errors.

- [ ] **Step 5: Commit the Web chat slice**

```bash
git add web/src/lib web/src/features/auth web/src/features/chat web/src/app/chat web/src/i18n web/tests
git commit -m "feat: connect Web assistant to shared agent API"
```

---

### Task 10: Replace Static Feature Pages with Live Account-aware Data

**Files:**
- Create: `web/src/lib/use-feature-data.ts`
- Create: `web/src/features/records/live-feature-screen.tsx`
- Create: `web/src/features/settings/account-family-settings.tsx`
- Modify: `web/src/app/recipes/page.tsx`
- Modify: `web/src/app/plan/page.tsx`
- Modify: `web/src/app/shopping/page.tsx`
- Modify: `web/src/app/imports/page.tsx`
- Modify: `web/src/app/shares/page.tsx`
- Modify: `web/src/app/settings/page.tsx`
- Test: `web/tests/live-pages.test.tsx`
- Test: `web/tests/e2e/live-core-flow.spec.ts`

**Interfaces:**
- Produces: all feature pages backed by authenticated API data, owner labels, invite controls, and Lark binding controls.
- Consumes: Task 5 live APIs and Task 2 identity APIs.

- [ ] **Step 1: Write failing live-page tests**

```tsx
it("shows separate owner labels for family recipes", async () => {
  server.recipes([aliceRecipe, bobRecipe]);
  render(<RecipesPage />);
  expect(await screen.findByText("Alice")).toBeVisible();
  expect(screen.getByText("Bob")).toBeVisible();
  expect(screen.getAllByRole("article")).toHaveLength(2);
});

it("creates a family invite and Lark link code from settings", async () => {
  render(<SettingsPage />);
  await user.click(await screen.findByRole("button", { name: "Create family invite" }));
  expect(await screen.findByText(server.inviteCode)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Link Lark" }));
  expect(await screen.findByText(server.larkCode)).toBeVisible();
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pnpm --dir web test -- live-pages.test.tsx`

Expected: FAIL because pages still read locale fixture arrays.

- [ ] **Step 3: Implement live pages and remove static record arrays**

```ts
export function useFeatureData<T>(path: string) {
  const [state, setState] = useState<LoadState<T>>({ status: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    api<T>(path, { signal: controller.signal })
      .then((data) => setState({ status: "ready", data }))
      .catch((error) => setState({ status: "error", error }));
    return () => controller.abort();
  }, [path]);
  return state;
}
```

Render loading, empty, error, and ready states. Owner attribution is visible on every shared record. Remove `items` and `metric` fixture content from locale JSON while keeping translated labels and empty-state copy.

- [ ] **Step 4: Run Web tests and Playwright flow GREEN**

Run: `pnpm --dir web test && pnpm --dir web typecheck && pnpm --dir web lint && pnpm --dir web exec playwright test tests/e2e/live-core-flow.spec.ts`

Expected: all pass against the live local API; no page depends on static record fixtures.

- [ ] **Step 5: Commit the live-page slice**

```bash
git add web/src web/tests
git commit -m "feat: replace Web fixtures with live family data"
```

---

### Task 11: End-to-end Verification and Local Test Runbook

**Files:**
- Create: `tests/e2e/test_unified_runtime.py`
- Create: `tests/live/test_openai_smoke.py`
- Create: `docs/runbooks/local-end-to-end.md`
- Modify: `Makefile`
- Modify: `README.md`

**Interfaces:**
- Produces: one reproducible full-flow test, opt-in live provider smoke test, and manual local/Lark verification instructions.
- Consumes: all prior tasks.

- [ ] **Step 1: Write the failing full-flow test**

```python
async def test_web_and_lark_share_runtime_but_keep_private_conversations(runtime) -> None:
    family = await runtime.create_family_with_two_accounts()
    web_run = await runtime.submit_web(family.alice, "Recommend dinner")
    lark_run = await runtime.submit_lark(family.alice_lark, "Recommend dinner")
    assert web_run.response.model == lark_run.response.model
    assert web_run.response.structure == ("thinking", "plan", "act", "answer")
    assert web_run.conversation_id != lark_run.conversation_id
    assert all(action.executed_at is None for action in web_run.actions)
```

- [ ] **Step 2: Run the full flow and verify RED**

Run: `.venv/bin/python -m pytest tests/e2e/test_unified_runtime.py -v`

Expected: FAIL until all runtime fixtures and delivery adapters are integrated.

- [ ] **Step 3: Complete runtime fixtures, opt-in smoke test, and runbook**

The live test is marked `live` and skipped unless `RUN_LIVE_AI_TESTS=1`. It sends one harmless question, asserts a non-empty structured response, and never prints request headers, API keys, Lark secrets, raw provider responses, or private reasoning.

The runbook must document exact commands for Docker services, migrations, API, worker, Web, development login, family invitation, Lark linking, chat, suggested-action clicks, database inspection, Lark webhook/tunnel configuration, and shutdown.

- [ ] **Step 4: Run the complete verification matrix**

Run:

```bash
make backend-verify
make web-verify
RECIPE_AGENT_DATABASE_URL=postgresql+asyncpg://recipe:local-recipe-password@localhost:55432/recipe_local .venv/bin/alembic upgrade head
.venv/bin/python -m pytest tests/e2e/test_unified_runtime.py -v
RUN_LIVE_AI_TESTS=1 .venv/bin/python -m pytest tests/live/test_openai_smoke.py -v
```

Expected: format, lint, type, migration, unit, integration, API, security, Web, browser, unified-runtime, and live model checks all pass. Lark live verification is performed manually from the runbook because it requires an externally delivered event.

- [ ] **Step 5: Commit the verification slice**

```bash
git add tests/e2e/test_unified_runtime.py tests/live/test_openai_smoke.py docs/runbooks/local-end-to-end.md Makefile README.md
git commit -m "test: verify unified Web and Lark agent runtime"
```

---

## Plan Self-Review Matrix

| Design requirement | Tasks |
|---|---|
| One account per user, one family with multiple users | 1, 2 |
| Data ownership without merging | 1, 5, 10 |
| Web/Lark linking and family invitations | 2, 7, 10 |
| Shared `ConversationHub` | 3, 7, 8 |
| Durable PostgreSQL run and Redis/Celery execution | 3, 8 |
| LiteLLM GPT-5.1 high reasoning with fallback | 4, 8 |
| Five-step bounded read-only ReAct | 4, 5 |
| Thinking/Plan/Act/Answer without private reasoning | 4, 7, 9 |
| Explicit-click mutations only | 6, 7, 9 |
| Live Web pages | 5, 9, 10 |
| Recovery, idempotency, and isolation | 1, 3, 6, 7, 11 |
| Local and live verification | 8, 11 |

All approved design requirements map to at least one independently testable task. Shared interfaces are introduced before their consumers, and no task relies on an undefined later type except the Task 4 `ReadOnlyToolRegistry`, which is consumed through a protocol and receives its concrete implementation in Task 5.
