# Verification — 18 September 2026

- `npm --prefix web run typecheck`: passed.
- `npm --prefix web run lint`: passed.
- `npm --prefix web test`: 67 tests passed across 20 files.
- `.venv/bin/python scripts/run-kitchen-e2e.py`: 12 browser stories passed, desktop and iPhone Chromium, using a newly migrated isolated PostgreSQL database. Covers login, Chinese inventory persistence, plan confirmation, prep production, meal completion/skip/like/undo, missing-key errors, authenticated MCP, knowledge import/versioning/deletion, all-page viewport containment and recipe drawer navigation.
- `docker compose --env-file .env -f infra/compose.yaml build web`: production Next.js build passed, including TypeScript and 19 prerendered pages.
- Final image: `sha256:c4bec3861344602de6884c84cea8d2b149e2fbcf35c9ed18e3111216ff443ed8`.
- Activated with `up -d --no-deps web`; existing API, workers and database volumes preserved.
- Runtime: `/calendar`, `/plan`, `/prep`, `/fridge`, `/recipes`, `/guidance`, `/knowledge` all HTTP 200 at port 13107; API `/health/ready` HTTP 200 at port 8000.
- Deployed logo and all three Figma-exported expression SVGs are byte-for-byte equal to the local original assets.
- Manual browser visual review: Calendar, Plan, Fridge, Recipes, Settings and Prep, compared with six Figma PDF exports. Real records and active/draft/empty states determine rendered content. There is no claim of pixel identity across different data, viewport sizes, or OS emoji renderers.

No paid AI generation was run for this presentation change. Browser tests exercise the missing-key case deliberately; prior live AI verification is documented separately.
