"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { getCatalog, type Catalog, type Locale } from "./catalog";

interface LocaleContextValue {
  locale: Locale;
  catalog: Catalog;
  setLocale: (locale: Locale) => void;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

interface LocaleProviderProps {
  children: ReactNode;
  initialLocale: Locale;
}

export function LocaleProvider({ children, initialLocale }: LocaleProviderProps) {
  const [locale, setLocale] = useState<Locale>(initialLocale);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo(
    () => ({ locale, catalog: getCatalog(locale), setLocale }),
    [locale],
  );

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  const context = useContext(LocaleContext);
  if (context === null) {
    throw new Error("useLocale must be used inside LocaleProvider");
  }
  return context;
}
