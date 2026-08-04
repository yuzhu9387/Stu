"use client";

import type { ReactNode } from "react";

import { LocaleProvider } from "@/i18n/locale-context";
import type { Locale } from "@/i18n/catalog";

import { AppShell } from "./app-shell";
import { ChatHome } from "../features/chat/chat-home";

interface LocalizedAppProps {
  children?: ReactNode;
  initialLocale: Locale;
}

export function LocalizedApp({ children, initialLocale }: LocalizedAppProps) {
  return (
    <LocaleProvider initialLocale={initialLocale}>
      <AppShell>{children ?? <ChatHome />}</AppShell>
    </LocaleProvider>
  );
}
