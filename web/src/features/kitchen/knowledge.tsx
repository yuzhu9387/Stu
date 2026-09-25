"use client";

import { useRef, useState } from "react";
import type { KnowledgeDocument, PageProps } from "./types";
import "./knowledge.css";

const blankDocument = (): KnowledgeDocument => ({
  id: crypto.randomUUID(), title: "", content: "", category: "Nutrition",
  enabled: true, version: 1, updatedAt: new Date().toISOString(),
});

export function KnowledgePage({ state, send }: PageProps) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [editing, setEditing] = useState<KnowledgeDocument | null>(null);
  const [preview, setPreview] = useState(false);
  const [discard, setDiscard] = useState(false);
  const [removeId, setRemoveId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingEnabled, setPendingEnabled] = useState<Record<string, boolean>>({});
  const fileInput = useRef<HTMLInputElement>(null);
  const documents = state.knowledgeDocuments || [];
  const categories = [...new Set(documents.map(document => document.category))].sort();
  const needle = query.trim().toLocaleLowerCase();
  const filtered = documents.filter(document => (!category || document.category === category) &&
    `${document.title}\n${document.content}\n${document.category}\n${document.sourceUrl || ""}`.toLocaleLowerCase().includes(needle));

  function open(document: KnowledgeDocument, importing = false) {
    setEditing({ ...document }); setPreview(importing); setDiscard(false); setError("");
  }
  async function command(type: string, payload: Record<string, unknown>) {
    setBusy(true); setError("");
    try { return await send(type, payload); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to save. Try again."); return false; }
    finally { setBusy(false); }
  }
  async function toggleEnabled(document: KnowledgeDocument, enabled: boolean) {
    setPendingEnabled(current => ({ ...current, [document.id]: enabled }));
    const saved = await command("knowledge.save", { document: { ...document, enabled } });
    if (!saved) setError(current => current || "Unable to update this document. Its previous status has been restored.");
    setPendingEnabled(current => { const next = { ...current }; delete next[document.id]; return next; });
  }
  async function importFile(file: File) {
    setError("");
    if (!/\.(txt|md)$/i.test(file.name)) { setError("Choose a .txt or .md file. PDF import is not supported."); return; }
    if (file.size > 400000) { setError("Keep the file under 400 KB and 100,000 characters."); return; }
    setBusy(true);
    try {
      const content = await file.text();
      if (!content.trim() || content.length > 100000 || content.includes("\u0000")) throw new Error("Use a nonempty text document of up to 100,000 characters.");
      open({ ...blankDocument(), title: file.name.replace(/\.(txt|md)$/i, "").slice(0, 200), content }, true);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to read this file."); }
    finally { setBusy(false); }
  }
  return <section className="kw-support-page kw-knowledge-page">
    <header className="kw-page-header"><div><h1>Your reference library</h1><p className="kw-muted">Keep nutrition and meal-planning documents together. Enabled documents are included when AI plans or adjusts meals.</p></div>
      <div className="kw-support-actions"><button className="kw-button" disabled={busy || !!editing} onClick={() => fileInput.current?.click()}>Import .txt / .md</button><button className="kw-button kw-primary" disabled={busy || !!editing} onClick={() => open(blankDocument())}>Add document</button></div>
      <input ref={fileInput} className="kw-knowledge-file" type="file" aria-label="Import text or Markdown" accept=".txt,.md,text/plain,text/markdown" disabled={busy || !!editing} onChange={event => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void importFile(file); }} />
    </header>
    {error && <p className="kw-error" role="alert">{error}</p>}
    {editing && <form className="kw-card kw-support-editor" onSubmit={async event => {
      event.preventDefault();
      const document = { ...editing, title: editing.title.trim(), content: editing.content.trim(), category: editing.category.trim(), sourceUrl: editing.sourceUrl?.trim() || undefined };
      if (document.sourceUrl) { try { const source = new URL(document.sourceUrl); if (!["http:", "https:"].includes(source.protocol) || source.username || source.password) throw new Error(); } catch { setError("Source URL must use HTTP or HTTPS without credentials."); return; } }
      if (await command("knowledge.save", { document })) { setEditing(null); setPreview(false); }
    }}>
      <h2>{preview ? "Import preview" : documents.some(document => document.id === editing.id) ? "Edit document" : "New document"}</h2>
      {preview && <p className="kw-support-notice">Review and edit the imported text, then save it to your library.</p>}
      <div className="kw-form-grid"><label className="kw-label">Document title<input className="kw-input" autoFocus required maxLength={200} value={editing.title} onChange={event => setEditing({ ...editing, title: event.target.value })} /></label>
        <label className="kw-label">Category<input className="kw-input" required maxLength={100} list="knowledge-categories" value={editing.category} onChange={event => setEditing({ ...editing, category: event.target.value })} /><datalist id="knowledge-categories">{categories.map(value => <option key={value} value={value} />)}</datalist></label></div>
      <label className="kw-label">Source URL (optional)<input className="kw-input" type="url" maxLength={2000} placeholder="https://…" value={editing.sourceUrl || ""} onChange={event => setEditing({ ...editing, sourceUrl: event.target.value })} /></label>
      <label className="kw-label">Document content<textarea className="kw-input" required rows={12} maxLength={100000} value={editing.content} onChange={event => setEditing({ ...editing, content: event.target.value })} /></label>
      <label className="kw-support-toggle"><input type="checkbox" checked={editing.enabled} onChange={event => setEditing({ ...editing, enabled: event.target.checked })} />Use in future planning</label>
      <div className="kw-support-actions"><button className="kw-button kw-primary" disabled={busy || !editing.title.trim() || !editing.content.trim() || !editing.category.trim()}>Save document</button><button className="kw-button" type="button" disabled={busy} onClick={() => setDiscard(true)}>Cancel</button></div>
      {discard && <div className="kw-support-notice" role="alert"><p>Discard this unsaved document edit?</p><div className="kw-support-actions"><button type="button" className="kw-button" onClick={() => { setEditing(null); setDiscard(false); }}>Discard edit</button><button type="button" className="kw-button" onClick={() => setDiscard(false)}>Keep editing</button></div></div>}
    </form>}
    <div className="kw-support-toolbar"><label className="kw-label">Search documents<input className="kw-input" type="search" placeholder="Search titles, content or sources" value={query} onChange={event => setQuery(event.target.value)} /></label><label className="kw-label">Filter category<select className="kw-input" value={category} onChange={event => setCategory(event.target.value)}><option value="">All categories</option>{categories.map(value => <option key={value}>{value}</option>)}</select></label></div>
    <p className="kw-muted">{documents.filter(document => pendingEnabled[document.id] ?? document.enabled).length} of {documents.length} documents enabled. Saved plans keep the document versions used to create them.</p>
    <div className="kw-knowledge-list">{filtered.map(document => <article className="kw-card kw-support-task" key={document.id}>
      <div className="kw-row"><div><span className="kw-pill">{document.category}</span><h2>{document.title}</h2></div><label className="kw-support-toggle"><input type="checkbox" aria-label={`Enable ${document.title}`} checked={pendingEnabled[document.id] ?? document.enabled} disabled={busy || !!editing} onChange={event => void toggleEnabled(document, event.target.checked)} /><span aria-live="polite">{pendingEnabled[document.id] !== undefined ? "Saving…" : "Enabled"}</span></label></div>
      <p className="kw-knowledge-excerpt">{document.content.slice(0, 220)}{document.content.length > 220 ? "…" : ""}</p>
      <details className="kw-support-details"><summary>Read document</summary><div className="kw-knowledge-content">{document.content}</div></details>
      {document.sourceUrl && <a className="kw-knowledge-source" href={document.sourceUrl} target="_blank" rel="noreferrer">Source: {document.sourceUrl}</a>}
      <div className="kw-support-actions"><span className="kw-muted">Version {document.version}</span><time className="kw-muted" dateTime={document.updatedAt}>Updated {new Date(document.updatedAt).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })}</time><button className="kw-button" aria-label={`Edit ${document.title}`} disabled={busy || !!editing} onClick={() => open(document)}>Edit</button><button className="kw-button" aria-label={`Delete ${document.title}`} disabled={busy || !!editing} onClick={() => setRemoveId(document.id)}>Delete</button></div>
      {removeId === document.id && <div className="kw-support-notice"><p>Delete this document? Existing plan snapshots will be kept.</p><div className="kw-support-actions"><button className="kw-button" disabled={busy} onClick={async () => { if (await command("knowledge.delete", { id: document.id })) setRemoveId(null); }}>Confirm delete</button><button className="kw-button" onClick={() => setRemoveId(null)}>Cancel</button></div></div>}
    </article>)}</div>
    {!filtered.length && <div className="kw-empty"><h2>{documents.length ? "No matching documents" : "Build your nutrition library"}</h2><p>{documents.length ? "Try another search or category." : "Add your own references or import a text or Markdown file. Chinese and English content are supported."}</p></div>}
  </section>;
}
