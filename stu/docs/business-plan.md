# Family Recipe Agent Business Plan

## Executive Summary

Family Recipe Agent turns scattered recipe content into a household memory and decision system. Users forward a Xiaohongshu link, upload a screenshot or spreadsheet, or describe a recipe in Lark or the Web. The product preserves the source, structures the recipe, learns household feedback, recommends three relevant dishes, builds weekly meal plans, creates shopping lists, and produces privacy-safe shares.

The initial wedge is parents and household cooking decision-makers who already collect recipes but struggle to retrieve, adapt, and use them. The product competes on workflow rather than content: low-friction chat intake, child-age context, household versions, and a bot that plans and performs actions instead of merely answering questions.

## Customer Problem

Recipe content is abundant, but household execution is fragmented:

- Recipes are split across social bookmarks, screenshots, chat history, spreadsheets, and memory.
- Saved recipes are difficult to retrieve at the moment of cooking.
- General recipe tools do not understand household-specific adjustments, child preferences, lunchbox needs, or recent repetition.
- Weekly planning and shopping require repeated manual aggregation.
- Sharing a source link does not communicate the household's tested version or privacy boundaries.

The economic cost is recurring decision time, unused saved content, duplicated shopping, and poor retention in traditional recipe organizers.

## Target Market

### Primary Segment

Parents and household cooking decision-makers with children aged one to eight who regularly collect recipes from Chinese social platforms, screenshots, chat, and spreadsheets.

### Secondary Segment

General household cooks who optimize for quick meals, lunchboxes, available ingredients, and repeatable weekly planning.

### Expansion Segment

Friends and family groups that exchange curated recipe collections and want an importable, privacy-safe format.

## Value Proposition

**Positioning:** A household recipe memory and action agent, not another recipe content application.

The product delivers four linked outcomes:

1. **Capture without organization work:** Forward or upload content and receive a usable recipe card.
2. **Decide with household context:** Receive exactly three recommendations based on ingredients, time, age, ratings, and history.
3. **Execute the week:** Convert recommendations into a meal plan and consolidated shopping list.
4. **Improve over time:** Turn real cooking feedback into a durable household recipe version and better future ranking.

## Competitive Strategy

Established recipe managers already provide recipe boxes, Web imports, meal plans, and shopping lists. New AI products increasingly parse social links and generate plans. Competing on a complete consumer application feature set would be expensive and undifferentiated.

The defensible strategy is:

- Lead with Lark and chat-driven intake instead of application-first organization.
- Build household feedback memory that compounds with every cooking session.
- Model child age, child/adult ratings, lunchbox use, cold serving, and household-specific difficulty.
- Preserve source provenance and private household versions separately.
- Make sharing a privacy projection rather than a raw database view.
- Keep channel adapters and model providers replaceable so distribution can expand without rebuilding the domain core.

## Business Model

### Free Tier

- One household.
- Up to 50 saved recipes.
- Text and link import.
- Limited monthly AI extraction and planning actions.
- Basic three-result recommendations.

### Household Plus

- Unlimited recipes within fair-use limits.
- Image and Excel imports.
- Weekly plans and shopping lists.
- Household versions, feedback history, and ratings.
- Private share links and collections.
- Higher monthly AI allowance.

### Future Family Tier

- Multiple household members.
- Shared editing and shopping collaboration.
- Advanced dietary and allergy controls.
- Family administration and additional storage.

Pricing validation should begin with willingness-to-pay interviews and a beta paywall experiment. The implementation must meter model usage and storage from the first release even if billing is not initially enabled.

## Go-to-Market

### Phase 1: Design Partners

Recruit 20 to 30 parents or household cooking decision-makers who already maintain recipe collections. Onboard their real Xiaohongshu links, screenshots, and spreadsheets. Observe first-save time, correction behavior, and the first weekly planning session.

### Phase 2: Closed Beta

Expand to 50 to 200 users through parent groups, cooking communities, and direct invitations. Focus acquisition messaging on forwarding recipes to Lark and remembering the household's own version.

### Phase 3: Sharing-Led Growth

Introduce age-, meal-, and scenario-specific collections that can be opened without exposing private household details. Measure share-open and save-to-household intent before building receiving-account import.

## Success Metrics

### North Star

Weekly successful household recipe uses: viewing steps, adding to a meal plan, creating a shopping list, recording cooking feedback, or sharing a recipe.

### Activation

- First recipe saved rate above 70%.
- Median time to first saved recipe below 60 seconds.
- Supported input to usable recipe-card rate above 80%.

### Engagement

- More than 10 saved recipes per activated beta household.
- Recommendation acceptance above 25%.
- Weekly plan creation and shopping-list completion.
- Feedback events per cooked recipe.

### Retention and Growth

- Day-seven retention above 30%.
- Week-four retention trend by activated cohort.
- Repeat-cooking rate.
- Share open rate and save intent.

## Unit Economics and Cost Controls

The major variable costs are model inference, image processing, object storage, and outbound messaging. Cost controls include:

- Per-operation LiteLLM model routing.
- Structured extraction with bounded repair attempts.
- Embedding deduplication by content hash.
- Image resizing and lifecycle policies.
- Request and household budgets.
- Cached explanations only when ranking inputs are identical.
- Usage events for every AI and storage operation.

The beta should track gross variable cost per activated household and per successful recipe use. Paid-tier pricing must preserve a healthy contribution margin under high image-import usage.

## Risks and Mitigations

### Platform Parsing Risk

Xiaohongshu access can be unstable. The product always saves the URL and supports screenshot or copied-text fallback. The adapter remains isolated from recipe persistence.

### Extraction Trust Risk

Incorrect ingredients or steps damage trust. The product stores field confidence, marks uncertain values, preserves the source, and supports one-sentence correction.

### Child Safety Risk

Age and allergy information can be consequential. The product applies explicit restrictions as hard filters, labels inferred age, and never provides medical claims.

### Competitive Risk

Competitors can reproduce generic AI parsing. Household feedback history, tested versions, and low-friction channel workflows create the compounding advantage.

### Privacy Risk

Household and child information is private by default. Shares are immutable privacy-filtered snapshots with revocation and expiry.

## Funding and Team Assumptions

The first full MVP is designed for a small product-engineering team:

- One product owner or founder.
- One backend/AI engineer.
- One full-stack engineer.
- Fractional product design and security review.

The modular-monolith architecture minimizes early operations work while allowing worker pools and high-load spokes to scale independently.

## Milestones

1. **Foundation:** Identity, localization, observability, containers, and agent contracts.
2. **Capture:** Lark/Web intake, raw preservation, extraction, and recipe library.
3. **Decision:** Exactly three recommendations, weekly planning, and shopping lists.
4. **Memory:** Feedback, ratings, and household versions.
5. **Growth:** Privacy-safe sharing and beta instrumentation.
6. **Beta Gate:** Full acceptance suite, security review, and design-partner onboarding.

## Decision Gate

Proceed to closed beta when representative imports achieve the usability target, the core workflows pass in both languages and both channels, household isolation is verified, and the measured variable cost supports a plausible paid tier.
