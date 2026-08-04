"use client";

import { useEffect, useState } from "react";

import { api } from "./api";

export type LoadState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; message: string };

export function useFeatureData<T>(path: string): LoadState<T> {
  const [state, setState] = useState<LoadState<T>>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    api<T>(path, { signal: controller.signal })
      .then((data) => setState({ status: "ready", data }))
      .catch((error) => {
        if (!controller.signal.aborted) {
          setState({ status: "error", message: error instanceof Error ? error.message : "request_failed" });
        }
      });
    return () => controller.abort();
  }, [path]);

  return state;
}
