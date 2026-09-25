"use client";

import type { Catalog } from "@/i18n/catalog";
import { useLocale } from "@/i18n/locale-context";
import { useFeatureData } from "@/lib/use-feature-data";

type Page = "recipes" | "plan" | "shopping" | "imports" | "shares";

interface OwnedRecord {
  id: string;
  owner_display_name?: string;
  is_owned_by_current_account?: boolean;
}

interface Recipe extends OwnedRecord { name: string; visibility: string; created_at: string }
interface PlanItem { day: string; slot: string; recipe_name: string }
interface Plan extends OwnedRecord { week_start: string; version: number; items: PlanItem[] }
interface ShoppingEntry { name: string; quantity: string | number; unit: string; checked: boolean }
interface ShoppingList extends OwnedRecord { version: number; entries: ShoppingEntry[] }
interface Import extends OwnedRecord { kind: string; status: string; error_code: string | null; created_at: string }
interface Share extends OwnedRecord { expires_at: string; revoked_at: string | null }

type Payload =
  | { recipes: Recipe[] }
  | { plans: Plan[] }
  | { shopping_lists: ShoppingList[] }
  | { imports: Import[] }
  | { shares: Share[] };

interface LiveRecord {
  id: string;
  title: string;
  detail: string;
  meta: string;
  owner?: string;
}

const PATHS: Record<Page, string> = {
  recipes: "/api/v1/recipes",
  plan: "/api/v1/plans",
  shopping: "/api/v1/shopping-lists",
  imports: "/api/v1/imports",
  shares: "/api/v1/shares",
};

function owner(record: OwnedRecord, current: string): string | undefined {
  if (!record.owner_display_name) return undefined;
  return record.is_owned_by_current_account ? current : record.owner_display_name;
}

function records(page: Page, payload: Payload, locale: "en-US" | "zh-CN"): LiveRecord[] {
  const mine = locale === "zh-CN" ? "我" : "Me";
  if (page === "recipes" && "recipes" in payload) {
    return payload.recipes.map((item) => ({
      id: item.id,
      title: item.name,
      detail: item.visibility,
      meta: new Intl.DateTimeFormat(locale).format(new Date(item.created_at)),
      owner: owner(item, mine),
    }));
  }
  if (page === "plan" && "plans" in payload) {
    return payload.plans.map((item) => ({
      id: item.id,
      title: new Intl.DateTimeFormat(locale).format(new Date(`${item.week_start}T00:00:00`)),
      detail: item.items.map((entry) => `${entry.day} · ${entry.recipe_name}`).join(" · "),
      meta: `${locale === "zh-CN" ? "版本" : "Version"} ${item.version}`,
      owner: owner(item, mine),
    }));
  }
  if (page === "shopping" && "shopping_lists" in payload) {
    return payload.shopping_lists.map((item) => ({
      id: item.id,
      title: locale === "zh-CN" ? "购物清单" : "Shopping list",
      detail: item.entries.map((entry) => `${entry.name} ${entry.quantity} ${entry.unit}`).join(" · "),
      meta: `${item.entries.filter((entry) => !entry.checked).length} ${locale === "zh-CN" ? "项待购买" : "remaining"}`,
      owner: owner(item, mine),
    }));
  }
  if (page === "imports" && "imports" in payload) {
    return payload.imports.map((item) => ({
      id: item.id,
      title: item.kind,
      detail: item.error_code ?? item.status,
      meta: new Intl.DateTimeFormat(locale).format(new Date(item.created_at)),
      owner: owner(item, mine),
    }));
  }
  if (page === "shares" && "shares" in payload) {
    return payload.shares.map((item) => ({
      id: item.id,
      title: item.revoked_at ? (locale === "zh-CN" ? "已撤销分享" : "Revoked share") : locale === "zh-CN" ? "有效分享" : "Active share",
      detail: `${locale === "zh-CN" ? "到期" : "Expires"}: ${new Intl.DateTimeFormat(locale).format(new Date(item.expires_at))}`,
      meta: item.id.slice(0, 8),
      owner: owner(item, mine),
    }));
  }
  return [];
}

export function LiveFeatureScreen({ page }: { page: Page }) {
  const { catalog, locale } = useLocale();
  const content = catalog.pages[page] as Catalog["pages"][Page];
  const state = useFeatureData<Payload>(PATHS[page]);
  const rows = state.status === "ready" ? records(page, state.data, locale) : [];
  const loading = locale === "zh-CN" ? "正在读取家庭数据…" : "Loading household data…";
  const empty = locale === "zh-CN" ? "这里还没有记录。" : "No records yet.";
  const failed = locale === "zh-CN" ? "无法读取数据，请先登录或稍后重试。" : "Could not load data. Sign in or try again.";

  return (
    <section className="feature-screen">
      <header className="feature-header">
        <div>
          <p className="eyebrow">{content.eyebrow}</p>
          <h1>{content.title}</h1>
          <p className="feature-description">{content.body}</p>
        </div>
      </header>
      <div className="metric-strip">
        <span className="metric-dot" aria-hidden="true" />
        {state.status === "ready" ? `${rows.length} ${locale === "zh-CN" ? "条记录" : "records"}` : loading}
      </div>
      {state.status === "error" ? <p className="empty-state" role="alert">{failed}</p> : null}
      {state.status === "ready" && rows.length === 0 ? <p className="empty-state">{empty}</p> : null}
      <div className="record-grid">
        {rows.map((item, index) => (
          <article className="record-card" key={item.id}>
            <span className="record-index" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
            <div><h2>{item.title}</h2><p>{item.detail || empty}</p></div>
            <small>{item.owner ? `${locale === "zh-CN" ? "所有者" : "Owner"}: ${item.owner} · ` : ""}{item.meta}</small>
          </article>
        ))}
      </div>
    </section>
  );
}
