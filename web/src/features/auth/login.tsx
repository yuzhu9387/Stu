"use client";

import { useEffect, useState, type FormEvent } from "react";

import { api, ApiError, type SessionIdentity } from "@/lib/api";
import type { Locale } from "@/i18n/catalog";

interface LoginProps {
  locale: Locale;
  onAuthenticated: (identity: SessionIdentity) => void;
}

type Mode = "sign-in" | "register";
const MIN_PASSWORD = 8;

/** Sign in, or create an account: anyone can join, and each account gets its
 * own household. Locally the server also offers a passwordless shortcut. */
export function Login({ locale, onAuthenticated }: LoginProps) {
  const chinese = locale === "zh-CN";
  const t = (zh: string, en: string) => (chinese ? zh : en);
  const [mode, setMode] = useState<Mode>("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [shortcut, setShortcut] = useState(false);

  useEffect(() => {
    let live = true;
    api<{ password: boolean; developmentLink: boolean }>("/api/v1/auth/methods")
      .then(methods => { if (live) setShortcut(methods.developmentLink); })
      .catch(() => {});
    return () => { live = false; };
  }, []);

  function switchMode(next: Mode) {
    setMode(next);
    setMessage(null);
    setConfirm("");
  }

  async function finish() {
    onAuthenticated(await api<SessionIdentity>("/api/v1/auth/session"));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    if (mode === "register") {
      if (password.length < MIN_PASSWORD) { setMessage(t(`密码至少 ${MIN_PASSWORD} 个字符。`, `Use at least ${MIN_PASSWORD} characters.`)); return; }
      if (password !== confirm) { setMessage(t("两次输入的密码不一致。", "The passwords do not match.")); return; }
    }
    setBusy(true);
    try {
      await api<void>(mode === "register" ? "/api/v1/auth/register" : "/api/v1/auth/sign-in", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      await finish();
    } catch (error) {
      setMessage(error instanceof ApiError && error.status !== 500 && error.status !== 422
        ? error.message
        : error instanceof ApiError && error.status === 422
          ? t("请检查邮箱格式和密码。", "Check the email address and password.")
          : t("暂时无法登录，请重试。", "Unable to sign in right now. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  /** Local development only: the server hands the one-time token straight back. */
  async function quickSignIn() {
    setMessage(null);
    if (!email) { setMessage(t("先填写邮箱。", "Enter your email first.")); return; }
    setBusy(true);
    try {
      const delivery = await api<{ status: string; development_token?: string }>(
        "/api/v1/auth/magic-links",
        { method: "POST", body: JSON.stringify({ email }) },
      );
      if (!delivery.development_token) throw new Error("No development token");
      await api<void>("/api/v1/auth/sessions", {
        method: "POST",
        body: JSON.stringify({ token: delivery.development_token }),
      });
      await finish();
    } catch {
      setMessage(t("登录失败，请重试。", "Sign-in failed. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  const registering = mode === "register";
  return (
    <section className="login-card" aria-label={registering ? t("注册", "Create account") : t("登录", "Sign in")}>
      <p className="eyebrow">{t("私人家庭空间", "PRIVATE HOUSEHOLD SPACE")}</p>
      <h1>{registering ? t("创建你的家庭餐桌", "Create your Family Table") : t("登录你的家庭餐桌", "Sign in to Family Table")}</h1>
      <p>{registering ? t("注册后会得到一个只属于你家的空间。", "Your account comes with its own household space.") : t("每位家庭成员使用自己的账户。", "Every family member keeps a separate account.")}</p>
      <form onSubmit={submit}>
        <label htmlFor="login-email">{t("邮箱", "Email")}</label>
        <input id="login-email" type="email" value={email} onChange={event => setEmail(event.target.value)} required autoComplete="email" />
        <label htmlFor="login-password">{t("密码", "Password")}</label>
        <input id="login-password" type="password" value={password} onChange={event => setPassword(event.target.value)} required minLength={registering ? MIN_PASSWORD : undefined} maxLength={128} autoComplete={registering ? "new-password" : "current-password"} />
        {registering && <>
          <label htmlFor="login-confirm">{t("确认密码", "Confirm password")}</label>
          <input id="login-confirm" type="password" value={confirm} onChange={event => setConfirm(event.target.value)} required maxLength={128} autoComplete="new-password" />
        </>}
        <button className="primary-button" type="submit" disabled={busy}>
          {busy ? t("请稍候…", "Please wait…") : registering ? t("创建账户", "Create account") : t("登录", "Sign in")}
        </button>
      </form>
      {message ? <p className="login-message" role="alert">{message}</p> : null}
      <p className="login-switch">
        {registering ? t("已经有账户？", "Already have an account?") : t("还没有账户？", "New here?")}{" "}
        <button type="button" onClick={() => switchMode(registering ? "sign-in" : "register")}>
          {registering ? t("去登录", "Sign in") : t("创建账户", "Create an account")}
        </button>
      </p>
      {shortcut && <p className="login-switch">
        <button type="button" disabled={busy} onClick={() => void quickSignIn()}>{t("本地开发：免密码登录", "Local development: continue without a password")}</button>
      </p>}
    </section>
  );
}
