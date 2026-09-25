import { expect, test, type Page, type APIRequestContext } from "@playwright/test";
import type { KitchenState, Recipe, WeeklyPlan } from "../../src/features/kitchen/types";
import { randomUUID } from "node:crypto";

const apiBase = process.env.E2E_API_BASE_URL || "http://localhost:8002";
const week = "2026-09-21";

async function login(page: Page) {
  await page.goto("/calendar");
  await page.getByLabel("Email", { exact: true }).fill(`kitchen-${randomUUID()}@example.com`);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  // The shell heading is visible even before login; wait for authenticated data.
  await expect(page.getByRole("region", { name: "Weekly meal calendar" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Calendar", exact: true })).toBeVisible();
}
async function state(request: APIRequestContext): Promise<KitchenState> {
  const response = await request.get(`${apiBase}/api/v1/kitchen`);
  expect(response.ok(), `Kitchen read returned ${response.status()}`).toBeTruthy();
  return response.json();
}
async function command(request: APIRequestContext, type: string, payload: Record<string, unknown>) {
  const current = await state(request);
  const response = await request.post(`${apiBase}/api/v1/kitchen/commands`, {
    data: { type, payload, expectedRevision: current.revision, operationId: randomUUID() },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()).state as KitchenState;
}
async function seed(request: APIRequestContext) {
  const recipe: Recipe = { id: "chicken", name: "鸡肉丸", type: "Protein", mealTypes: ["lunch", "dinner"], tags: [], servings: 3, activeMinutes: 8, elapsedMinutes: 18, ingredients: [{ name: "鸡肉", quantity: 300, unit: "g" }], steps: ["Prepare chicken", "Cook through and portion"], liked: false, source: "Explicit E2E test fixture" };
  await command(request, "recipe.save", { recipe });
  const inventory = [
    { id: "meat", name: "鸡肉丸", type: "Protein", portions: 2, recipeId: "chicken" },
    { id: "rice", name: "糙米饭", type: "Carbs", portions: 6 },
    { id: "veg", name: "西兰花", type: "Vegetables", portions: 4 },
  ];
  for (const item of inventory) await command(request, "inventory.save", { item: { ...item, location: "Freezer", prepared: true, addedOn: "2026-09-17", priority: false } });
  const plan: WeeklyPlan = { id: "week", weekStart: week, status: "draft", version: 1, prompt: "E2E fixture", chat: [], meals: [{ id: "dinner", day: "2026-09-23", slot: "dinner", components: inventory.map(item => ({ id: item.id, name: item.name, type: item.type as Recipe["type"], portions: 3, inventoryId: item.id, ...(item.id === "meat" ? { recipeId: "chicken", prepId: "prep" } : {}) })), activeMinutes: 5, elapsedMinutes: 10, steps: ["Reheat the prepared portions", "Serve and tidy"], status: "planned", liked: false, locked: false }], prep: [{ id: "prep", name: "鸡肉丸", type: "Protein", recipeId: "chicken", plannedPortions: 3, actualPortions: 0, activeMinutes: 8, elapsedMinutes: 18, steps: recipe.steps, status: "planned", liked: false, outputInventoryId: "meat", inputs: [], equipment: ["stove"], dependencies: [] }] };
  await command(request, "plan.save", { plan });
}
const portions = async (request: APIRequestContext) => (await state(request)).inventory.map(item => item.portions);

test("plan journey resumes and confirmation opens persistent shopping and prep panels", async ({ page }, testInfo) => {
  await login(page); await seed(page.request);
  await page.goto(`/plan?week=${week}`);
  await page.getByRole("button", { name: "Back to step 1, meals and preferences", exact: true }).click();
  await expect(page.getByRole("region", { name: "Plan setup" })).toBeVisible();
  await page.goto(`/calendar?week=${week}`);
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await expect(nav.getByRole("button").first()).toHaveText(/Plan/);
  await nav.getByRole("button", { name: "Plan", exact: true }).click();
  await expect(page.getByRole("region", { name: "Plan setup" })).toBeVisible();
  await page.getByRole("button", { name: "Go to step 2, adjust", exact: true }).click();
  await page.getByRole("button", { name: "Confirm plan", exact: true }).click();
  await expect(page.getByText("Stu is preparing your week…", {exact:true})).toBeVisible();
  await page.screenshot({path:`/tmp/stu-confirm-${testInfo.project.name}.png`,fullPage:true});
  await expect(page.getByRole("region", { name: "Shopping and prep", exact: true })).toBeVisible();
  const shoppingToggle = page.getByRole("button", { name: /Shopping cart.*picked up/ });
  const prepToggle = page.getByRole("button", { name: /Prep day.*dishes ready/ });
  await expect(shoppingToggle).toHaveAttribute("aria-expanded", "true");
  await expect(prepToggle).toHaveAttribute("aria-expanded", "false");
  const item = page.getByLabel("Purchased 鸡肉 300 g", { exact: true });
  await item.check(); await expect(item).toBeChecked();
  await expect.poll(async () => (await state(page.request)).plans[0].shoppingChecked?.length).toBe(1);
  await page.goto(`/plan?week=${week}`);
  await expect(item).toBeChecked();
  await page.screenshot({ path: `/tmp/stu-workflow-${testInfo.project.name}-shopping.png`, fullPage: true });
  await prepToggle.click();
  await expect(prepToggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("region", { name: "Ingredients for 鸡肉丸" })).toContainText("300 g");
  await page.reload();
  await expect(prepToggle).toHaveAttribute("aria-expanded", "true");
  await page.screenshot({ path: `/tmp/stu-workflow-${testInfo.project.name}-prep.png`, fullPage: true });
  const widths = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: window.innerWidth }));
  expect(widths.content).toBeLessThanOrEqual(widths.viewport);
  await page.getByRole("button", { name: "View calendar", exact: true }).click();
  await expect(page.getByRole("region", { name: "Weekly meal calendar" })).toHaveClass(/kw-calendar-plan/);
  await expect(page.getByRole("combobox", { name: "Plan version" })).toBeVisible();
  await page.getByRole("navigation", { name: "Main navigation" }).getByRole("button", { name: "Plan", exact: true }).click();
  await expect(prepToggle).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("button", { name: "Edit plan", exact: true }).click();
  await page.getByRole("button", { name: "Confirm plan", exact: true }).click();
  await expect(shoppingToggle).toHaveAttribute("aria-expanded", "true");
  expect((await state(page.request)).weeklyPrompts?.find(p => p.weekStart === week)?.workflow?.step).toBe("shopping");
});

test("real login and Chinese fridge edits survive reload, with no demo seed", async ({ page }) => {
  await login(page);
  expect((await state(page.request)).inventory).toEqual([]);
  await page.goto(`/fridge?week=${week}`);
  await page.getByRole("button", { name: "Add food to Fridge", exact: true }).click();
  await page.getByLabel("Name", { exact: true }).fill("宝宝南瓜泥");
  await page.getByLabel("Portions", { exact: true }).fill("2.5");
  await page.getByRole("combobox", { name: "Type", exact: true }).selectOption("Vegetables");
  await page.getByRole("button", { name: "Save food", exact: true }).click();
  await expect(page.getByRole("heading", { name: "宝宝南瓜泥", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "宝宝南瓜泥", exact: true })).toBeVisible();
  expect((await state(page.request)).inventory[0].portions).toBe(2.5);
  const widths = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: window.innerWidth }));
  expect(widths.content).toBeLessThanOrEqual(widths.viewport);
});

