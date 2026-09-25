"use client";

import type { Catalog } from "@/i18n/catalog";
import { useLocale } from "@/i18n/locale-context";

export type FeaturePage = keyof Catalog["pages"];

interface FeatureScreenProps {
  page: FeaturePage;
}

export function FeatureScreen({ page }: FeatureScreenProps) {
  const { catalog } = useLocale();
  const content = catalog.pages[page];

  return (
    <section className="feature-screen">
      <header className="feature-header">
        <div>
          <p className="eyebrow">{content.eyebrow}</p>
          <h1>{content.title}</h1>
          <p className="feature-description">{content.body}</p>
        </div>
        <button className="primary-button" type="button">
          {content.action}
          <span aria-hidden="true">→</span>
        </button>
      </header>

      <div className="metric-strip">
        <span className="metric-dot" aria-hidden="true" />
        {content.metric}
      </div>

      <div className="record-grid">
        {content.items.map((item, index) => (
          <article className="record-card" key={item.title}>
            <span className="record-index" aria-hidden="true">
              {String(index + 1).padStart(2, "0")}
            </span>
            <div>
              <h2>{item.title}</h2>
              <p>{item.detail}</p>
            </div>
            <small>{item.meta}</small>
          </article>
        ))}
      </div>
    </section>
  );
}
