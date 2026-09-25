"use client";
import { ArrowUp, X } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { api } from "@/lib/api";
import { dayLabel, slots, weekDays, weekLabel } from "./data";
import { ANALYSIS_METRICS, planMetrics, type MetricResult, type PlanWarning } from "./analysis";
import { planRuleWarnings } from "./plan-rules";
import type { ChatTurn } from "./ai-tasks";
import { useStored } from "./browser-store";
import { takeChatFocus } from "./chat-refs";
import { prepSchedule } from "./schedule";
import { slotKey, useChosenPlan, type SetupChoices } from "./slot-choices";
import type { ChatProposal, KitchenState, Meal, WeeklyPlan } from "./types";

/** Frame 47:9's prompt shortcuts. They only fill the prompt the generator
 * already reads — nothing hidden is sent. */
const QUICK_PROMPTS = [
  { label: "Auto-generate this week", icon: "✨", apply: "", edit: { label: "Rebuild the whole week", apply: "Rebuild the whole week." } },
  { label: "Based on last week", icon: "📊", apply: "Build on what we actually cooked last week." },
  { label: "Prioritize fridge items", icon: "🧊", apply: "Use what is already in the fridge before buying anything." },
];
const shortDayFormat = new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: "UTC" });
const shortDay = (day: string) => shortDayFormat.format(new Date(`${day}T12:00:00Z`));
const failure = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);
const slotName = (slot: string) => slot[0].toUpperCase() + slot.slice(1);
/** Shift+Enter (or ⌘/Ctrl+Enter) sends; plain Enter is a new line. An IME
 * composition's Enter is left alone. */
const sendKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => e.key === "Enter" && (e.shiftKey || e.metaKey || e.ctrlKey) && !e.nativeEvent.isComposing;
const chineseDayFormat = new Intl.DateTimeFormat("zh-CN", { weekday: "short", timeZone: "UTC" });
const chineseDay = (day: string) => chineseDayFormat.format(new Date(`${day}T12:00:00Z`));

/** A message keeps the meal references it was sent with, independently of the
 * composer's selection for the next turn. */
function MessageMealTags({ ids = [], meals }: { ids?: string[]; meals: Meal[] }) {
  const referenced = [...new Set(ids)].flatMap(id => { const meal = meals.find(m => m.id === id); return meal ? [meal] : []; });
  if (!referenced.length) return null;
  return <span className="kw-message-meals" role="group" aria-label="Referenced meals">{referenced.map(meal => <span className="kw-context" key={meal.id}>{dayLabel(meal.day)} · {slotName(meal.slot)}</span>)}</span>;
}

type Stage = "setup" | "adjust" | "confirmed" | "shopping";

/** Seconds since `start`, ticking once a second while it is set. Read from a
 * subscribed clock so the server renders nothing time-dependent. */
function useElapsed(start: number | null) {
  const now = useSyncExternalStore(
    onChange => { if (start === null) return () => {}; const timer = window.setInterval(onChange, 1000); return () => window.clearInterval(timer); },
    () => (start === null ? 0 : Math.floor(Date.now() / 1000)),
    () => 0,
  );
  return start === null ? 0 : Math.max(0, now - Math.floor(start / 1000));
}
const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
type Step = "preferences" | "adjust" | "confirmed" | "shopping";