test("confirmed plan, prep, drawer completion, liking and undo persist to PostgreSQL", async ({ page }) => {
  await login(page);
  await seed(page.request);
  await page.goto(`/plan?week=${week}&plan=week`);
  await page.getByRole("button", { name: "Confirm plan", exact: true }).click();
  await expect.poll(async () => (await state(page.request)).plans[0].status).toBe("confirmed");
  expect(await portions(page.request)).toEqual([2, 6, 4]);
  await page.goto(`/prep?week=${week}&plan=week`);
  await page.getByRole("button", { name: "Mark prepared", exact: true }).click();
  await expect.poll(() => portions(page.request)).toEqual([5, 6, 4]);
  await page.goto(`/calendar?week=${week}&plan=week&meal=dinner`);
  const drawer = page.getByRole("dialog");
  await expect(drawer).toBeVisible();
  await drawer.getByRole("button", { name: "Mark completed", exact: true }).click();
  await expect.poll(() => portions(page.request)).toEqual([2, 3, 1]);
  await drawer.getByRole("button", { name: "Baby liked it", exact: true }).click();
  await expect.poll(async () => (await state(page.request)).plans[0].meals[0].liked).toBe(true);
  expect(await portions(page.request)).toEqual([2, 3, 1]);
  await drawer.getByRole("button", { name: "Undo completion", exact: true }).click();
  await expect.poll(() => portions(page.request)).toEqual([5, 6, 4]);
  expect((await state(page.request)).plans[0].meals[0].liked).toBe(true);
  await drawer.getByRole("button", { name: "Skip meal", exact: true }).click();
  await expect.poll(async () => (await state(page.request)).plans[0].meals[0].status).toBe("skipped");
  expect(await portions(page.request)).toEqual([5, 6, 4]);
  await page.reload();
  await expect(page.getByRole("dialog").getByText("skipped", { exact: true })).toBeVisible();
});

