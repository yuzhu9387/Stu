import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { LocalizedApp } from "@/components/localized-app";

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