/** A stable four-step journey: unavailable steps remain visible. */
function StepRail({ stage, hasDraft, editing, busy, blocked, stamping, onStep, onConfirm, onEdit, onCalendar }: { onCalendar?: () => void; stage: Stage; hasDraft: boolean; editing: boolean; busy: boolean; blocked: boolean; stamping: boolean; onStep: (step: Step) => void | Promise<void>; onConfirm: () => void; onEdit: () => void }) {
  const settled = stage === "confirmed" || stage === "shopping";
  const segments = [
    { n: "1", label: "Meals & preferences", active: stage === "setup", done: settled, action: !settled && hasDraft && stage !== "setup" ? () => onStep("preferences") : undefined, aria: "Back to step 1, meals and preferences" },
    { n: "2", label: settled ? "Review plan" : "Adjust plan", active: stage === "adjust", done: settled, action: settled ? () => onStep("confirmed") : hasDraft && stage !== "adjust" ? () => onStep("adjust") : undefined, aria: settled ? "Review confirmed plan" : "Go to step 2, adjust" },
    { n: settled ? "✎" : "✓", label: settled ? "Edit plan" : editing ? "Save changes" : "Confirm", active: false, done: settled, action: settled ? onEdit : (stage === "adjust" || editing) ? onConfirm : undefined, aria: settled ? "Edit plan" : "Confirm plan" },
    { n: "4", label: "Shopping & prep", active: stage === "shopping", done: false, action: settled && stage !== "shopping" ? () => onStep("shopping") : undefined, aria: "Open shopping and prep" },
  ];
  return <div className="kw-journey"><ol className={`kw-stepper ${stamping ? "is-stamping" : ""}`} aria-label="Planning steps">{segments.map((segment, index) => {
    const kind = segment.active ? "current" : index === 2 && segment.action ? "action" : segment.action ? "link" : segment.done ? "done" : "disabled";
    const disabled = busy || index === 2 && blocked;
    if (index === 2) return <li key={index} className={`kw-state-transition is-${kind}`}><button type="button" aria-label={segment.aria} disabled={disabled || !segment.action} onClick={() => { void Promise.resolve(segment.action?.()).catch(() => {}); }}><span aria-hidden="true">{segment.n}</span></button><span className="kw-transition-label">{segment.label}</span></li>;
    const body = <><span className="kw-stepper-n" aria-hidden="true">{segment.n}</span><span className="kw-step-label">{segment.label}</span><span className="kw-step-short">{index === 0 ? "Meals" : index === 1 ? "Plan" : "Prep"}</span></>;
    return <li key={index} className={`is-${kind}`} aria-current={segment.active ? "step" : undefined}>{segment.action ? <button type="button" aria-label={segment.aria} disabled={disabled} onClick={() => { void Promise.resolve(segment.action?.()).catch(() => {}); }}>{body}</button> : <span className="kw-stepper-static">{body}</span>}</li>;
  })}</ol>{onCalendar && <button className="kw-view-calendar" onClick={onCalendar}>View calendar <span aria-hidden="true">→</span></button>}</div>;
}

interface Props {
  week: string; state: KitchenState; plan: WeeklyPlan | null; choices: SetupChoices; step: string | null;
  onStep: (step: Step) => void | Promise<void>; onSlot: (day: string, slot: string, included: boolean) => void;
  /** These throw on failure; the page says what went wrong where it happened. */
  onGoal: (id: string, enabled: boolean) => Promise<void>; onSavePreferences: (prompt: string) => Promise<number>;
  onGenerate: (prompt: string) => Promise<string | null>; onApplyFix: (meal: Meal) => Promise<void>;
  /** When the week's draft started, while Stu is drafting it (even after a refresh). */
  confirmingSince?:number|null; fulfillmentError?:string|null;
  generatingSince?: number | null; generationError?: string | null; onDismissGenerationError?: () => void;
  onPlanMyself?: () => Promise<void>;
  selected: string[]; onSelect: (ids: string[]) => void;
  /** Stu's latest chat turn: running, or done with a suggestion or a question. */
  turn?: ChatTurn | null;
  onChat: (text: string, answering: boolean) => Promise<void>; onApply: () => Promise<void>; onKeep?: () => Promise<void>;
  onConfirm: () => Promise<string | null>; onEdit: () => Promise<void>; focusTick: number; onPrep: () => void; onGuidance: () => void; onWeek: (delta: number) => void;
  shoppingContent?: ReactNode; onCalendar?: () => void;
  children: ReactNode; demo: boolean; busy: boolean;
}

