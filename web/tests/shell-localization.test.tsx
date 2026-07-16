import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { LocalizedApp } from "@/components/localized-app";

describe("shell localization", () => {
  it("keeps all interface copy in the selected locale", async () => {
    const user = userEvent.setup();
    render(<LocalizedApp initialLocale="zh-CN" />);

    expect(screen.getByText("余家")).toBeVisible();
    expect(screen.getByText("已记住 12 道菜谱")).toBeVisible();
    expect(screen.getByText("Lark 已连接")).toBeVisible();
    expect(screen.getByText("网址 · 图片 · 表格")).toBeVisible();
    expect(screen.queryByText("Yu household")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "English" }));

    expect(screen.getByText("Yu household")).toBeVisible();
    expect(screen.getByText("12 recipes remembered")).toBeVisible();
    expect(screen.getByText("Lark connected")).toBeVisible();
    expect(screen.getByText("URL · image · spreadsheet")).toBeVisible();
    expect(screen.queryByText("余家")).not.toBeInTheDocument();
  });
});
