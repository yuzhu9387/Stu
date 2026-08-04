# Family Recipe Agent Product Requirements

## Document Purpose

This document translates the approved product design into a buildable full-MVP product contract. It covers Lark international and the Web UI. Code, identifiers, comments, and technical documentation use English. User-visible content supports Simplified Chinese and English, with one active language per screen or message.

## Product Promise

Users can send recipe content, ask what to cook, plan a week, record what happened, and share a safe result without manually organizing a database. The agent visibly understands, plans, acts, checks, and continues the conversation.

## Personas

### Primary: Parent and Household Cooking Lead

Collects recipes from Xiaohongshu, screenshots, chat, and spreadsheets. Needs age-aware decisions, child and adult feedback, quick weekly planning, and less repeated work.

### Secondary: General Household Cook

Needs ingredient-based discovery, quick-meal filters, lunchbox suitability, and a reliable personal recipe library.

### Tertiary: Share Recipient

Receives a privacy-safe recipe or collection. Can read it without seeing private household context.

## Core Jobs

1. Save a recipe without filling a form.
2. Find three suitable things to cook now.
3. Build and adjust a weekly meal plan.
4. Generate a consolidated shopping list.
5. Record household feedback and improve the recipe version.
6. Share a recipe or collection without leaking private data.

## Product Principles

- Chat first; management screens support review rather than replace conversation.
- Save raw input before parsing.
- Infer when safe and label uncertainty.
- Ask only for critical missing information.
- Prefer household recipes and household versions.
- Perform actions and report verified outcomes.
- Keep one active display language.
- Protect child and household privacy by default.

## Functional Requirements

### Identity and Localization

- **ID-01:** A user can request an email magic link and establish a secure Web session.
- **ID-02:** An authenticated Web user can generate a single-use Lark linking code.
- **ID-03:** A valid linking code connects one Lark identity to the user's household.
- **ID-04:** Every household-owned request enforces household authorization.
- **LOC-01:** The user can switch the complete Web UI between Simplified Chinese and English from the upper-right control.
- **LOC-02:** The locale preference persists to the account and controls later Lark responses.
- **LOC-03:** A screen, message, or card never mixes localized UI copy.

### Agent Conversation

- **AGENT-01:** An actionable request creates an agent run with Understand, Plan, Act, Check, and Continue stages.
- **AGENT-02:** The user sees a concise understanding status and action plan before or during non-trivial execution.
- **AGENT-03:** Long actions publish progress receipts for completed domain operations.
- **AGENT-04:** The agent never claims a mutation succeeded without a successful tool result.
- **AGENT-05:** Private model reasoning, secrets, provider payloads, and policy text are never displayed.
- **AGENT-06:** The final result states what changed and proposes the most relevant next action.

### Lark Channel

- **LARK-01:** The system verifies Lark callback tokens, encryption, and signatures.
- **LARK-02:** The callback endpoint acknowledges within three seconds.
- **LARK-03:** Duplicate `event_id` values do not create duplicate actions.
- **LARK-04:** Text, image, file, and interactive-card events normalize into channel-independent commands.
- **LARK-05:** Long-running work sends a localized progress card and a final follow-up card.
- **LARK-06:** Lark API failures retry within bounded policies and preserve the agent-run state.

### Recipe Import

- **SAVE-01:** Xiaohongshu and generic URLs persist before parsing.
- **SAVE-02:** Text, images, URLs, and Excel files produce validated recipe candidates.
- **SAVE-03:** Every extracted field can carry confidence and review status.
- **SAVE-04:** Exact source duplicates merge without creating a duplicate recipe.
- **SAVE-05:** Similar recipe candidates produce a merge decision or an additional source.
- **SAVE-06:** One input can create multiple recipe candidates.
- **SAVE-07:** Parsing failure leaves a `needs_review` raw input and offers screenshot or text fallback.
- **SAVE-08:** Originals and derived media remain private and retain source provenance.

### Recipe Library

