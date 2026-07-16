"use client";

import { useLocale } from "@/i18n/locale-context";

export function LanguageSwitcher() {
  const { catalog, locale, setLocale } = useLocale();

  return (
    <div className="language-switcher" aria-label={catalog.language.label}>
      <button
        className={locale === "zh-CN" ? "language-button active" : "language-button"}
        onClick={() => setLocale("zh-CN")}
        type="button"
      >
        {catalog.language.chinese}
      </button>
      <button
        className={locale === "en-US" ? "language-button active" : "language-button"}
        onClick={() => setLocale("en-US")}
        type="button"
      >
        {catalog.language.english}
      </button>
    </div>
  );
}
