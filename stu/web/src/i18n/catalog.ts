import enUS from "./en-US.json";
import zhCN from "./zh-CN.json";

export type Locale = "en-US" | "zh-CN";
export type Catalog = typeof enUS;

const catalogs: Record<Locale, Catalog> = {
  "en-US": enUS,
  "zh-CN": zhCN,
};

export function getCatalog(locale: Locale): Catalog {
  return catalogs[locale];
}
