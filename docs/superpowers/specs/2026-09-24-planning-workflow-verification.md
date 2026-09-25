# Planning workflow verification

Verified 2026-09-24.

| Check | Result |
| --- | --- |
| Frontend Vitest suite | 156 passed, 33 files |
| Backend unit suite | 220 passed |
| PostgreSQL kitchen integration | 50 passed in isolated temporary schemas |
| Authenticated Playwright desktop + iPhone stories | 14 passed with a disposable migrated database |
| TypeScript / ESLint | Passed |
| Ruff / kitchen mypy | Passed |
| Docker production build | API, web, worker, dispatcher and migration images built |

The added browser story exercises saved preference-stage recovery, header order,
confirmation to Shopping & prep, persistent purchase checks, focus restoration
after reload, ingredient details, responsive layout, View calendar, matching card
classes, version control, and confirming an edited plan back into Shopping.

Reviewed screenshots from both panel states on desktop and mobile. Also checked
the running local service's Calendar visually and found no browser console errors.
The existing user tab was refreshed; temporary demo inspection was closed.

Shopping is a live ingredient projection with a saved purchase checklist. It uses
known units/grams per portion; ambiguous stock and missing recipes are shown for
review. The Update fridge button opens the existing editor for actual purchased
amounts. Checking an item alone does not mutate stock.
