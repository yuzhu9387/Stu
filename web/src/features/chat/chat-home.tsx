"use client";

import { useLocale } from "@/i18n/locale-context";

export function ChatHome() {
  const { catalog } = useLocale();

  return (
    <section className="chat-home">
      <div className="hero-copy">
        <p className="eyebrow">{catalog.chat.eyebrow}</p>
        <h1>{catalog.chat.title}</h1>
        <p>{catalog.chat.subtitle}</p>
      </div>
      <div className="prompt-card">
        <textarea aria-label={catalog.chat.placeholder} placeholder={catalog.chat.placeholder} rows={3} />
        <div className="prompt-actions">
          <span className="attachment-hint"><span aria-hidden="true">＋ </span>{catalog.chat.attachments}</span>
          <button type="button">{catalog.chat.send} <span aria-hidden="true">→</span></button>
        </div>
      </div>
      <div className="quick-actions">
        <button type="button">{catalog.chat.quickOne}</button>
        <button type="button">{catalog.chat.quickTwo}</button>
        <button type="button">{catalog.chat.quickThree}</button>
      </div>
    </section>
  );
}
