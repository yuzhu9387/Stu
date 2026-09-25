import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LocalizedApp } from "@/components/localized-app";

// The shell mounts ChatHome, which probes the session on first render. Left
// unmocked that probe reaches a real API on localhost and a 401 swaps the page
// for the login form mid-assertion, so this test only passed when nothing was
// listening. It is about interface copy, so hold the probe open instead.
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: vi.fn(() => new Promise(() => {})) };
});

describe("shell localization", () => {
  it("keeps all interface copy in the selected locale", async () => {
    const user = userEvent.setup();
    render(<LocalizedApp initialLocale="zh-CN" />);

    expect(screen.getByText("家的味道，都在这里")).toBeVisible();
    expect(screen.getByRole("navigation", { name: "主要导航" })).toHaveTextContent("计划");
    expect(screen.getByText("仅 Web")).toBeVisible();
    expect(screen.getByText("网址 · 图片 · 表格")).toBeVisible();
    expect(screen.queryByText("Recipes that feel like home")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "English" }));

    await waitFor(() => {
      expect(screen.getByText("Recipes that feel like home")).toBeVisible();
      expect(screen.getByRole("navigation", { name: "Primary navigation" })).toHaveTextContent("Plan");
      expect(screen.getByText("Web only")).toBeVisible();
      expect(screen.getByText("URL · image · spreadsheet")).toBeVisible();
      expect(screen.queryByText("家的味道，都在这里")).not.toBeInTheDocument();
    });
  });
});
