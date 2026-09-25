# Design QA

final result: passed

## Evidence

- Source visual truth:
  - `/var/folders/4h/xnlm6xs90sv6dkpd_j5xlbq00000gn/T/codex-clipboard-d528e983-e344-4e66-9b25-1032ed311ed6.png` (recipe list, 559 × 779)
  - `/var/folders/4h/xnlm6xs90sv6dkpd_j5xlbq00000gn/T/codex-clipboard-09113c92-9057-4b4a-a427-0cecceb18079.png` (recipe detail, 353 × 790)
  - `/var/folders/4h/xnlm6xs90sv6dkpd_j5xlbq00000gn/T/codex-clipboard-14f33dd0-d653-4add-9c28-1ac201c20db5.png` (plan, 655 × 851)
  - `/var/folders/4h/xnlm6xs90sv6dkpd_j5xlbq00000gn/T/codex-clipboard-5f023580-9c53-4f13-bef7-f66ae7c84ae4.png` (plan generator, 671 × 844)
  - `/var/folders/4h/xnlm6xs90sv6dkpd_j5xlbq00000gn/T/codex-clipboard-b93b4e7c-03b9-42ee-9a97-af087f53cb5e.png` (todo, 643 × 852)
- Browser-rendered implementation captures:
  - `.recipe-list-desktop-final.png`
  - `.recipe-detail-final.png`
  - `.plan-desktop-final.png`
  - `.plan-generator-final.png`
  - `.todo-desktop-final.png`
  - `.recipe-list-mobile-final.png`
- Comparison composites:
  - `.design-qa/recipe-list-comparison.png`
  - `.design-qa/recipe-detail-comparison.png`
  - `.design-qa/plan-comparison.png`
  - `.design-qa/plan-generator-comparison.png`
  - `.design-qa/todo-comparison.png`
- Desktop viewport: 1280 × 720 CSS pixels at device scale factor 2; implementation screenshots are 1280 × 720 pixels as returned by the in-app browser.
- Mobile viewport: 390 × 844 CSS pixels; implementation screenshot is 390 × 844 pixels.
- Density normalization: every side-by-side composite normalizes both source and implementation to 720 pixels high before comparison. Source aspect ratios were retained.
- State: authenticated Chinese UI with owned recipe, manual plan, grocery item, and todo data. The AI generator setup form is shown before generation. English mode was also inspected separately.

## Findings

- No actionable P0, P1, or P2 differences remain.
- Fonts and typography: the implementation preserves the mockups' editorial recipe emphasis with a high-contrast serif display face, while interface controls use a compact sans serif. Chinese fallback, optical weight, wrapping, and hierarchy remain readable at desktop and mobile widths.
- Spacing and layout rhythm: the desktop sidebar is an intentional responsive expansion of the mockups' bottom navigation. Mobile returns to a persistent three-item bottom navigation. Card spacing, large radii, two-column todo layout, and plan rows retain the source hierarchy without overflow.
- Colors and visual tokens: warm cream, sage, clay, and soft gold replace the wireframe blue/lilac placeholders consistently. Contrast remains clear for text, selected states, destructive actions, and focus treatments.
- Image quality and asset fidelity: the recipe detail uses a dedicated generated food photograph with correct cover crop and a restrained dark overlay. Phosphor icons replace all wireframe glyphs; no emoji, CSS-drawn icons, placeholder image blocks, or handcrafted SVGs are used.
- Copy and content: all interface copy switches as a single Chinese or English language system. Meal labels, preferences, navigation, forms, actions, loading states, and empty states are localized. User-authored recipe and todo content intentionally remains unchanged.
- Interaction and accessibility: primary controls expose accessible names. Create, read, update, delete, completion toggle, filtering, language switching, AI generation, and assistant-driven database mutation were exercised in the browser.

## Comparison History

1. Initial recipe-detail capture showed a blank hero because the production web image did not copy `public/`. Fixed `infra/Dockerfile.web`, rebuilt the service, and recaptured `.recipe-detail-final.png`; the final comparison shows the complete food photograph.
2. Initial DOM inspection found icon-only edit/delete/add controls without accessible names and raw English meal labels in Chinese mode. Added localized labels and accessible names across recipe, plan, todo, and generator views. Post-fix DOM snapshots expose names such as `编辑菜谱`, `删除计划`, `添加待办`, and localized `早餐/午餐/晚餐` labels.
3. Initial ingredient quantities displayed database precision such as `4.000000`. Added locale-aware bounded number formatting; the final detail evidence shows `4 pieces`, `3 tbsp`, and equivalent concise values.

## Full-view Comparison

All five source/implementation composites were inspected at normalized height. The source information architecture is preserved: recipe filtering and cards, photo-led detail with ingredients/method, day-and-meal planning, guided generation inputs, and parallel grocery/todo columns. Desktop adaptations add whitespace and sidebar navigation; the 390-pixel capture verifies the requested bottom-navigation behavior and stacked recipe layout.

## Focused Regions

- Recipe hero and stat strip were inspected at full desktop size because imagery, overlay contrast, and crop were critical.
- Recipe-card controls were inspected at the 390-pixel mobile breakpoint because hover is unavailable there; edit/delete actions remain visible.
- AI generator controls and todo card actions were inspected through DOM snapshots to confirm localized copy and accessible names.

## Primary Interactions Tested

- Created a recipe and opened its detail page.
- Created a manual plan and added a meal.
- Generated and persisted a seven-day AI plan using live LiteLLM.
- Created a grocery item and toggled todo data.
- Asked the shared assistant to create a private todo without confirmation, then verified the new database row on the todo page.
- Switched the full interface between Chinese and English.
- Checked browser console errors: none.

## Follow-up Polish

- P3: additional user-provided recipe photographs would make list cards more visually distinctive.
- P3: a future iteration could add drag-to-reorder for meals and todos.

## Implementation Checklist

- [x] Five requested views implemented.
- [x] Responsive desktop and mobile layouts verified.
- [x] Full CRUD paths connected to the API and PostgreSQL.
- [x] Shared Web/Lark agent tool layer connected to account-scoped mutations.
- [x] Chinese/English whole-interface switching verified.
- [x] Final browser capture and console check completed.
