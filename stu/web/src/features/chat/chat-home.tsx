"use client";

import { useEffect, useState, type FormEvent } from "react";

import { Login } from "@/features/auth/login";
import { useLocale } from "@/i18n/locale-context";
import { ApiError, api, type SessionIdentity } from "@/lib/api";

import { ChatThread } from "./chat-thread";
import { useAgentRun } from "@/lib/use-agent-run";

export function ChatHome() {
  const { catalog, locale } = useLocale();
  const [identity, setIdentity] = useState<SessionIdentity | null | undefined>(undefined);
  const [message, setMessage] = useState("");
  const run = useAgentRun(locale);

  useEffect(() => {
    let active = true;
    api<SessionIdentity>("/api/v1/auth/session")
      .then((session) => { if (active) setIdentity(session); })
      .catch((error) => {
        if (active && error instanceof ApiError && error.status === 401) setIdentity(null);
      });
    return () => { active = false; };
  }, []);

  if (identity === null) return <Login locale={locale} onAuthenticated={setIdentity} />;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = message.trim();
    if (!identity || !value || run.phase === "submitting" || run.phase === "polling") return;
    void run.submit(value);
  }

  const busy = identity === undefined || run.phase === "submitting" || run.phase === "polling";

  return (
    <section className="chat-home">
      <div className="hero-copy">
        <p className="eyebrow">{catalog.chat.eyebrow}</p>
        <h1>{catalog.chat.title}</h1>
        <p>{catalog.chat.subtitle}</p>
      </div>
      <form className="prompt-card" onSubmit={submit}>
        <textarea
          aria-label={catalog.chat.placeholder}
          placeholder={catalog.chat.placeholder}
          rows={3}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
        />
        <div className="prompt-actions">
          <span className="attachment-hint"><span aria-hidden="true">＋ </span>{catalog.chat.attachments}</span>
          <button type="submit" disabled={busy}>{busy ? "…" : catalog.chat.send} <span aria-hidden="true">→</span></button>
        </div>
      </form>
      <div className="quick-actions">
        {[catalog.chat.quickOne, catalog.chat.quickTwo, catalog.chat.quickThree].map((prompt) => (
          <button type="button" key={prompt} onClick={() => setMessage(prompt)}>{prompt}</button>
        ))}
      </div>
      {busy ? (
        <section className="run-waiting" role="status">
          <strong>{locale === "zh-CN" ? "思考" : "Thinking"}</strong>
          <span>{locale === "zh-CN" ? " → 计划 → 执行" : " → Plan → Act"}</span>
        </section>
      ) : null}
      {run.phase === "failed" ? (
        <p className="chat-error" role="alert">{locale === "zh-CN" ? "助手暂时无法完成，请重试。" : "The assistant could not finish. Please try again."}</p>
      ) : null}
      {run.phase === "completed" && run.run?.response ? <ChatThread response={run.run.response} locale={locale} /> : null}
    </section>
  );
}
