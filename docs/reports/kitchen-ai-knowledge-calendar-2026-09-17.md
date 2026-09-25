# Kitchen AI, Knowledge, calendar and palette acceptance — 2026-09-17

The application has a real authenticated API, PostgreSQL persistence and execution
workers. `/demo` remains an explicitly simulated workspace. Browser acceptance
below uses a separate temporary PostgreSQL database and real HTTP; visual
comparison screenshots use the demo fixture and do not prove persistence.

**Full-week live AI acceptance passed:** an actual provider generated and persisted
a 21-meal draft, six complete recipes and four prep tasks, then returned a scoped
chat proposal. The isolated acceptance test also verified enabled-only document
snapshots, timing, rotation, persisted chat and an idempotent generation retry.
The entire paid-provider test took 240.65 seconds; this demonstrates a working
flow, not a fast-generation guarantee.

This report supersedes the counts and missing-key statements in the earlier
[core implementation report](kitchen-live-completion-2026-09-17.md) and
[initial workspace report](kitchen-verification-2026-09-17.md). Those documents
describe earlier checkpoints, not the current verification state.

## Implemented behavior

| Area | Behavior and evidence |
| --- | --- |
| Nutrition Knowledge | Dedicated `/knowledge` page with household-owned documents, Chinese content, title/category/content, optional HTTP(S) source URL, enabled state, server-assigned version and update time. Search, category filtering, viewing, add/edit/delete and enable/disable are implemented. Real desktop/mobile browser stories verify persistence, reload, versions and deletion. |
| Document import | `.txt` and `.md` files open an editable preview. Save is explicit; cancelling does not create a document. Unsupported PDF input is rejected. No PDF parsing, source-URL crawling or automatic fact verification is claimed. |
| Planning evidence | Enabled documents enter the AI generation and chat context; disabled documents are excluded. Plans save the exact document content/version in `knowledgeSnapshot`. Later document changes or deletion do not rewrite the saved evidence. Existing guidance remains a separate feature with its own snapshot. Deterministic provider and repository tests cover these boundaries. |
| Concurrent edits | Stale document versions cannot overwrite newer edits. Knowledge changes use the existing household revision/idempotency checks. The enable toggle changes immediately while saving, disables duplicate submissions, and restores its previous state if saving fails. |
| MCP | `knowledge.save` and `knowledge.delete` are advertised alongside existing commands. They share authenticated household scope, validation and persistence with the UI. MCP does not expose unrestricted SQL or an independent OAuth token. |
| Empty recipe library | AI can create complete recipe records together with a weekly draft. Deterministic tests verify atomic save and idempotent retry; the real-provider acceptance produced and persisted six complete recipes and all 21 meals from an initially empty library. |
| Compact bootstrap generation | For an empty library, the provider returns recipes, reusable meal templates and seven day assignments. The server expands these into the normal 21-meal draft and weekend prep tasks, preserving recipe steps/yields, exact fractional demand, batch time accounting and explicit stock-input allocations. The generated result passes the existing timing, stock and rotation validation before saving. The separate generation reasoning setting defaults to `medium`; its request timeout remains 240 seconds. |
| Dish rotation | Default `recipeRepeatGapDays=1` requires one intervening date: Monday’s dish may return Wednesday, but not Tuesday. The setting accepts 1–7. Recipe IDs and normalized bilingual names are checked; plain staple exemptions and skipped meals are explicit. Validation covers generation, manual edits, confirmation and undo, including the preceding week boundary. |
| Calendar | Seven day columns with compact breakfast/lunch/dinner cards, Chinese titles, component/source/time metadata, category colors and a selected border. Card open, direct Replace, Reference in Chat, completion, skip and like retain their existing behaviors. Mobile scroll remains within the calendar. |
| Route and mobile fixes | Knowledge renders exactly one kitchen navigation instead of the legacy outer shell. The legacy Settings route retains its shell. Five primary destinations plus Settings fit the mobile bottom bar. Page feedback occupies a normal layout row so document actions remain accessible. |
| Palette | The latest approved reference is applied through shared tokens: cream `#FFF8EF`, primary `#C74732`, olive `#64734B`, dark brown `#35251F`, white surfaces and derived category tints. Calendar, drawer, Plan, Prep, Fridge, Recipes, Knowledge and Guidance use the same palette. |

## Verified checks

