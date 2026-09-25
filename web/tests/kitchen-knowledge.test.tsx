import { useState } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KnowledgePage } from "@/features/kitchen/knowledge";
import { applyDemoCommand } from "@/features/kitchen/demo-engine";
import { emptyState } from "@/features/kitchen/data";
import type { KitchenState } from "@/features/kitchen/types";

function Harness({ initial = emptyState() }: { initial?: KitchenState }) {
  const [state, setState] = useState(initial);
  return <KnowledgePage state={state} plan={null} demo notify={() => {}} navigate={() => {}} send={async (type, payload) => {
    setState(value => applyDemoCommand(value, { type, payload, expectedRevision: value.revision, operationId: crypto.randomUUID() }).state);
    return true;
  }} />;
}

describe("Nutrition knowledge", () => {
  it("creates Chinese content, searches, disables, edits and deletes a saved document", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Add document" }));
    fireEvent.change(screen.getByLabelText("Document title"), { target: { value: "家庭膳食搭配" } });
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "宝宝饭" } });
    fireEvent.change(screen.getByLabelText("Document content"), { target: { value: "用户保存的营养资料，中文内容。" } });
    fireEvent.click(screen.getByRole("button", { name: "Save document" }));
    const title = await screen.findByRole("heading", { name: "家庭膳食搭配" });
    const card = title.closest("article")!;
    expect(within(card).getByText("Version 1")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Search documents"), { target: { value: "不存在" } });
    expect(screen.queryByRole("heading", { name: "家庭膳食搭配" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search documents"), { target: { value: "营养" } });
    fireEvent.click(screen.getByLabelText("Enable 家庭膳食搭配"));
    await waitFor(() => expect(screen.getByText("Version 2")).toBeVisible());
    expect(screen.getByLabelText("Enable 家庭膳食搭配")).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Edit 家庭膳食搭配" }));
    fireEvent.change(screen.getByLabelText("Document content"), { target: { value: "修改后的营养资料。" } });
    fireEvent.click(screen.getByRole("button", { name: "Save document" }));
    await screen.findByText("Version 3");
    fireEvent.click(screen.getByRole("button", { name: "Delete 家庭膳食搭配" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "家庭膳食搭配" })).not.toBeInTheDocument());
  });

  it("imports Markdown into an editable preview and saves only after review", async () => {
    const send = vi.fn().mockResolvedValue(true);
    render(<KnowledgePage state={emptyState()} plan={null} demo send={send} notify={() => {}} navigate={() => {}} />);
    const file = new File(["# 用户的资料\n保留原文"], "family-notes.md", { type: "text/markdown" });
    Object.defineProperty(file, "text", { value: async () => "# 用户的资料\n保留原文" });
    fireEvent.change(screen.getByLabelText("Import text or Markdown"), { target: { files: [file] } });
    await screen.findByText("Import preview");
    expect(screen.getByLabelText("Document title")).toHaveValue("family-notes");
    expect(screen.getByLabelText("Document content")).toHaveValue("# 用户的资料\n保留原文");
    expect(send).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save document" }));
    await waitFor(() => expect(send).toHaveBeenCalledWith("knowledge.save", { document: expect.objectContaining({ title: "family-notes", content: "# 用户的资料\n保留原文" }) }));
  });

  it("rejects unsupported PDFs without calling the save command", async () => {
    const send = vi.fn();
    render(<KnowledgePage state={emptyState()} plan={null} demo send={send} notify={() => {}} navigate={() => {}} />);
    fireEvent.change(screen.getByLabelText("Import text or Markdown"), { target: { files: [new File(["pdf"], "nutrition.pdf", { type: "application/pdf" })] } });
    expect(await screen.findByRole("alert")).toHaveTextContent(".txt or .md");
    expect(send).not.toHaveBeenCalled();
  });
});


it("updates the toggle immediately while saving and restores it after a failed save", async () => {
  const state = emptyState();
  state.knowledgeDocuments = [{ id: "doc", title: "Family notes", content: "User reference", category: "Nutrition", enabled: true, version: 1, updatedAt: "2026-09-17T12:00:00Z" }];
  let finish!: (saved: boolean) => void;
  const send = vi.fn(() => new Promise<boolean>(resolve => { finish = resolve; }));
  render(<KnowledgePage state={state} plan={null} demo send={send} notify={() => {}} navigate={() => {}} />);
  const toggle = screen.getByLabelText("Enable Family notes");
  fireEvent.click(toggle);
  expect(toggle).not.toBeChecked();
  expect(toggle).toBeDisabled();
  expect(state.knowledgeDocuments[0].enabled).toBe(true);
  expect(screen.getByText("Version 1")).toBeVisible();
  await act(async () => { finish(false); });
  expect(toggle).toBeChecked();
  expect(toggle).not.toBeDisabled();
  expect(screen.getByRole("alert")).toHaveTextContent("previous status");
});