export function PlanningPage({ week, state, plan, choices, step, onStep, onSlot, onGoal, onSavePreferences, onGenerate, confirmingSince = null, fulfillmentError = null, generatingSince = null, generationError = null, onDismissGenerationError, onPlanMyself, onApplyFix, selected, onSelect, turn = null, onChat, onApply, onKeep, onConfirm, onEdit, focusTick, onPrep, onGuidance, onWeek, onCalendar, shoppingContent, children, demo, busy }: Props) {
  const confirmationElapsed = useElapsed(confirmingSince);
  const [confirmPosting,setConfirmPosting] = useState(false);
  const [applying, setApplying] = useState<string | null>(null);
  // Editing a confirmed week: step 1's box asks Stu for a change instead of
  // generating a new week, so it starts empty.
  const editing = plan?.status === "draft" && !!plan.basePlanId;
  const [prompt, setPrompt] = useState(editing ? "" : state.weeklyPrompts?.find(item => item.weekStart === week)?.prompt ?? plan?.prompt ?? "");
  const [storedMessage, writeMessage] = useStored("session", `stu-composer:${demo?"demo":"live"}:${plan?.id??week}`);
  const message = storedMessage ?? "";
  const setMessage = (value: string) => writeMessage(value || null);
  const [posting, setPosting] = useState(false);
  // The message on its way to Stu, shown until the conversation has it.
  const [pending, setPending] = useState<{ text: string; mealIds: string[] } | null>(null), [applyingProposal, setApplyingProposal] = useState(false);
  // Stu answers on the server: the turn says whether Stu is still at it, and
  // holds the suggestion (or question) until it is applied, kept or superseded.
  const waiting = posting || turn?.status === "running";
  const proposal = turn?.status === "done" && turn.resolution === "open" ? turn.result : null;
  const [chatError, setChatError] = useState<string | null>(null), [setupError, setSetupError] = useState<string | null>(null);
  const [fixError, setFixError] = useState<string | null>(null), [editError, setEditError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false), [saved, setSaved] = useState<number | null>(null);
  // A ticked goal shows at once; the setting follows a moment later.
  const [pendingGoals, setPendingGoals] = useState<Record<string, boolean>>({});
  const [confirmError, setConfirmError] = useState<string | null>(null), [stamping, setStamping] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const generating = generatingSince !== null;
  const elapsed = useElapsed(generatingSince);
  // What the analysis said just before a change was applied, so the next
  // render can say which concerns that change settled.
  const [baseline, setBaseline] = useState<MetricResult[] | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null), chatBox = useRef<HTMLElement>(null), history = useRef<HTMLDivElement>(null), jumpToChat = useRef(false);
  // The conversation opens on, and follows, its newest message.
  const chatLength = plan?.chat.length ?? 0, onAdjust = !!plan && plan.status !== "confirmed" && step !== "preferences";
  useEffect(() => {
    const frame = window.requestAnimationFrame(() => { const el = history.current; if (el) el.scrollTop = el.scrollHeight; });
    return () => window.cancelAnimationFrame(frame);
  }, [chatLength, pending, waiting, onAdjust]);
  // Only an explicit "Reference in chat" moves the page to the chat. A ⌘-click
  // that adds a reference leaves the page where it is.
  useEffect(() => { if (takeChatFocus()) { composer.current?.focus(); composer.current?.scrollIntoView?.({ block: "center" }); } }, [focusTick]);

  // The step lives in the URL, so each step has its own address. The plan's
  // own state still wins: without a draft there is only step 1, and a
  // confirmed week is step 3 whatever the address says.
  const stage: Stage = !plan ? "setup" : plan.status === "confirmed" ? step === "shopping" ? "shopping" : "confirmed" : step === "preferences" ? "setup" : "adjust";
  // A request typed in step 1 while editing continues in the chat on Adjust.
  useEffect(() => {
    if (stage !== "adjust" || !jumpToChat.current) return;
    jumpToChat.current = false;
    const timer = window.setTimeout(() => chatBox.current?.scrollIntoView?.({ block: "start", behavior: "smooth" }), 60);
    return () => window.clearTimeout(timer);
  }, [stage]);
  const view = useChosenPlan(plan, choices);
  const metrics = useMemo(() => view ? planMetrics(state, view) : [], [state, view]);
  const ruleWarnings = useMemo(() => view ? planRuleWarnings(state, view) : [], [state, view]);
  const prepTiming = useMemo(() => {
    try { return plan ? prepSchedule(state, plan) : null; } catch { return null; /* shown as "needs review" */ }
  }, [state, plan]);

  /** Sends one message. If Stu's last answer was a question, this is the
   * answer to it — Stu then acts rather than asking again. */
  async function ask(text: string) {
    const value = text.trim(); if (!value || waiting) return;
    const answering = proposal?.needsClarification === true;
    setPosting(true); setPending({ text: value, mealIds: [...selected] }); setChatError(null);
    try { await onChat(value, answering); setMessage(""); }
    catch (e) { setChatError(failure(e, "Stu couldn’t answer just now. Your meals are unchanged.")); setMessage(value); }
    finally { setPosting(false); setPending(null); }
  }
  async function keep() { setChatError(null); try { await onKeep?.(); } catch (e) { setChatError(failure(e, "Unable to keep the current meals.")); } }
  async function planMyself() { setSetupError(null); try { await onPlanMyself?.(); } catch (e) { setSetupError(failure(e, "Unable to start an empty week.")); } }
  async function goToStep(step: Step) {
    try { await onStep(step); } catch (e) { const message = failure(e, "Unable to save planning progress."); setSetupError(message); setConfirmError(message); }
  }
  async function askFromSetup() {
    const text = prompt.trim(); if (!text) return;
    try { await onStep("adjust"); jumpToChat.current = true; setPrompt(""); void ask(text); } catch (e) { setSetupError(failure(e, "Unable to open the plan.")); }
  }
  async function applyProposal() {
    setChatError(null); setBaseline(metrics); setApplyingProposal(true);
    try { await onApply(); }
    catch (e) { setBaseline(null); setChatError(failure(e, "Unable to apply these changes.")); }
    finally { setApplyingProposal(false); }
  }
  async function toggleGoal(id: string, enabled: boolean) {
    setPendingGoals(current => ({ ...current, [id]: enabled })); setSetupError(null);
    try { await onGoal(id, enabled); } catch (e) { setSetupError(failure(e, "Unable to save this goal.")); } finally { setPendingGoals(current => { const next = { ...current }; delete next[id]; return next; }); }
  }
  async function edit() { setEditError(null); try { await onEdit(); } catch (e) { setEditError(failure(e, "Unable to start editing this plan.")); } }
  async function confirm() {
    if(confirmPosting || confirmingSince !== null)return;
    setConfirmError(null);setConfirmPosting(true);
    try { const error = await onConfirm(); if(error)setConfirmError(error); }
    catch(error){setConfirmError(failure(error,"Unable to confirm. Please try again."));}
    finally{setConfirmPosting(false);}
  }
  const previousStatus=useRef(plan?.status);
  useEffect(()=>{if(previousStatus.current==="draft"&&plan?.status==="confirmed"){const start=window.setTimeout(()=>setStamping(true),0),end=window.setTimeout(()=>setStamping(false),1800);previousStatus.current=plan?.status;return()=>{window.clearTimeout(start);window.clearTimeout(end);};}previousStatus.current=plan?.status;},[plan?.status]);
  async function generate() {
    setGenerateError(null);
    const error = await onGenerate(prompt);
    if (error) setGenerateError(error);
  }
  // A failed draft is said once, in place, until dismissed or retried.
  const draftError = generateError ?? generationError;
  // Stu's failed turn is said in the chat, like a message that could not be sent.
  const turnError = turn?.status === "failed" && turn.resolution === "open" ? turn.error : null;
  async function applyFix(id: string, mealId: string, component: Meal["components"][number]) {
    const target = plan?.meals.find(m => m.id === mealId); if (!target) return;
    setBaseline(metrics); setApplying(id); setFixError(null);
    try { await onApplyFix({ ...target, components: [...target.components, component] }); }
    catch (e) { setBaseline(null); setFixError(failure(e, "Unable to apply this fix.")); }
    finally { setApplying(null); }
  }
  async function save() { setSaving(true); setSetupError(null); try { setSaved(await onSavePreferences(prompt)); } catch (e) { setSetupError(failure(e, "Unable to save preferences.")); } finally { setSaving(false); } }

  return <div className={`kw-planning is-${stage}`}>
    <header className="kw-planning-heading">
      <h1 aria-label="Plan">Weekly Plan 🍽️</h1>
      <div className="kw-weekbar"><button className="kw-week-step" aria-label="Previous week" onClick={() => onWeek(-1)}><span aria-hidden="true">◀</span></button><span className="kw-week-label">{weekLabel(week)}</span><button className="kw-week-step" aria-label="Next week" onClick={() => onWeek(1)}><span aria-hidden="true">▶</span></button></div>
      {plan && <span className="kw-stamp-slot">{stamping && <span className="kw-plan-stamp draft is-leaving" aria-hidden="true">DRAFT</span>}<span className={`kw-plan-stamp ${plan.status} ${stamping ? "is-stamping" : ""}`}>{plan.status === "draft" ? (plan.basePlanId ? "EDITING" : "DRAFT") : "CONFIRMED"}</span></span>}
    </header>
    <StepRail onCalendar={plan ? onCalendar : undefined} stage={stage} hasDraft={plan?.status === "draft"} editing={editing} busy={busy || waiting || confirmPosting || confirmingSince !== null} blocked={false} stamping={stamping} onStep={goToStep} onConfirm={() => void confirm()} onEdit={() => void edit()} />
    {generating && stage !== "setup" && <div className="kw-panel" role="status">Stu is drafting your week… {clock(elapsed)}</div>}
    {(confirmPosting || confirmingSince !== null) && <div className="kw-confirm-generating" role="status" aria-live="polite"><div className="kw-confirm-orbit" aria-hidden="true"><span>🧊</span><span>🛒</span><span>🥣</span></div><div><strong>{demo?"Preparing your demo week…":"Stu is preparing your week…"}</strong><span>Shopping cart + prep day · {clock(confirmationElapsed)}</span></div><div className="kw-confirm-progress" aria-hidden="true" /></div>}
    {stage !== "confirmed" && (confirmError || fulfillmentError) && <div className="kw-confirm-block" role="alert"><strong>{editing ? "Can’t save yet" : "Can’t confirm yet"}</strong><p>{confirmError || fulfillmentError}</p><button className="kw-button secondary" disabled={confirmPosting || confirmingSince !== null} onClick={()=>void confirm()}>Try again</button></div>}
    {(stage === "confirmed" || stage === "shopping") && editError && <p className="kw-inline-error" role="alert">{editError}</p>}

    {stage === "setup" && <section className="kw-setup" aria-label="Plan setup">
      <h2 className="kw-setup-title">Choose meals</h2>
      <div className="kw-panel kw-week-picker">{weekDays(week).map(day => <div className="kw-week-col" key={day}>
        <h3>{shortDay(day)}<span>{chineseDay(day)}</span></h3>
        {slots.map(slot => {
          const meal = plan?.meals.find(m => m.day === day && m.slot === slot);
          const on = choices.slots[slotKey(day, slot)] ?? (meal ? meal.included !== false : true);
          return <label className="kw-check" key={slot}><input type="checkbox" checked={meal?.locked ? true : on} disabled={meal?.locked} aria-label={`Plan ${shortDay(day)} ${slot}`} onChange={e => onSlot(day, slot, e.target.checked)} /><span>{slot[0].toUpperCase() + slot.slice(1)}</span></label>;
        })}
      </div>)}</div>

      <div className="kw-setup-head">
        <h2 className="kw-setup-title">What’s in your mind this week?</h2>
        {(plan || onPlanMyself) && <button type="button" className="kw-link" onClick={() => (plan ? void goToStep("adjust") : void planMyself())}>or skip AI, I’ll plan myself ✍️ →</button>}
      </div>
      <div className="kw-setup-pair">
        <section className="kw-panel kw-goals" aria-label="Meal style presets">
          <h3>🎯 Meal Style Presets</h3>
          <div className="kw-goal-list">{state.settings.guidance.map(goal => {
            const on = pendingGoals[goal.id] ?? goal.enabled;
            return <label className="kw-check" key={goal.id}><input type="checkbox" checked={on} aria-label={`Use goal ${goal.title}`} onChange={e => void toggleGoal(goal.id, e.target.checked)} /><span>{goal.title}</span></label>;
          })}</div>
          <button type="button" className="kw-link" onClick={onGuidance}>Manage Goals →</button>
        </section>

        <section className="kw-panel kw-stu" aria-label="Plan with Stu">
          <h3>👨‍🍳 Plan with Stu</h3>
          <div className="kw-stu-box">
            {editing && (plan.chat.length > 0 || waiting) && <div className="kw-stu-latest" aria-label="Latest with Stu">
              {plan.chat.slice(-2).map(m => <div key={m.id}><p className={m.role}><span>{m.role === "user" ? "You" : "Stu"}</span>{m.text}</p>{m.role === "user" && <MessageMealTags ids={m.mealIds} meals={plan.meals} />}</div>)}
              {waiting ? <p className="assistant is-typing"><span>Stu</span><i /><i /><i /></p> : proposal && <button type="button" className="kw-link" onClick={() => void goToStep("adjust")}>{proposal.needsClarification ? "Answer Stu →" : "Review Stu’s suggestion →"}</button>}
            </div>}
            <textarea aria-label="This week’s preferences" value={prompt} onChange={e => { setPrompt(e.target.value); setSaved(null); }} onKeyDown={e => { if (editing && sendKey(e)) { e.preventDefault(); askFromSetup(); } }} placeholder={editing ? "What should change? e.g. Swap Wednesday dinner, fewer eggs this week…" : "Any preferences this week? e.g. More vegetables, try Korean food…"} />
            <div className="kw-quick-chips">{QUICK_PROMPTS.map(chip => { const use = editing && chip.edit ? chip.edit : chip; return <button key={chip.label} type="button" onClick={() => { setPrompt(use.apply); setSaved(null); }}><span aria-hidden="true">{chip.icon}</span>{use.label}</button>; })}</div>
            {generating && <div className="kw-stu-cooking" role="status"><span aria-hidden="true">🔍</span><p>Stu is cooking… <strong>{clock(elapsed)}</strong></p><progress /><small>Allow 2–7 minutes; complex weeks may take longer. You can refresh or visit another page. Stu keeps working and your result will appear here.</small></div>}
          </div>
          {draftError && <div className="kw-confirm-block" role="alert"><strong>Stu couldn’t finish this draft</strong><p>{draftError}</p>{onDismissGenerationError && <button type="button" className="kw-icon" aria-label="Dismiss" onClick={() => { setGenerateError(null); onDismissGenerationError(); }}>×</button>}</div>}
          {!editing&&!generating&&<p className="kw-muted small">Allow about 2–7 minutes for a full week. You can leave this page while Stu works.</p>}
          <div className="kw-stu-actions">
            {editing
              ? <button className="kw-cta" aria-label="Ask Stu to change this week" title="Shift+Enter" disabled={busy || waiting || saving || !prompt.trim()} onClick={askFromSetup}>Ask Stu →</button>
              : <button className="kw-cta" aria-label={plan ? "Generate another draft" : "Generate week"} disabled={busy || waiting || saving || plan?.status === "confirmed"} onClick={() => void generate()}>{busy && !saving ? "Working…" : "Generate Plan ✨"}</button>}
            <button className="kw-outline" disabled={busy || waiting || saving || saved !== null} onClick={() => void save()}>{saving ? "Saving…" : saved === null ? "Save weekly preferences" : saved > 0 ? `Saved ✓ · ${saved} added to goals` : "Saved ✓"}</button>
          </div>
          {setupError && <p className="kw-inline-error" role="alert">{setupError}</p>}
        </section>
      </div>
      {!demo && <GenerationStatus week={week} quiet />}
    </section>}

    {stage === "shopping" && shoppingContent}
    {stage !== "setup" && stage !== "shopping" && plan && <>
      {children}
      {stage === "confirmed" && <section className="kw-next-step" aria-label="Next step"><span className="kw-next-label">NEXT STEP 👇</span><button className="kw-cta" onClick={onPrep}>Shopping cart & Prep day →</button></section>}

      {stage === "adjust" && <>
      <section className="kw-chat" aria-label="Plan conversation" ref={chatBox}>
        <h2>👨‍🍳 Ask Stu to adjust</h2>
        {(plan.chat.length > 0 || pending || waiting) && <div className="kw-chat-history" aria-live="polite" ref={history}>
          {plan.chat.map(m => <div key={m.id} className={`kw-chat-message ${m.role}`}><span>{m.role === "user" ? "You" : "Stu"}</span>{m.role === "user" && <MessageMealTags ids={m.mealIds} meals={plan.meals} />}<p>{m.text}</p></div>)}
          {pending && <div className="kw-chat-message user is-pending"><span>You</span><MessageMealTags ids={pending.mealIds} meals={plan.meals} /><p>{pending.text}</p></div>}
          {waiting && <div className="kw-chat-message assistant is-typing"><span>Stu</span><p aria-label="Stu is thinking"><i /><i /><i /></p></div>}
        </div>}
        {waiting && <p className="kw-muted small" role="status">Stu is working in the background. A full-week rebuild can take 2–7 minutes. Refreshing or switching pages won’t interrupt this conversation.</p>}
        {proposal && !waiting && <ProposalCard plan={plan} proposal={proposal} disabled={busy || waiting || applyingProposal} applying={applyingProposal} onApply={() => void applyProposal()} onKeep={() => void keep()} onAnswer={option => void ask(option)} />}
        {(chatError ?? turnError) && <p className="kw-inline-error" role="alert">{chatError ?? turnError}</p>}
        <form className="kw-chat-composer" onSubmit={e => { e.preventDefault(); void ask(message); }}>
          {selected.length > 0 && <div className="kw-contexts">{selected.map(id => { const m = plan.meals.find(m => m.id === id); return m ? <span className="kw-context" key={id}>{dayLabel(m.day)} · {m.slot}<button type="button" className="kw-icon" aria-label={`Remove ${m.slot} reference`} onClick={() => onSelect(selected.filter(x => x !== id))}><X size={11} /></button></span> : null; })}</div>}
          <div className="kw-chat-input"><textarea ref={composer} aria-label="Ask Stu to adjust your plan" placeholder="The baby didn’t like broccoli. Replace Wednesday’s vegetable…" value={posting?"":message} onChange={e => setMessage(e.target.value)} disabled={posting} onKeyDown={e => { if (sendKey(e)) { e.preventDefault(); void ask(message); } }} rows={2} /><button className="kw-send" aria-label="Send plan request" title="Send · Shift+Enter" disabled={!message.trim() || busy || waiting}>{waiting ? "…" : <ArrowUp size={16} />}</button></div>
        </form>
      </section>

      {view && <Analysis plan={view} rules={ruleWarnings} proposedRules={proposal?.violations??[]} metrics={metrics} baseline={baseline} applying={applying} error={fixError} onGuidance={onGuidance} onApplyFix={applyFix} onDismiss={() => setBaseline(null)} />}

      <div className="kw-plan-foot">
        <details className="kw-reference" aria-label="Plan review summary">
          <summary>Details</summary>
          <p>Prep: {prepTiming ? `${prepTiming.activeMinutes} min active · ${prepTiming.ordinaryReadyMinutes} min elapsed` : "Timing needs review"} · limit {state.settings.maxPrepMinutes} min</p>
          <p>{weekDays(week).map(day => { const active = plan.meals.filter(m => m.day === day && m.status !== "skipped").reduce((sum, m) => sum + m.activeMinutes, 0); return `${dayLabel(day)} ${active}/${state.settings.maxDailyActiveMinutes} min`; }).join(" · ")}</p>
          <p>{["Protein", "Carbs", "Vegetables"].map(type => `${plan.meals.filter(m => m.components.some(c => c.type === type)).length} meals with ${type.toLowerCase()}`).join(" · ")}</p>
          <h3>How the analysis is counted</h3>
          {ANALYSIS_METRICS.filter(metric => (state.settings.analysisMetrics ?? ANALYSIS_METRICS.map(m => m.id)).includes(metric.id)).map(metric => <p key={metric.id}><strong>{metric.label}:</strong> {metric.rule}</p>)}
          {!!plan.guidanceSnapshot?.length && <><h3>Guidance used</h3>{plan.guidanceSnapshot.map(g => <details key={g.id}><summary>{g.title} · v{g.version}</summary><p>{g.content}</p></details>)}</>}
          {!!plan.knowledgeSnapshot?.length && <><h3>Knowledge documents used</h3>{plan.knowledgeSnapshot.map(document => <details key={document.id}><summary>{document.title} · v{document.version}</summary><p className="kw-support-prewrap">{document.content}</p>{document.sourceUrl && <a href={document.sourceUrl} target="_blank" rel="noreferrer">Source document</a>}</details>)}</>}
          {!demo && <GenerationStatus week={week} />}
        </details>
      </div>
      </>}
    </>}
  </div>;
}