test("missing AI key is explicit and preserves saved weekly preferences", async ({ page }) => {
  await login(page);
  await command(page.request, "planning.prompt", { weekStart: week, prompt: "优先消耗菠菜，早餐不吃鸡蛋" });
  await page.goto(`/plan?week=${week}`);
  await expect(page.getByLabel("This week’s preferences")).toHaveValue("优先消耗菠菜，早餐不吃鸡蛋");
  await page.getByRole("button", { name: "Generate week", exact: true }).click();
  await expect(page.locator("main").getByRole("alert")).toContainText("OPENAI_API_KEY");
  expect((await state(page.request)).plans).toEqual([]);
  await page.reload();
  await expect(page.getByLabel("This week’s preferences")).toHaveValue("优先消耗菠菜，早餐不吃鸡蛋");
});

test("MCP writes share live state and require an authenticated household", async ({ page, playwright }) => {
  await login(page);
  const headers = { Accept: "application/json, text/event-stream" };
  const init = await page.request.post(`${apiBase}/api/v1/kitchen/mcp`, { headers, data: { jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-03-26", capabilities: {}, clientInfo: { name: "e2e", version: "1" } } } });
  expect(init.ok()).toBeTruthy();
  const response = await page.request.post(`${apiBase}/api/v1/kitchen/mcp`, { headers, data: { jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "kitchen_command", arguments: { type: "inventory.save", payload: { item: { id: "mcp-stock", name: "MCP 红薯", type: "Carbs", portions: 3, location: "Fridge", prepared: true, addedOn: "2026-09-17", priority: false } }, expectedRevision: (await state(page.request)).revision, operationId: randomUUID() } } } });
  expect(response.ok(), await response.text()).toBeTruthy();
  expect((await response.json()).result.isError).not.toBe(true);
  await page.goto(`/fridge?week=${week}`);
  await expect(page.getByRole("heading", { name: "MCP 红薯", exact: true })).toBeVisible();
  const outsider = await playwright.request.newContext();
  try { expect((await outsider.post(`${apiBase}/api/v1/kitchen/mcp`, { headers: { Accept: "application/json, text/event-stream" }, data: { jsonrpc: "2.0", id: 3, method: "tools/list" } })).status()).toBe(401); }
  finally { await outsider.dispose(); }
});

test("nutrition documents import, persist, version, filter and delete through the real API", async ({ page }) => {
  await login(page);
  await page.getByRole("button", { name: "Settings and knowledge", exact: true }).click();
  await expect(page.getByRole("button", { name: "Knowledge", exact: true })).toBeInViewport({ ratio: 1 });
  await expect(page.getByRole("button", { name: "Settings", exact: true })).toBeInViewport({ ratio: 1 });
  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Your reference library" })).toBeVisible();
  await page.getByLabel("Import text or Markdown").setInputFiles({ name: "宝宝膳食参考.md", mimeType: "text/markdown", buffer: Buffer.from("# 家庭参考\n早餐交替安排，隔一天可以重复。", "utf8") });
  await expect(page.getByRole("heading", { name: "Import preview" })).toBeVisible();
  expect((await state(page.request)).knowledgeDocuments).toEqual([]);
  await page.getByLabel("Category", { exact: true }).fill("Family preferences");
  await page.getByRole("button", { name: "Save document", exact: true }).click();
  await expect(page.getByRole("heading", { name: "宝宝膳食参考", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "宝宝膳食参考", exact: true })).toBeVisible();
  const saved = (await state(page.request)).knowledgeDocuments![0];
  expect(saved.content).toContain("隔一天可以重复");
  expect(saved.version).toBe(1);
  await page.getByLabel("Enable 宝宝膳食参考", { exact: true }).uncheck();
  await expect.poll(async () => (await state(page.request)).knowledgeDocuments![0].enabled).toBe(false);
  expect((await state(page.request)).knowledgeDocuments![0].version).toBe(2);
  await page.getByRole("button", { name: "Edit 宝宝膳食参考", exact: true }).click();
  await page.getByRole("textbox", { name: "Document content", exact: true }).fill("早餐交替安排。午餐和晚餐搭配蔬菜。合成测试参考资料。");
  await page.getByRole("button", { name: "Save document", exact: true }).click();
  await expect.poll(async () => (await state(page.request)).knowledgeDocuments![0].version).toBe(3);
  await page.getByLabel("Search documents", { exact: true }).fill("不存在的内容");
  await expect(page.getByRole("heading", { name: "No matching documents", exact: true })).toBeVisible();
  await page.getByLabel("Search documents", { exact: true }).fill("蔬菜");
  await expect(page.getByRole("heading", { name: "宝宝膳食参考", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Delete 宝宝膳食参考", exact: true }).click();
  await page.getByRole("button", { name: "Confirm delete", exact: true }).click();
  await expect.poll(async () => (await state(page.request)).knowledgeDocuments).toEqual([]);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Build your nutrition library", exact: true })).toBeVisible();
  const widths = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: window.innerWidth }));
  expect(widths.content).toBeLessThanOrEqual(widths.viewport);
});

test("Figma navigation, recipe drawer and all page layouts work at desktop and phone widths", async ({ page }) => {
  for (const destination of ["calendar", "plan", "fridge", "recipes", "guidance", "prep", "knowledge"]) {
    await page.goto(`/demo?week=${week}&plan=plan-demo&page=${destination}`);
    await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
    await expect(page.getByText("Loading your kitchen…")).toHaveCount(0);
    const logo = page.getByRole("img", { name: "Stu baby logo", exact: true });
    await expect(logo).toBeVisible();
    await expect(logo).toHaveAttribute("src", /stu-logo/);
    const widths = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: window.innerWidth }));
    expect(widths.content, `${destination} must not overflow the viewport`).toBeLessThanOrEqual(widths.viewport);
  }
  await page.getByRole("button", { name: "Recipes", exact: true }).click();
  await page.getByRole("button", { name: "Open recipe 鸡肉丸", exact: true }).click();
  // A recipe has its own page (frame 36:1030), with editing on that page.
  await expect(page).toHaveURL(/\/recipes\/[^/]+$/);
  const recipe = page.getByRole("article", { name: "Recipe 鸡肉丸" });
  await expect(recipe.getByRole("button", { name: "✎ 编辑 Edit", exact: true })).toBeInViewport();
  await recipe.getByRole("button", { name: "← Recipe Book", exact: true }).click();
  await expect(page).toHaveURL(/\/recipes$/);
});

