"use client";
import { useEffect, useState } from "react";
import { api, apiUrl } from "@/lib/api";

interface AccessToken { id: string; name: string; createdAt: string; lastUsedAt: string | null }
const when = (value: string | null) => value ? new Date(value).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "Never";

/** Personal access tokens for AI clients (MCP). A token acts for this account
 * in its household — read everything, run every kitchen command — and is shown
 * once; revoking it cuts the client off at once. */
export function McpAccess({ demo }: { demo: boolean }) {
  const [tokens, setTokens] = useState<AccessToken[] | null>(null);
  const [name, setName] = useState("Claude");
  const [fresh, setFresh] = useState<{ name: string; token: string } | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const endpoint = apiUrl("/api/v1/kitchen/mcp");

  useEffect(() => {
    if (demo) return;
    let live = true;
    api<{ tokens: AccessToken[] }>("/api/v1/auth/mcp-tokens")
      .then(result => { if (live) setTokens(result.tokens); })
      .catch(() => { if (live) setError("Unable to load access tokens."); });
    return () => { live = false; };
  }, [demo]);

  async function create() {
    if (!name.trim() || busy) return;
    setBusy(true); setError(null);
    try {
      const made = await api<AccessToken & { token: string }>("/api/v1/auth/mcp-tokens", { method: "POST", body: JSON.stringify({ name: name.trim() }) });
      setFresh({ name: made.name, token: made.token });
      setTokens(current => [...(current ?? []), { id: made.id, name: made.name, createdAt: made.createdAt, lastUsedAt: null }]);
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to create a token."); }
    finally { setBusy(false); }
  }

  async function revoke(id: string) {
    setBusy(true); setError(null);
    try {
      await api<void>(`/api/v1/auth/mcp-tokens/${id}`, { method: "DELETE" });
      setTokens(current => (current ?? []).filter(t => t.id !== id));
      setRevoking(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to revoke the token."); }
    finally { setBusy(false); }
  }

  function copy(label: string, text: string) {
    void navigator.clipboard?.writeText(text).then(() => { setCopied(label); window.setTimeout(() => setCopied(null), 1500); });
  }

  const command = fresh ? `claude mcp add --transport http stu ${endpoint} --header "Authorization: Bearer ${fresh.token}"` : "";
  return <section className="kw-card kw-mcp-access" id="ai-access" aria-label="AI access">
    <h2>AI Access 🔌</h2>
    <p className="kw-muted">Let an AI assistant (an MCP client such as Claude) work in your kitchen: it can read everything and make any change you can — recipes, fridge, plans, prep, settings. Each token acts as you; revoke it to cut the assistant off.</p>
    {demo ? <p className="kw-muted">Access tokens are for your own account; the demo has none.</p> : <>
      <form className="kw-mcp-create" onSubmit={e => { e.preventDefault(); void create(); }}>
        <label className="kw-label">Token name<input className="kw-input" maxLength={80} value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Claude on my laptop" /></label>
        <button className="kw-button kw-yellow" disabled={busy || !name.trim()}>+ New access token</button>
      </form>
      {fresh && <div className="kw-mcp-fresh" role="status">
        <p><strong>{fresh.name}</strong>: copy it now — it will not be shown again.</p>
        <div className="kw-mcp-secret"><code>{fresh.token}</code><button type="button" className="kw-button secondary" onClick={() => copy("token", fresh.token)}>{copied === "token" ? "Copied ✓" : "Copy"}</button></div>
        <p className="kw-muted">Server: <code>{endpoint}</code> · header <code>Authorization: Bearer …</code></p>
        <p className="kw-muted">Claude Code:</p>
        <div className="kw-mcp-secret"><code>{command}</code><button type="button" className="kw-button secondary" onClick={() => copy("command", command)}>{copied === "command" ? "Copied ✓" : "Copy"}</button></div>
        <button type="button" className="kw-link-button" onClick={() => setFresh(null)}>Done</button>
      </div>}
      {error && <p className="kw-inline-error" role="alert">{error}</p>}
      {tokens && (tokens.length ? <ul className="kw-mcp-list">{tokens.map(t => <li key={t.id}>
        <span><strong>{t.name}</strong><small>Created {when(t.createdAt)} · Last used {when(t.lastUsedAt)}</small></span>
        {revoking === t.id
          ? <span className="kw-mcp-confirm">Revoke this token?<button type="button" className="kw-tag-option danger" disabled={busy} onClick={() => void revoke(t.id)}>Revoke</button><button type="button" className="kw-tag-option" onClick={() => setRevoking(null)}>Cancel</button></span>
          : <button type="button" className="kw-tag-option danger" aria-label={`Revoke ${t.name}`} onClick={() => setRevoking(t.id)}>Revoke</button>}
      </li>)}</ul> : <p className="kw-muted">No access tokens yet.</p>)}
    </>}
  </section>;
}
