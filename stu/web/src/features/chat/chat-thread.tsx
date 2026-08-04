import type { AgentResponse } from "@/lib/api";
import type { Locale } from "@/i18n/catalog";

import { SuggestedActions } from "./suggested-actions";

const SECTION_LABELS = {
  "en-US": { thinking: "Thinking", plan: "Plan", act: "Act", answer: "Answer" },
  "zh-CN": { thinking: "思考", plan: "计划", act: "执行", answer: "回答" },
} as const;

export function ChatThread({ response, locale }: { response: AgentResponse; locale: Locale }) {
  const labels = SECTION_LABELS[locale];
  return (
    <article className="chat-thread" aria-live="polite">
      {(["thinking", "plan", "act", "answer"] as const).map((section) => (
        <section className={`agent-section agent-${section}`} key={section}>
          <h2>{labels[section]}</h2>
          <p>{response[section]}</p>
        </section>
      ))}
      <SuggestedActions actions={response.suggested_actions} locale={locale} />
    </article>
  );
}
