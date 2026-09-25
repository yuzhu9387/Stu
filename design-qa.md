# Calendar reference implementation QA

final result: passed

## Visual truth and evidence

- Source: `docs/reports/calendar-selected-reference.png`, the user's selected
  screenshot (1210 × 442 pixels).
- Desktop implementation: `docs/reports/calendar-reference-grid-final.png`,
  1194 × 432 pixels, captured from the 1862 × 960 CSS viewport at density 1.
  `calendar-reference-drawer-final.png` shows the complete page and drawer.
- State: Sep 21–27, 2026, confirmed plan, Wednesday dinner selected. The source
  crops away the drawer; the implementation was captured wide enough to retain
  all seven columns while its drawer remained open. Source canvas margins and
  the partial footer are excluded when comparing card sizes.
- Both source and final grid were opened together in the same image comparison
  tool response. They are approximately the same CSS/pixel width; no density
  rescaling was needed. A focused Wednesday dinner comparison is legible directly
  at this size: category, Chinese title, component subtitle, source/time line,
  coral border and action icons.
- Mobile: `calendar-mobile-final.png`, `calendar-mobile-drawer.png`, and
  `knowledge-mobile-final.png`, all 390 × 844 CSS pixels at density 1.
- The in-app browser was opened on the running implementation. Automated Chromium
  screenshots and interaction checks used the existing browser test setup. Visual
  fixtures are explicitly the demo household; real persistence is tested separately
  in the isolated PostgreSQL browser suite.

## Findings and comparison history

1. [P2, fixed] Initial cards were 124 px tall, leaving excessive blank space versus
   the source. Evidence: `calendar-reference-grid.png`. Cards are now 112 px, with
   tighter internal spacing and 11 px metadata. Final evidence:
   `calendar-reference-grid-final.png`. The remaining height beyond the source's
   roughly 95–108 px cards accommodates the requested completion/skip/like controls
   alongside replace/chat without covering titles or timing.
2. [P1, fixed] Adding Knowledge created a second mobile navigation row below the
   fixed bar. Evidence: `calendar-mobile.png` and `knowledge-mobile.png`. The grid
   now has five destinations plus Settings in one row. Final evidence:
   `calendar-mobile-final.png` and `knowledge-mobile-final.png`. All six targets
   have y=789, height=50 in an 844 px viewport; no document horizontal overflow.
3. [P1, fixed] The live Knowledge route initially retained the legacy outer shell.
   The pathname exclusion now selects only KitchenWorkspace. A regression test
   checks one navigation while preserving the legacy Settings route.

## Required fidelity surfaces

- **Typography:** Existing Inter/system sans with Chinese fallbacks retained;
  16 px date, 12 px dish heading and 11 px metadata. Two-line dish headings,
  component subtitle truncation and full drawer content remain readable. The
  source font is inferred from appearance, not asserted as an exact known face.
- **Layout:** Seven equal day columns, subtle vertical separators, compact stacked
  meal cards, rounded corners and left accents match the reference hierarchy.
  The week scrolls inside its own container on smaller screens; drawer actions
  remain visible on mobile. Slightly taller cards are the intentional control-row
  accommodation described above.
- **Colors:** Warm breakfast, pale sage lunch, pale peach dinner and coral selected
  border follow the reference. Existing ivory app background is retained.
- **Assets:** Phosphor Sun, Leaf and BowlFood supply standard category icons.
  No illustration/photo assets are present in this cropped reference. No invented
  bitmap or CSS artwork was required.
- **Content:** English controls and Chinese dish names render correctly. Household
  fixture names intentionally differ from the screenshot. Inventory labels reflect
  actual state (including Planned prep) instead of copying inaccurate From fridge
  labels from a static reference. Elapsed minutes are on cards; hands-on totals
  remain visible separately.

## Interaction checks

- Inline Replace opens the replacement drawer directly; normal card opens detail.
- Selected border and quick actions render; keyboard focus is visible.
- Mobile detail, close, scroll and Knowledge navigation work.
- Browser page-error collection returned an empty list during capture.
- Real-service E2E covers execution/undo/likes, knowledge import/edit/version/toggle/
  delete/reload and authenticated MCP independently of demo visuals.

No actionable P0/P1/P2 visual findings remain. Optional P3: the library bowl icon
contains food strokes whereas the reference uses a simpler outline bowl.

## Subsequent approved palette change

The user's later color reference overrides the earlier calendar's exact palette.
Source: `docs/reports/palette-selected-reference.png` (804 × 455). The requested
change is the app-wide color system, not the example's Chinese copy or layout.
Shared CSS tokens now use background #FFF8EF, primary #C74732, accent #64734B and
text #35251F, with white surfaces and derived meal/category tints.

The palette reference and `palette-calendar.png` / `palette-knowledge-mobile.png`
were opened in the same comparison input. Additional reviewed evidence:
`palette-drawer.png`, `palette-plan.png`, `palette-prep.png`, `palette-recipes.png`.
Desktop is 1458 × 920 at density 1; mobile is 390 × 844. Layout, typography,
meal hierarchy and imagery are intentionally unchanged. Primary controls, navigation
selection, forms, drawers and reference documents consistently use the new palette.

Text contrasts measured from tokens: white on primary 4.80:1; dark brown on cream
13.88:1; muted brown on cream 5.05:1; olive on pale olive 4.54:1.

Real mobile testing also found a persistent toast covering document actions.
Feedback now occupies a normal page row (drawer feedback retains its dedicated
row), allowing edit/delete without dismissing a blocking overlay. The desktop and
mobile real-service suite passed all 10 stories after the fix.

Palette result: passed. No new P0/P1/P2 color or responsive findings.

After deployment, the real service at `http://localhost:13107` was checked as
well. `palette-login-live.png` and `palette-knowledge-live.png` show the actual
login and authenticated Knowledge route. Computed root tokens matched all four
requested hex values exactly; the Knowledge route had one navigation shell and
no browser page errors. Its workspace API returned HTTP 200. The QA account was
separate from existing households, and no recipes or documents were saved there.
