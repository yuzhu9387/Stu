import type { Metadata } from "next";
import type { ReactNode } from "react";

import { LocalizedApp } from "@/components/localized-app";

import "./globals.css";

export const metadata: Metadata = {
  title: "Stu · Family Table",
  description: "Plan a balanced week, prep together, and make everyday meals simpler.",
};

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <LocalizedApp initialLocale="en-US">{children}</LocalizedApp>
      </body>
    </html>
  );
}
