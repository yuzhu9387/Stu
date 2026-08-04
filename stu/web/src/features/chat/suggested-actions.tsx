"use client";

import { useState } from "react";

import { api, ApiError, type ActionResult, type SuggestedActionReference } from "@/lib/api";
import type { Locale } from "@/i18n/catalog";

const LABELS = {
  "en-US": {
    save_recipe: "Save recipe",
    create_plan: "Create plan",
    replace_plan_item: "Replace meal",
    create_share: "Create private link",
    queued: "Queued safely",
    conflict: "Already confirmed",
    failed: "Could not confirm",
  },
  "zh-CN": {
    save_recipe: "保存菜谱",
    create_plan: "创建计划",
    replace_plan_item: "替换餐食",
    create_share: "创建私密链接",
    queued: "已安全排队",
    conflict: "已经确认",
    failed: "确认失败",
  },
} as const;

export function SuggestedActions({ actions, locale }: { actions: SuggestedActionReference[]; locale: Locale }) {
  const labels = LABELS[locale];
  const [states, setStates] = useState<Record<string, string>>({});

  async function execute(action: SuggestedActionReference) {
    setStates((current) => ({ ...current, [action.id]: "loading" }));
    try {
      const result = await api<ActionResult>(`/api/v1/agent/actions/${action.id}/execute`, {
        method: "POST",
      });
      setStates((current) => ({ ...current, [action.id]: result.status }));
    } catch (error) {
      setStates((current) => ({
        ...current,
        [action.id]: error instanceof ApiError && error.status === 409 ? "conflict" : "failed",
      }));
    }
  }

  return (
    <div className="suggested-actions">
      {actions.slice(0, 3).map((action) => {
        const state = states[action.id];
        const done = state === "queued" || state === "executing" || state === "succeeded";
        return (
          <div key={action.id}>
            <button type="button" disabled={state === "loading" || done} onClick={() => void execute(action)}>
              {state === "loading" ? "…" : labels[action.type]}
            </button>
            {done ? <small role="status">{labels.queued}</small> : null}
            {state === "conflict" ? <small role="status">{labels.conflict}</small> : null}
            {state === "failed" ? <small role="alert">{labels.failed}</small> : null}
          </div>
        );
      })}
    </div>
  );
}
