"use client";

import { useLocale } from "@/i18n/locale-context";
import { useFeatureData } from "@/lib/use-feature-data";

interface PublicRecipe { id: string; name: string; ingredients: string[]; steps: string[] }

export function PublicShare({ token }: { token: string }) {
  const { locale } = useLocale();
  const state = useFeatureData<PublicRecipe>(`/api/v1/public/shares/${encodeURIComponent(token)}`);
  const chinese = locale === "zh-CN";
  if (state.status === "loading") return <p className="empty-state">{chinese ? "正在打开私密分享…" : "Opening private share…"}</p>;
  if (state.status === "error") return <p className="empty-state" role="alert">{chinese ? "链接无效、已撤销或已过期。" : "This link is invalid, revoked, or expired."}</p>;
  return <section className="feature-screen"><header className="feature-header"><div><p className="eyebrow">{chinese ? "私密分享" : "PRIVATE SHARE"}</p><h1>{state.data.name}</h1><p className="feature-description">{chinese ? "只显示获准公开的菜谱字段。" : "Only approved recipe fields are visible."}</p></div></header>
    <div className="record-grid"><article className="record-card"><span className="record-index">01</span><div><h2>{chinese ? "食材" : "Ingredients"}</h2><p>{state.data.ingredients.join(" · ")}</p></div></article><article className="record-card"><span className="record-index">02</span><div><h2>{chinese ? "步骤" : "Method"}</h2><p>{state.data.steps.join(" ")}</p></div></article></div>
  </section>;
}
