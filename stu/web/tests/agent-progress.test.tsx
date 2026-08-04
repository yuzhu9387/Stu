import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentProgressView } from "@/features/chat/agent-progress";

describe("agent progress", () => {
  it("shows action receipts without private reasoning", () => {
    render(
      <AgentProgressView
        locale="en-US"
        progress={{
          stage: "checking",
          completedActions: ["checkedHouseholdRecipes"],
          result: "Three recommendations are ready.",
        }}
      />,
    );

    expect(screen.getByText("Checked household recipes")).toBeVisible();
    expect(screen.getByText("Three recommendations are ready.")).toBeVisible();
    expect(screen.queryByText(/chain of thought/i)).not.toBeInTheDocument();
  });
});