/** Stu's answer as something to act on. A question comes with answers to tap.
 * Changes come as Now → After for each meal — dishes that go are struck
 * through, dishes that arrive are highlighted — and nothing changes until
 * Apply. Stu's words are already in the conversation above. */
function ProposalCard({ plan, proposal, disabled, applying, onApply, onKeep, onAnswer }: { plan: WeeklyPlan; proposal: ChatProposal; disabled: boolean; applying: boolean; onApply: () => void; onKeep: () => void; onAnswer: (option: string) => void }) {
  if (proposal.needsClarification) return proposal.options?.length
    ? <div className="kw-proposal is-question" role="group" aria-label="Answer Stu">{proposal.options.map(option => <button type="button" key={option} className="kw-option" disabled={disabled} onClick={() => onAnswer(option)}>{option}</button>)}</div>
    : null;
  if (!proposal.meals.length) return null;
  const prepChanges = (proposal.prep ?? []).filter(task => { const old = plan.prep.find(p => p.id === task.id); return !old || old.name !== task.name || old.plannedPortions !== task.plannedPortions; });
  const count = proposal.meals.length;
  return <div className="kw-proposal" role="group" aria-label="Proposed changes">
    <ul className="kw-diff-list">{proposal.meals.map(next => {
      const before = plan.meals.find(m => m.id === next.id);
      const was = new Set(before?.components.map(c => c.name) ?? []), now = new Set(next.components.map(c => c.name));
      const timeChanged = before && before.activeMinutes !== next.activeMinutes;
      return <li key={next.id} className="kw-diff">
        <h4>{dayLabel(next.day)} · {slotName(next.slot)}</h4>
        <div className="kw-diff-sides">
          <div className="kw-diff-side is-before"><span className="kw-diff-tag">Now</span>
            {before?.components.length ? <ul>{before.components.map(c => <li key={c.id} className={now.has(c.name) ? undefined : "is-removed"}>{now.has(c.name) ? c.name : <s>{c.name}</s>}</li>)}</ul> : <p className="kw-diff-empty">Empty</p>}
            <small>{before?.activeMinutes ?? 0} min</small>
          </div>
          <span className="kw-diff-arrow" aria-hidden="true">→</span>
          <div className="kw-diff-side is-after"><span className="kw-diff-tag">After</span>
            <ul>{next.components.map(c => <li key={c.id} className={was.has(c.name) ? undefined : "is-added"}>{c.name}</li>)}</ul>
            <small className={timeChanged ? "is-changed" : undefined}>{next.activeMinutes} min</small>
          </div>
        </div>
      </li>;
    })}</ul>
    {prepChanges.length > 0 && <p className="kw-diff-prep">Prep day also changes: {prepChanges.map(task => `${task.name} ×${task.plannedPortions}`).join(", ")}</p>}
    <div className="kw-row"><button className="kw-cta small" aria-label="Apply changes" disabled={disabled} onClick={onApply}>{applying ? "Applying…" : count === 1 ? "Apply change" : `Apply ${count} changes`}</button><button className="kw-outline small" onClick={onKeep}>Keep current</button></div>
  </div>;
}

