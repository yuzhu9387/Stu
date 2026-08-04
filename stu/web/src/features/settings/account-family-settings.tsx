"use client";

import { useState } from "react";

import { useLocale } from "@/i18n/locale-context";
import { api } from "@/lib/api";
import { useFeatureData } from "@/lib/use-feature-data";

interface Preference { id: string; label: string; owner_display_name: string; is_owned_by_current_account: boolean }
interface Member { owner_account_id: string; owner_display_name: string; email: string; role: string; is_owned_by_current_account: boolean }
interface SettingsData {
  preferences: Preference[];
  members: Member[];
  lark_binding: { is_linked: boolean };
}

export function AccountFamilySettings() {
  const { catalog, locale } = useLocale();
  const state = useFeatureData<SettingsData>("/api/v1/settings");
  const [inviteCode, setInviteCode] = useState<string | null>(null);
  const [larkCode, setLarkCode] = useState<string | null>(null);
  const [joinCode, setJoinCode] = useState("");
  const [joined, setJoined] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chinese = locale === "zh-CN";

  async function invite() {
    setError(null);
    try {
      const result = await api<{ code: string }>("/api/v1/families/invites", { method: "POST" });
      setInviteCode(result.code);
    } catch { setError(chinese ? "无法创建邀请码。" : "Could not create invite."); }
  }

  async function linkLark() {
    setError(null);
    try {
      const result = await api<{ code: string }>("/api/v1/auth/lark-link-codes", { method: "POST" });
      setLarkCode(result.code);
    } catch { setError(chinese ? "无法创建绑定码。" : "Could not create link code."); }
  }

  async function joinFamily() {
    setError(null);
    try {
      await api("/api/v1/families/invites/accept", { method: "POST", body: JSON.stringify({ code: joinCode }) });
      setJoined(true);
    } catch { setError(chinese ? "无法加入家庭，请检查邀请码。" : "Could not join family. Check the code."); }
  }

  return (
    <section className="feature-screen">
      <header className="feature-header"><div>
        <p className="eyebrow">{catalog.pages.settings.eyebrow}</p>
        <h1>{catalog.pages.settings.title}</h1>
        <p className="feature-description">{catalog.pages.settings.body}</p>
      </div></header>
      <div className="settings-actions">
        <button className="primary-button" type="button" onClick={() => void invite()}>{chinese ? "创建家庭邀请码" : "Create family invite"}</button>
        <button className="primary-button" type="button" onClick={() => void linkLark()}>{chinese ? "绑定 Lark" : "Link Lark"}</button>
      </div>
      <div className="join-family-form">
        <label htmlFor="family-code">{chinese ? "输入家庭邀请码" : "Enter family invite code"}</label>
        <input id="family-code" value={joinCode} onChange={(event) => setJoinCode(event.target.value)} />
        <button className="primary-button" type="button" disabled={!joinCode.trim()} onClick={() => void joinFamily()}>{chinese ? "加入家庭" : "Join family"}</button>
      </div>
      {inviteCode ? <p className="code-delivery" role="status">{chinese ? "家庭邀请码" : "Family invite"}: <strong>{inviteCode}</strong></p> : null}
      {larkCode ? <p className="code-delivery" role="status">{chinese ? "在 Lark 中发送" : "Send in Lark"}: <strong>link {larkCode}</strong></p> : null}
      {joined ? <p className="code-delivery" role="status">{chinese ? "已加入家庭，账户数据仍保持独立。" : "Family joined. Your account data remains separate."}</p> : null}
      {error ? <p role="alert" className="chat-error">{error}</p> : null}
      {state.status === "loading" ? <p className="empty-state">{chinese ? "正在加载…" : "Loading…"}</p> : null}
      {state.status === "error" ? <p className="empty-state" role="alert">{chinese ? "无法读取设置。" : "Could not load settings."}</p> : null}
      {state.status === "ready" ? <>
        <div className="metric-strip"><span className="metric-dot" aria-hidden="true" />{state.data.lark_binding.is_linked ? (chinese ? "Lark 已绑定" : "Lark linked") : (chinese ? "Lark 未绑定" : "Lark not linked")}</div>
        <div className="record-grid">
          {state.data.members.map((member) => <article className="record-card" key={member.owner_account_id}>
            <span className="record-index" aria-hidden="true">●</span><div><h2>{member.owner_display_name}</h2><p>{member.email}</p></div>
            <small>{member.role} · {member.is_owned_by_current_account ? (chinese ? "我的账户" : "My account") : (chinese ? "家庭成员" : "Family member")}</small>
          </article>)}
          {state.data.preferences.map((preference) => <article className="record-card" key={preference.id}>
            <span className="record-index" aria-hidden="true">◇</span><div><h2>{preference.label}</h2><p>{chinese ? "饮食偏好" : "Dietary preference"}</p></div>
            <small>{chinese ? "所有者" : "Owner"}: {preference.is_owned_by_current_account ? (chinese ? "我" : "Me") : preference.owner_display_name}</small>
          </article>)}
        </div>
      </> : null}
    </section>
  );
}
