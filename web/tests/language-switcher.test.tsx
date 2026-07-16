import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { LocalizedApp } from "@/components/localized-app";

describe("language switcher", () => {
  it("switches the complete shell to English", async () => {
    const user = userEvent.setup();
    render(<LocalizedApp initialLocale="zh-CN" />);

    expect(screen.getByRole("navigation")).toHaveTextContent("菜谱库");
    await user.click(screen.getByRole("button", { name: "English" }));

    expect(screen.getByRole("navigation")).toHaveTextContent("Recipes");
    expect(screen.queryByText("菜谱库")).not.toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en-US");
  });
});