/** Plan Analysis: one row per metric the household chose, each with its
 * number, whether it needs attention, and the issues under it — each issue with
 * up to three fixes to choose from. After a change is applied, a note says
 * which concerns it settled and which are still open. */
function Analysis({ plan, rules, proposedRules, metrics, baseline, applying, error, onApplyFix, onGuidance, onDismiss }: { plan: WeeklyPlan; rules: PlanWarning[]; proposedRules: {message:string}[]; metrics: MetricResult[]; baseline: MetricResult[] | null; applying: string | null; error: string | null; onApplyFix: (id: string, mealId: string, component: Meal["components"][number]) => Promise<void>; onGuidance: () => void; onDismiss: () => void }) {
  const empty = !plan.meals.some(m => (m.included ?? true) && m.status !== "skipped" && m.components.length);
  const outcome = baseline && !applying ? baseline.filter(before => before.status === "warn").map(before => {
    const now = metrics.find(m => m.id === before.id);
    const resolved = !now || now.status !== "warn";
    const headline = (value: string) => value.split(" · ")[0];
    return { id: before.id, label: before.label, resolved, from: headline(before.value), to: headline(now?.value ?? "") };
  }) : [];
  return <section className="kw-analysis" aria-label="Plan analysis">
    <header><h2>Plan Analysis 🧑‍🍳</h2><button type="button" className="kw-link" onClick={onGuidance}>Choose metrics →</button></header>
    {rules.length>0&&<div className="kw-rule-notices"><strong>Rules to review · these do not block your plan</strong><ul>{rules.map(rule=><li key={rule.id}><strong>{rule.title}</strong><p>{rule.detail}</p></li>)}</ul></div>}
    {proposedRules.length>0&&<div className="kw-rule-notices"><strong>Stu’s suggested changes · rules to review before applying</strong><ul>{proposedRules.map((rule,i)=><li key={i}>{rule.message}</li>)}</ul></div>}
    {error && <p className="kw-inline-error" role="alert">{error}</p>}
    {outcome.length > 0 && <div className="kw-analysis-outcome" role="status">
      <strong>After your change</strong>
      <ul>{outcome.map(item => <li key={item.id} className={item.resolved ? "is-resolved" : "is-open"}>{item.resolved ? `✓ ${item.label}: resolved` : `${item.label}: ${item.from === item.to ? "still open" : `${item.from} → ${item.to}`}`}</li>)}</ul>
      <button type="button" className="kw-icon" aria-label="Dismiss" onClick={onDismiss}>✕</button>
    </div>}
    {empty ? <p className="kw-analysis-empty">-</p> : !metrics.length ? <p className="kw-analysis-empty">No metrics selected.</p> : <dl className="kw-metrics">{metrics.map(metric => <div key={metric.id} className={`is-${metric.status}`}>
      <dt>{metric.label}</dt>
      <dd>
        <span className="kw-metric-value"><span className="kw-metric-mark" aria-hidden="true">{metric.status === "warn" ? "⚠️" : metric.status === "ok" ? "✓" : "·"}</span>{metric.value}</span>
        {metric.warnings.map(w => <div className="kw-metric-issue" key={w.id}><strong>{w.title}</strong><p>{w.detail}</p>
          {!!w.fixes?.length && <div className="kw-fix-options"><span>Suggested</span>{w.fixes.map(fix => { const key = `${w.id}:${fix.mealId}:${fix.component.recipeId}`; return <button type="button" key={key} className="kw-issue-fix" disabled={applying !== null} onClick={() => void onApplyFix(key, fix.mealId, fix.component)}>{applying === key ? "Applying…" : `Apply Fix · ${fix.label}`}</button>; })}</div>}
        </div>)}
      </dd>
    </div>)}</dl>}
  </section>;
}

