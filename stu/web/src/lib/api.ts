export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers,
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Keep the bounded status-only fallback.
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface SessionIdentity {
  account_id: string;
  household_id: string;
  email: string;
  role: string;
}

export type RunStatus = "queued" | "running" | "completed" | "failed";
export type SuggestedActionType =
  | "save_recipe"
  | "create_plan"
  | "replace_plan_item"
  | "create_share";

export interface SuggestedActionReference {
  id: string;
  type: SuggestedActionType;
  expires_at: string;
}

export interface AgentResponse {
  thinking: string;
  plan: string;
  act: string;
  answer: string;
  suggested_actions: SuggestedActionReference[];
}

export interface AgentRun {
  id: string;
  conversation_id: string;
  status: RunStatus;
  response: AgentResponse | null;
  error_code: string | null;
}

export interface ActionResult {
  action_id: string;
  type: SuggestedActionType;
  status: "pending" | "queued" | "executing" | "succeeded" | "failed";
  result: Record<string, unknown> | null;
}
