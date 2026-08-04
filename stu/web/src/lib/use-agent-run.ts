"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, type AgentRun } from "./api";
import type { Locale } from "@/i18n/catalog";

type RunPhase = "idle" | "submitting" | "polling" | "completed" | "failed";

interface RunState {
  phase: RunPhase;
  run: AgentRun | null;
  error: string | null;
}

const INITIAL_STATE: RunState = { phase: "idle", run: null, error: null };

function idempotencyKey(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") return globalThis.crypto.randomUUID();
  return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function useAgentRun(locale: Locale) {
  const [state, setState] = useState<RunState>(INITIAL_STATE);
  const conversationId = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const disposed = useRef(false);
  const pollRef = useRef<(runId: string) => Promise<void>>(async () => undefined);

  const clearTimer = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  }, []);

  useEffect(() => {
    disposed.current = false;
    return () => {
      disposed.current = true;
      clearTimer();
    };
  }, [clearTimer]);

  const poll = useCallback(
    async (runId: string): Promise<void> => {
      try {
        const run = await api<AgentRun>(`/api/v1/agent/runs/${runId}`);
        if (disposed.current) return;
        if (run.status === "completed") {
          conversationId.current = run.conversation_id;
          setState({ phase: "completed", run, error: null });
          return;
        }
        if (run.status === "failed") {
          setState({ phase: "failed", run, error: run.error_code ?? "agent_failed" });
          return;
        }
        setState({ phase: "polling", run, error: null });
        timer.current = setTimeout(() => void pollRef.current(runId), 750);
      } catch (error) {
        if (!disposed.current) {
          setState({
            phase: "failed",
            run: null,
            error: error instanceof Error ? error.message : "request_failed",
          });
        }
      }
    },
    [],
  );

  useEffect(() => {
    pollRef.current = poll;
  }, [poll]);

  const submit = useCallback(
    async (message: string) => {
      clearTimer();
      setState({ phase: "submitting", run: null, error: null });
      try {
        const run = await api<AgentRun>("/api/v1/agent/runs", {
          method: "POST",
          body: JSON.stringify({
            conversation_id: conversationId.current,
            message,
            locale,
            idempotency_key: idempotencyKey(),
          }),
        });
        if (disposed.current) return;
        setState({ phase: "polling", run, error: null });
        await poll(run.id);
      } catch (error) {
        if (!disposed.current) {
          setState({
            phase: "failed",
            run: null,
            error: error instanceof Error ? error.message : "request_failed",
          });
        }
      }
    },
    [clearTimer, locale, poll],
  );

  return { ...state, submit, reset: () => setState(INITIAL_STATE) };
}