interface GenerationJob { weekStart: string; status: string; attempts: number; error: string | null; nextAttemptAt: string | null }
/** Scheduled generation for the week. `quiet` shows it only when it needs the
 * household — a failure to retry — so a healthy week carries no status text. */
function GenerationStatus({ week, quiet = false }: { week: string; quiet?: boolean }) {
  const [job, setJob] = useState<GenerationJob | null>(null), [message, setMessage] = useState(""), [busy, setBusy] = useState(false);
  useEffect(() => { let active = true; api<{ jobs: GenerationJob[] }>("/api/v1/kitchen/generation-jobs").then(result => { if (active) setJob(result.jobs?.find(j => j.weekStart === week) ?? null); }).catch(error => { if (active) setMessage(error instanceof Error ? error.message : "Unable to load scheduled generation status."); }); return () => { active = false; }; }, [week]);
  async function retry() { setBusy(true); try { const result = await api<{ message: string; job: GenerationJob }>(`/api/v1/kitchen/generation-jobs/${week}/retry`, { method: "POST" }); setJob(result.job); setMessage(result.message); } catch (error) { setMessage(error instanceof Error ? error.message : "Unable to retry generation."); } finally { setBusy(false); } }
  const failing = !!job && ["failed", "retry"].includes(job.status);
  if (quiet && !failing && !message) return null;
  return <div className="kw-muted small" aria-live="polite">{job && <><p>Scheduled generation: {job.status} · {job.attempts} attempt{job.attempts === 1 ? "" : "s"}</p>{job.error && <p className="kw-error">{job.error}</p>}{job.nextAttemptAt && <p>Next attempt: {new Date(job.nextAttemptAt).toLocaleString()}</p>}{failing && <button className="kw-button secondary" disabled={busy} onClick={() => void retry()}>Retry scheduled generation</button>}</>}{message && <p>{message}</p>}</div>;
}