- **RECIPE-01:** A user can list, search, filter, and open household recipes.
- **RECIPE-02:** Recipe detail shows ingredients, steps, times, age suitability, tags, sources, confidence, and the active household version.
- **RECIPE-03:** A user can correct supported fields through chat or the Web.
- **RECIPE-04:** Original and household versions remain recoverable.

### Recommendations

- **REC-01:** A recommendation request returns exactly three ordered choices.
- **REC-02:** Each choice explains ingredient match, missing ingredients, time, age fit, and relevant household history.
- **REC-03:** Explicit age, allergy, and dietary restrictions are hard filters.
- **REC-04:** Ranking considers ingredients, meal type, age, ratings, time, scenario tags, diversity, difficulty, recent repetition, and negative feedback.
- **REC-05:** Household recipes rank before generated suggestions.
- **REC-06:** If fewer than three eligible household recipes exist, generated suggestions fill the remaining positions and are clearly labeled.
- **REC-07:** Generated suggestions are not saved until the user chooses to save or schedule them.

### Weekly Planning and Shopping

- **PLAN-01:** A user can generate a dated weekly plan for selected meal types and constraints.
- **PLAN-02:** The plan limits repetition and explains every selected recipe.
- **PLAN-03:** A user can replace one plan item without regenerating accepted items.
- **PLAN-04:** Confirmed plan mutations persist before success is reported.
- **SHOP-01:** The system aggregates normalized ingredients from plan items.
- **SHOP-02:** Compatible quantities combine; incompatible raw units remain separate.
- **SHOP-03:** A user can check, uncheck, add, edit, and remove shopping-list items.

### Feedback, Ratings, and Versions

- **FB-01:** Natural-language cooking feedback creates an immutable feedback event.
- **FB-02:** Feedback can update time, step, quantity, tag, rating, preference, or suppression state.
- **FB-03:** Structural recipe changes create a new household recipe version.
- **FB-04:** Child and adult ratings support scores from one to five and private comments.
- **FB-05:** Ambiguous recipe references return at most three candidates for selection.
- **FB-06:** Negative feedback affects future ranking without deleting the recipe.

### Sharing

- **SHARE-01:** A user can create a share for one recipe or a collection.
- **SHARE-02:** A share is an immutable localized snapshot with an opaque token.
- **SHARE-03:** Real member names, private photos, comments, exact child ratings, contact details, and internal IDs are excluded.
- **SHARE-04:** The owner can revoke a share or set an expiry.
- **SHARE-05:** A valid public token renders a read-only share page without requiring login.

## Web Information Architecture

- `/chat`: default conversation route and upload entry.
- `/recipes`: recipe library with search and filters.
- `/recipes/[id]`: recipe detail, sources, confidence, and version history.
- `/plan`: weekly plan and replacement controls.
- `/shopping`: current shopping list.
- `/imports`: import status and review queue.
- `/shares`: share list, expiry, and revocation.
- `/settings`: account, language, and Lark linking.
- `/s/[token]`: privacy-safe public snapshot.

## Analytics Events

The MVP records:

- `account_created`
- `lark_identity_linked`
- `raw_input_received`
- `recipe_import_completed`
- `recipe_import_needs_review`
- `recommendation_requested`
- `recommendation_selected`
- `meal_plan_created`
- `meal_plan_item_replaced`
- `shopping_list_created`
- `feedback_recorded`
- `recipe_version_created`
- `share_created`
- `share_opened`
- `share_revoked`
- `ai_operation_completed`

Analytics payloads use internal opaque IDs and exclude message bodies and private comments.

## Acceptance Metrics

- Representative import usability rate at or above 80%.
- First save completed in under 60 seconds for the median new user.
- Exactly three recommendation cards for every successful recommendation request.
- Recommendation acceptance above 25% in beta.
- Day-seven retention above 30% for activated households.
- Zero cross-household data access in the security suite.
- Zero excluded private fields in generated share fixtures.

## Release Scope

The full MVP includes every requirement above. Social feeds, automatic grocery ordering, video transcription, voice mode, nutrition diagnosis, refrigerator inventory, native mobile applications, household invitations, and receiving-account share import remain outside the first release.
