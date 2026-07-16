"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useLocale } from "@/i18n/locale-context";

import { LanguageSwitcher } from "./language-switcher";

interface AppShellProps {
  children: ReactNode;
}

const navigation = [
  ["chat", "/chat", "✦"],
  ["recipes", "/recipes", "▦"],
  ["plan", "/plan", "◷"],
  ["shopping", "/shopping", "✓"],
  ["imports", "/imports", "⇩"],
  ["shares", "/shares", "↗"],
  ["settings", "/settings", "⚙"],
] as const;

export function AppShell({ children }: AppShellProps) {
  const { catalog } = useLocale();
  const pathname = usePathname() ?? "/chat";

  if (pathname.startsWith("/s/")) {
    return (
      <div className="public-frame">
        <header className="public-topbar">
          <Link className="brand brand-on-light" href="/chat">
            <span className="brand-mark">F</span>
            <strong>{catalog.brand}</strong>
          </Link>
          <LanguageSwitcher />
        </header>
        <main>{children}</main>
      </div>
    );
  }

  return (
    <div className="app-frame">
      <aside className="sidebar">
        <Link className="brand" href="/chat">
          <span className="brand-mark">F</span>
          <span>
            <strong>{catalog.brand}</strong>
            <small>{catalog.tagline}</small>
          </span>
        </Link>
        <nav aria-label={catalog.shell.primaryNavigation}>
          {navigation.map(([key, href, icon]) => (
            <Link
              aria-current={pathname === href || (href === "/recipes" && pathname.startsWith("/recipes/")) ? "page" : undefined}
              aria-label={catalog.nav[key]}
              className="nav-link"
              href={href}
              key={key}
            >
              <span className="nav-icon" aria-hidden="true">{icon}</span>
              <span className="nav-label">{catalog.nav[key]}</span>
            </Link>
          ))}
        </nav>
        <div className="household-card">
          <span className="household-avatar">Y</span>
          <span><strong>{catalog.shell.household}</strong><small>{catalog.shell.recipeCount}</small></span>
        </div>
      </aside>
      <section className="workspace">
        <header className="topbar">
          <div className="status-pill"><span /> {catalog.shell.larkConnected}</div>
          <LanguageSwitcher />
        </header>
        <main>{children}</main>
      </section>
    </div>
  );
}
