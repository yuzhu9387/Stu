import { expect, test } from "@playwright/test";

test("switches language and opens the recipe library", async ({ page }) => {
  await page.goto("/chat");

  await expect(page.getByRole("heading", { name: "今天想做点什么？" })).toBeVisible();
  await page.getByRole("button", { name: "English" }).click();
  await expect(page.getByRole("heading", { name: "What should we cook?" })).toBeVisible();

  await page.getByRole("link", { name: "Recipes" }).click();
  await expect(page).toHaveURL(/\/recipes$/);
  await expect(page.getByRole("heading", { name: "Household recipes" })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(3);
});

test("keeps the mobile page within the viewport", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "Mobile-only layout assertion");
  await page.goto("/recipes");

  const sizes = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.body.scrollWidth,
  }));

  expect(sizes.scrollWidth).toBeLessThanOrEqual(sizes.clientWidth);
});
