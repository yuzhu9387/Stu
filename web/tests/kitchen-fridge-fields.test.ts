import { describe, expect, it } from "vitest";

import { freshness } from "@/features/kitchen/data";

const today = new Date("2026-09-20T09:00:00Z");

describe("fridge freshness, frame 110:5", () => {
  it("reports nothing when no expiry was recorded", () => {
    // An unknown expiry stays unknown; the card must not invent one.
    expect(freshness(undefined, today)).toBeNull();
  });

  it("counts the days left", () => {
    expect(freshness("2026-09-27", today)).toMatchObject({ days: 7, tone: "fresh" });
    expect(freshness("2026-09-22", today)).toMatchObject({ days: 2, tone: "soon" });
  });

  it("separates due today from already expired", () => {
    expect(freshness("2026-09-20", today)).toMatchObject({ days: 0, tone: "due" });
    const gone = freshness("2026-09-18", today);
    expect(gone).toMatchObject({ days: -2, tone: "expired" });
    expect(gone?.label).toContain("2");
  });
});
