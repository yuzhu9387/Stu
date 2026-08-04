"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useLocale } from "@/i18n/locale-context";

import { LanguageSwitcher } from "./language-switcher";
import { PrivateAppShell } from "./private-app-shell";

interface AppShellProps {
  children: ReactNode;
}

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

  return <PrivateAppShell pathname={pathname}>{children}</PrivateAppShell>;
}
