import type { Metadata } from "next";
import type { ReactNode } from "react";

import { LocalizedApp } from "@/components/localized-app";

import "./globals.css";

export const metadata: Metadata = {
  title: "Family Table",
  description: "A private household recipe agent for Lark and the web.",
};

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        <LocalizedApp initialLocale="zh-CN">{children}</LocalizedApp>
      </body>
    </html>
  );
}
