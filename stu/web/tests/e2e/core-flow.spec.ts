import { expect, test } from "@playwright/test";

async function mockLiveApi(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/auth/session") {
      return route.fulfill({ json: { account_id: "1", household_id: "2", email: "cook@example.com", role: "owner" } });
    }
    if (path === "/api/v1/settings") {
      return route.fulfill({ json: { preferences: [], members: [{ owner_account_id: "1", owner_display_name: "cook", email: "cook@example.com", role: "owner", is_owned_by_current_account: true }], lark_binding: { is_linked: false } } });
    }
    if (path === "/api/v1/recipes") {
      return route.fulfill({ json: { recipes: [
        { id: "r1", owner_display_name: "cook", is_owned_by_current_account: true, name: "Tomato soup", visibility: "family", created_at: "2026-07-16T00:00:00Z" },
        { id: "r2", owner_display_name: "bob", is_owned_by_current_account: false, name: "Noodles", visibility: "family", created_at: "2026-07-15T00:00:00Z" },
      ] } });
    }
    return route.fulfill({ status: 404, json: { detail: "Not found" } });
  });
}

test("switches language and opens the recipe library", async ({ page }) => {
  await mockLiveApi(page);
  await page.goto("/chat");

  await expect(page.getByRole("heading", { name: "今天想做点什么？" })).toBeVisible();
  await page.getByRole("button", { name: "English" }).click();
  await expect(page.getByRole("heading", { name: "What should we cook?" })).toBeVisible();

  await page.getByRole("link", { name: "Recipes" }).click();
  await expect(page).toHaveURL(/\/recipes$/);
  await expect(page.getByRole("heading", { name: "Household recipes" })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(2);
  await expect(page.getByText("Owner: bob", { exact: false })).toBeVisible();
});

test("keeps the mobile page within the viewport", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "Mobile-only layout assertion");
  await mockLiveApi(page);
  await page.goto("/recipes");

  const sizes = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.body.scrollWidth,
  }));

  expect(sizes.scrollWidth).toBeLessThanOrEqual(sizes.clientWidth);
});
