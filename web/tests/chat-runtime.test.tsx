import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatHome } from "@/features/chat/chat-home";
import { ChatThread } from "@/features/chat/chat-thread";
import { LocaleProvider } from "@/i18n/locale-context";

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const session = {
  account_id: "10000000-0000-0000-0000-000000000001",
  household_id: "20000000-0000-0000-0000-000000000002",
  email: "cook@example.com",
  role: "owner",
};

const queuedRun = {
  id: "30000000-0000-0000-0000-000000000003",
  conversation_id: "40000000-0000-0000-0000-000000000004",
  status: "queued",
  response: null,
  error_code: null,
};

const response = {
  thinking: "I checked the household context.",
  plan: "Recommend one practical dinner.",
  act: "Compared the saved recipes.",
  answer: "Cook tomato and egg stir-fry tonight.",
  suggested_actions: [
    {
      id: "50000000-0000-0000-0000-000000000005",
      type: "save_recipe" as const,
      expires_at: "2026-07-17T00:00:00Z",
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("real assistant chat", () => {
  it("submits once, polls, and renders one structured final response", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(session))
      .mockResolvedValueOnce(json(queuedRun, 202))
      .mockResolvedValueOnce(json({ ...queuedRun, status: "completed", response }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <LocaleProvider initialLocale="en-US">
        <ChatHome />
      </LocaleProvider>,
    );

    const textbox = await screen.findByRole("textbox");
    await user.type(textbox, "Recommend dinner");
    await user.click(screen.getByRole("button", { name: /ask assistant/i }));

    expect(await screen.findByText(response.answer)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Thinking" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Plan" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Act" })).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const submit = JSON.parse(fetchMock.mock.calls[1][1].body as string) as Record<string, unknown>;
    expect(submit.message).toBe("Recommend dinner");
    expect(submit.locale).toBe("en-US");
    expect(typeof submit.idempotency_key).toBe("string");
  });

  it("does not execute an action until its button is clicked", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({
      action_id: response.suggested_actions[0].id,
      type: "save_recipe",
      status: "queued",
      result: null,
    }, 202));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<ChatThread response={response} locale="en-US" />);
    expect(fetchMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Save recipe" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).toContain(
      `/api/v1/agent/actions/${response.suggested_actions[0].id}/execute`,
    );
    expect(await screen.findByText("Queued safely")).toBeVisible();
  });
});
