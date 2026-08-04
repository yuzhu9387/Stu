"use client";

import { BowlFood, CalendarDots, ChatCircleDots, CookingPot, GearSix, ListChecks } from "@phosphor-icons/react";
import Link from "next/link";
import type { ReactNode } from "react";

import { useLocale } from "@/i18n/locale-context";
import { useFeatureData } from "@/lib/use-feature-data";

import { LanguageSwitcher } from "./language-switcher";

const navigation = [
  { key: "recipes", href: "/recipes", icon: BowlFood },
  { key: "plan", href: "/plan", icon: CalendarDots },
  { key: "todo", href: "/todo", icon: ListChecks },
] as const;

interface ShellSettings {
  members: { owner_display_name: string; is_owned_by_current_account: boolean }[];
  lark_binding: { is_linked: boolean };
}

export function PrivateAppShell({ children, pathname }: { children: ReactNode; pathname: string }) {
  const { locale } = useLocale();
  const chinese = locale === "zh-CN";
  const settings = useFeatureData<ShellSettings>("/api/v1/settings");
  const mine = settings.status === "ready" ? settings.data.members.find((member) => member.is_owned_by_current_account) : undefined;
  const linked = settings.status === "ready" && settings.data.lark_binding.is_linked;

  return <div className="family-app-shell">
    <aside className="family-sidebar">
      <Link className="family-brand" href="/recipes"><span><CookingPot size={24} weight="duotone" /></span><div><strong>Family Table</strong><small>{chinese ? "家的味道，都在这里" : "Recipes that feel like home"}</small></div></Link>
      <nav aria-label={chinese ? "主要导航" : "Primary navigation"}>
        {navigation.map(({ key, href, icon: Icon }) => <Link className="family-nav-link" aria-current={pathname.startsWith(href) ? "page" : undefined} href={href} key={key}><Icon size={21} weight={pathname.startsWith(href) ? "fill" : "regular"} /><span>{key === "recipes" ? (chinese ? "菜谱" : "Recipes") : key === "plan" ? (chinese ? "计划" : "Plan") : chinese ? "清单" : "Todo"}</span></Link>)}
      </nav>
      <div className="sidebar-secondary">
        <Link className="family-nav-link" aria-current={pathname === "/chat" ? "page" : undefined} href="/chat"><ChatCircleDots size={21} /><span>{chinese ? "智能助手" : "Assistant"}</span></Link>
        <Link className="family-nav-link" aria-current={pathname === "/settings" ? "page" : undefined} href="/settings"><GearSix size={21} /><span>{chinese ? "设置" : "Settings"}</span></Link>
      </div>
      <div className="family-profile"><span>{mine?.owner_display_name?.slice(0, 1).toUpperCase() ?? "F"}</span><div><strong>{mine?.owner_display_name ?? (chinese ? "我的家庭" : "My family")}</strong><small>{linked ? (chinese ? "Lark 已连接" : "Lark connected") : chinese ? "Lark 未连接" : "Lark not connected"}</small></div></div>
    </aside>
    <section className="family-workspace">
      <header className="family-topbar"><div className={`connection-status ${linked ? "linked" : ""}`}><span />{linked ? (chinese ? "Lark 已同步" : "Lark synced") : chinese ? "仅 Web" : "Web only"}</div><Link className="assistant-pill" href="/chat"><ChatCircleDots size={17} /> {chinese ? "问问助手" : "Ask assistant"}</Link><LanguageSwitcher /></header>
      <main>{children}</main>
    </section>
    <nav className="mobile-bottom-nav" aria-label={chinese ? "移动导航" : "Mobile navigation"}>{navigation.map(({ key, href, icon: Icon }) => <Link aria-current={pathname.startsWith(href) ? "page" : undefined} href={href} key={key}><Icon size={22} weight={pathname.startsWith(href) ? "fill" : "regular"} /><span>{key === "recipes" ? (chinese ? "菜谱" : "Recipes") : key === "plan" ? (chinese ? "计划" : "Plan") : chinese ? "清单" : "Todo"}</span></Link>)}</nav>
  </div>;
}
