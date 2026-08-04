import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FeatureScreen } from "@/components/feature-screen";
import { LocaleProvider } from "@/i18n/locale-context";

describe("feature screen", () => {
  it("renders the localized page and three useful records", () => {
    render(
      <LocaleProvider initialLocale="zh-CN">
        <FeatureScreen page="recipes" />
      </LocaleProvider>,
    );

    expect(screen.getByRole("heading", { name: "家庭菜谱库" })).toBeVisible();
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(screen.getByText("番茄炒蛋")).toBeVisible();
  });
});