| Check | Observed result |
| --- | --- |
| Full backend regression, real PostgreSQL configured | **386 passed, 2 skipped in 23.82s**, exit 0, no warnings. Final run includes all 14 compact-generation regressions, including batch instructions, stock inputs, fractional portions, omitted initial likes and baked-protein classification. |
| Backend lint and formatting | Ruff check passed for `src tests migrations scripts`; all **206 files** passed the formatting check. |
| Strict backend types | Mypy passed all **119 source files**. |
| Resource cleanup | `ResourceWarning`, `PytestUnraisableExceptionWarning` and `PytestUnhandledThreadExceptionWarning` were promoted to errors in that full run. |
| Live-test gating | Both skips were deliberate: `RUN_LIVE_AI_TESTS=0` skipped the real-provider smoke and complete-generation tests. PostgreSQL tests were enabled, not skipped. |
| Full frontend suite | **64 passed in 19 files** in the fresh final palette rerun. TypeScript and ESLint passed. |
| Real-service Playwright | **10 passed in 12.9s**, five stories each on desktop Chromium and a mobile Chromium viewport, after the Knowledge, navigation and feedback-layout fixes. |
| Actual provider smoke | **1 passed in 12.04s**: real agent response plus synthetic Chinese recipe extraction. This verifies the configured key/provider path without asserting full-week quality. |
| Deployed service check | Updated local images at `http://localhost:13107`: authenticated QA login succeeded; Knowledge rendered exactly one navigation; workspace GET returned 200; no browser page errors. The four computed palette tokens matched the approved hex values. |
| Deployed actual AI extraction | `/api/v1/kitchen/extract` returned 200 in **4.265s** with 燕麦粥, 2 servings, 5 active minutes, 8 elapsed minutes, 2 ingredients and 3 steps. This separate synthetic-input check does not save a recipe or prove weekly generation. |
| Full-week actual provider acceptance | **1 passed in 240.65s**: 21 persisted draft meals, 6 complete recipes, 4 prep tasks, enabled-only Knowledge snapshot, daily timing/rotation validation, persisted scoped chat and idempotent retry. Uses an isolated synthetic household and SQLite test repository, separate from the PostgreSQL browser suite. |
| Visual comparison | Desktop and mobile palette review passed. Captured browser page errors were empty during the documented review. Details and limitations are in [design QA](../../design-qa.md). |

The backend run used the unique temporary database
`stu_final_regression_8bc153bd2623444297e488b66e96b98b` on the local PostgreSQL test
server. The harness created it before the suite and dropped only that generated
database in `finally`; application data was not touched. The process log is
`/tmp/stu-final-backend-regression-20260917.log`.

The separate deployed browser check used a specific QA email. Its empty test
account, login links and session were cleaned up afterward; existing user
households were retained. Reading an empty workspace did not create saved
workspace records.

The real browser stories cover login and Chinese Fridge edits/reload; plan and
Prep execution, meal completion/likes/undo; explicit missing-key behavior while
preserving weekly preferences; authenticated MCP writes and unauthorized
rejection; and Knowledge import, versioned edit, enable/disable, search, delete and
reload. They deliberately do not call a paid AI provider. A passing UI story is
not presented as proof of actual model generation.

The separate successful live AI test made three real requests: compact generation
in 184.6 seconds, one correction in 52.2 seconds and scoped chat in 3.6 seconds.
Its saved draft has daily active estimates `[23, 30, 23, 30, 23, 30, 23]` minutes;
weekend prep totals 145 active minutes and 225 ordinary elapsed minutes. Only
`acceptance-reference` version 1 appears in the Knowledge snapshot; the disabled
document is absent. Two chat entries and a scoped proposal are persisted without
implicitly applying the proposed meal change. Retrying the same generation
operation did not cause another provider call. Raw evidence is retained locally
in `/tmp/stu-live-ai-acceptance.json` and `/tmp/stu-live-ai-compact.log`.

An earlier full-schema attempt timed out after 240 seconds. Compact generation
reduced the repeated output. The successful compact run requested one correction
because its already-running process still required `recipe.liked`; final code now
defaults new recipes to `false`, and the original actual response passes the
final compiler and validator without that correction. The final offline suite
verifies this compatibility fix. Baked protein also retains its Protein category
and ordinary timing budget instead of receiving the passive-baking exemption.

For reproducibility, the backend invocation was:

```sh
RUN_LIVE_AI_TESTS=0 \
RECIPE_AGENT_TEST_DATABASE_URL=postgresql+asyncpg://recipe:recipe@localhost:55433/UNIQUE_TEMP_TEST_DB \
PYTHONPATH=src .venv/bin/python -m pytest -q \
  -W error::ResourceWarning \
  -W error::pytest.PytestUnraisableExceptionWarning \
  -W error::pytest.PytestUnhandledThreadExceptionWarning
```

Create a unique disposable test database first and remove it afterward; do not
substitute the application database. The maintained browser harness is
`scripts/run-kitchen-e2e.py`; it handles its own temporary database and services.

## Visual evidence

The [selected palette](palette-selected-reference.png),
[desktop Calendar](palette-calendar.png), [meal drawer](palette-drawer.png),
[Plan](palette-plan.png), [Prep](palette-prep.png), [Fridge](palette-fridge.png),
[Recipes](palette-recipes.png), [Knowledge](palette-knowledge.png),
[Guidance](palette-guidance.png), [mobile Calendar](palette-calendar-mobile.png)
and [mobile Knowledge](palette-knowledge-mobile.png) capture the final palette
review. [Deployed login](palette-login-live.png) and
[deployed Knowledge](palette-knowledge-live.png) capture the authenticated service
checks. Earlier calendar geometry comparisons are retained in
[design QA](../../design-qa.md).

Measured token contrasts are white on primary 4.80:1, dark brown on cream 13.88:1,
muted brown on cream 5.05:1 and olive on pale olive 4.54:1. These measurements cover
the named token pairs; they are not a claim of a complete accessibility audit.

## Acceptance limits

The real provider key and tested weekly-generation/chat path work. This one
synthetic household run does not establish latency or reliability across every
household, recipe library or provider response. Provider timeouts and invalid
proposals still surface explicitly; the application does not substitute mock
menus or save an invalid partial draft. Manual planning, document management and
execution have independent passing tests.

Friday scheduling is covered by deterministic worker tests; an actual future
Friday paid-provider run has not been observed. Scheduling remains the approved
conservative one-cook active-then-wait model, with passive baking tails reported
separately. This report does not replace those estimates with measured kitchen
durations or claim that user-supplied nutritional material is medically verified.
