"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { useLocale } from "@/i18n/locale-context";
import { useFeatureData } from "@/lib/use-feature-data";

import { LanguageSwitcher } from "./language-switcher";

const navigation = [
  ["chat", "/chat", "✦"], ["recipes", "/recipes", "▦"], ["plan", "/plan", "◷"],
  ["shopping", "/shopping", "✓"], ["imports", "/imports", "⇩"],
  ["shares", "/shares", "↗"], ["settings", "/settings", "⚙"],
] as const;

interface ShellSettings {
  members: { owner_display_name: string; is_owned_by_current_account: boolean }[];
  lark_binding: { is_linked: boolean };
}

export function PrivateAppShell({ children, pathname }: { children: ReactNode; pathname: string }) {
  const { catalog, locale } = useLocale();
  const settings = useFeatureData<ShellSettings>("/api/v1/settings");
  const recipes = useFeatureData<{ recipes: unknown[] }>("/api/v1/recipes");
  const mine = settings.status === "ready" ? settings.data.members.find((member) => member.is_owned_by_current_account) : undefined;
  const linked = settings.status === "ready" && settings.data.lark_binding.is_linked;
  const count = recipes.status === "ready" ? recipes.data.recipes.length : null;
  const household = mine?.owner_display_name ? `${mine.owner_display_name} ${locale === "zh-CN" ? "的家庭" : "household"}` : catalog.shell.household;
  const recipeCount = count === null ? catalog.shell.recipeCount : locale === "zh-CN" ? `${count} 道家庭菜谱` : `${count} household recipes`;
  const larkStatus = linked ? catalog.shell.larkConnected : locale === "zh-CN" ? "Lark 未连接" : "Lark not connected";

  return <div className="app-frame">
    <aside className="sidebar">
      <Link className="brand" href="/chat"><span className="brand-mark">F</span><span><strong>{catalog.brand}</strong><small>{catalog.tagline}</small></span></Link>
      <nav aria-label={catalog.shell.primaryNavigation}>{navigation.map(([key, href, icon]) => <Link
        aria-current={pathname === href || (href === "/recipes" && pathname.startsWith("/recipes/")) ? "page" : undefined}
        aria-label={catalog.nav[key]} className="nav-link" href={href} key={key}>
        <span className="nav-icon" aria-hidden="true">{icon}</span><span className="nav-label">{catalog.nav[key]}</span>
      </Link>)}</nav>
      <div className="household-card"><span className="household-avatar">{mine?.owner_display_name?.slice(0, 1).toUpperCase() ?? "F"}</span><span><strong>{household}</strong><small>{recipeCount}</small></span></div>
    </aside>
    <section className="workspace"><header className="topbar"><div className={`status-pill${linked ? "" : " disconnected"}`}><span /> {larkStatus}</div><LanguageSwitcher /></header><main>{children}</main></section>
  </div>;
}
