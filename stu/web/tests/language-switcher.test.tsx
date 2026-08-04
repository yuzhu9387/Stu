import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { LocalizedApp } from "@/components/localized-app";

describe("language switcher", () => {
  it("switches the complete shell to English", async () => {
    const user = userEvent.setup();
    render(<LocalizedApp initialLocale="zh-CN" />);

    expect(screen.getByRole("navigation", { name: "主要导航" })).toHaveTextContent("菜谱");
    await user.click(screen.getByRole("button", { name: "English" }));

    await waitFor(() => {
      expect(screen.getByRole("navigation", { name: "Primary navigation" })).toHaveTextContent("Recipes");
      expect(screen.queryByText("菜谱")).not.toBeInTheDocument();
      expect(document.documentElement.lang).toBe("en-US");
    });
  });
});