test("planning hides execution, locks recur and recipe details open a real new tab",async({page},testInfo)=>{
  await login(page);await seed(page.request);
  await page.goto(`/plan?week=${week}&plan=week&meal=dinner`);
  const drawer=page.getByRole("dialog");
  await expect(drawer.getByText("From your fridge",{exact:true})).toBeVisible();
  await expect(drawer.getByRole("button",{name:"Mark completed",exact:true})).toHaveCount(0);
  await expect(drawer.getByRole("button",{name:"Baby liked it",exact:true})).toHaveCount(0);
  await expect(drawer.getByRole("button",{name:"Edit meal",exact:true})).toBeVisible();
  await drawer.getByRole("button",{name:"Lock this meal every week",exact:true}).click();
  await expect.poll(async()=> (await state(page.request)).settings.recurringMeals?.length).toBe(1);
  await page.screenshot({path:`/tmp/stu-drawer-${testInfo.project.name}.png`,fullPage:true});
  const popupPromise=page.waitForEvent("popup");
  await drawer.getByRole("link",{name:"View recipe for 鸡肉丸",exact:true}).click();
  const popup=await popupPromise;
  await expect(popup).toHaveURL(/\/recipes\/chicken/);
  await expect(popup.getByRole("heading",{name:"鸡肉丸",exact:true})).toBeVisible();
  await expect(popup.getByRole("heading",{name:"Ingredients",exact:true})).toBeVisible();
  await popup.screenshot({path:`/tmp/stu-recipe-${testInfo.project.name}.png`,fullPage:true});
  await popup.close();
  await drawer.getByRole("button",{name:"Close drawer",exact:true}).click();
  const next=structuredClone((await state(page.request)).plans[0]);
  next.id="next-week";next.weekStart="2026-09-28";next.meals[0].id="next-dinner";next.meals[0].day="2026-09-30";next.meals[0].locked=false;
  await command(page.request,"plan.save",{plan:next});
  await page.goto("/calendar?week=2026-09-28&plan=next-week");
  await page.getByRole("button",{name:"Unlock weekly meal",exact:true}).click();
  await expect.poll(async()=>(await state(page.request)).settings.recurringMeals?.length).toBe(0);
  expect((await state(page.request)).plans.every(p=>!p.meals[0].locked)).toBe(true);
});

test("failed AI confirmation keeps the draft and displays retry",async({page})=>{
  await login(page);await seed(page.request);
  const p=(await state(page.request)).plans[0];p.prompt="E2E provider failure";
  await command(page.request,"plan.save",{plan:p});
  await page.goto(`/plan?week=${week}&plan=week`);
  await page.getByRole("button",{name:"Confirm plan",exact:true}).click();
  await expect(page.getByText("Stu is preparing your week…",{exact:true})).toBeVisible();
  await expect(page.getByRole("button",{name:"Try again",exact:true})).toBeVisible();
  expect((await state(page.request)).plans[0].status).toBe("draft");
  await page.reload();
  await expect(page.getByRole("button",{name:"Try again",exact:true})).toBeVisible();
});
