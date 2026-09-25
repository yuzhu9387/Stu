"use client";

import { useState, type FormEvent } from "react";

import { api, type SessionIdentity } from "@/lib/api";
import type { Locale } from "@/i18n/catalog";

interface LoginProps {
  locale: Locale;
  onAuthenticated: (identity: SessionIdentity) => void;
}

export function Login({ locale, onAuthenticated }: LoginProps) {
  const chinese = locale === "zh-CN";
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const delivery = await api<{ status: string; development_token?: string }>(
        "/api/v1/auth/magic-links",
        { method: "POST", body: JSON.stringify({ email }) },
      );
      if (!delivery.development_token) {
        setMessage(chinese ? "登录链接已发送，请检查邮箱。" : "Check your email for the sign-in link.");
        return;
      }
      await api<void>("/api/v1/auth/sessions", {
        method: "POST",
        body: JSON.stringify({ token: delivery.development_token }),
      });
      onAuthenticated(await api<SessionIdentity>("/api/v1/auth/session"));
    } catch {
      setMessage(chinese ? "登录失败，请重试。" : "Sign-in failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="login-card" aria-label={chinese ? "登录" : "Sign in"}>
      <p className="eyebrow">{chinese ? "私人家庭空间" : "PRIVATE HOUSEHOLD SPACE"}</p>
      <h1>{chinese ? "登录你的家庭餐桌" : "Sign in to Family Table"}</h1>
      <p>{chinese ? "每位家庭成员使用自己的账户。" : "Every family member keeps a separate account."}</p>
      <form onSubmit={submit}>
        <label htmlFor="login-email">{chinese ? "邮箱" : "Email"}</label>
        <input
          id="login-email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
          autoComplete="email"
        />
        <button className="primary-button" type="submit" disabled={busy}>
          {busy ? (chinese ? "登录中…" : "Signing in…") : chinese ? "登录" : "Sign in"}
        </button>
      </form>
      {message ? <p role="status">{message}</p> : null}
    </section>
  );
}
