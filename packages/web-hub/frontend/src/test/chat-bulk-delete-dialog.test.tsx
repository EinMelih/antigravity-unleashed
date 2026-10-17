import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ConversationCatalogItem } from "@/api/contracts";
import { BulkDeleteDialog } from "@/features/chats/bulk-delete-dialog";

function conversation(
  conversationId: string,
  title: string,
  archived = false,
): ConversationCatalogItem {
  return {
    archived,
    conversation_type: "normal",
    convo_id: conversationId,
    created_at: 1,
    project_name: "",
    project_uuid: "",
    repository_name: "",
    sidebar_position: null,
    source: "antigravity",
    status: "complete",
    step_count: 1,
    title,
    updated_at: 2,
    visible_in_sidebar: !archived,
    workspace_path: "",
  };
}

describe("BulkDeleteDialog", () => {
  it("summarizes the selection and requires explicit confirmation", () => {
    const onConfirm = vi.fn();
    render(
      <BulkDeleteDialog
        busy={false}
        conversations={[
          conversation("chat-a", "Erster Testchat"),
          conversation("chat-b", "Zweiter Testchat", true),
        ]}
        onConfirm={onConfirm}
        onOpenChange={vi.fn()}
        open
      />,
    );

    expect(screen.getByRole("alertdialog", { name: "2 Chats dauerhaft löschen?" })).toBeVisible();
    expect(screen.getByText("Erster Testchat")).toBeVisible();
    expect(screen.getByText("Zweiter Testchat")).toBeVisible();
    expect(screen.getByText(/1 aktiver Chat und 1 archivierter Chat/)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "2 Chats löschen" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alertdialog")).toBeVisible();
  });

  it("shows progress and disables cancellation while deletion is running", () => {
    render(
      <BulkDeleteDialog
        busy
        conversations={[conversation("chat-a", "Testchat")]}
        onConfirm={vi.fn()}
        onOpenChange={vi.fn()}
        open
        progress={{ completed: 1, total: 3 }}
      />,
    );

    expect(screen.getByText("1 von 3 verarbeitet")).toBeVisible();
    expect(screen.getByRole("button", { name: "Abbrechen" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Wird gelöscht/ })).toBeDisabled();
  });

  it("counts only deletable chats and explains protected running selections", () => {
    render(
      <BulkDeleteDialog
        blockedCount={1}
        busy={false}
        conversations={[conversation("chat-a", "Löschbarer Chat")]}
        onConfirm={vi.fn()}
        onOpenChange={vi.fn()}
        open
      />,
    );

    expect(screen.getByRole("alertdialog", { name: "1 Chat dauerhaft löschen?" })).toBeVisible();
    expect(screen.getByText("1 laufender Chat bleibt geschützt und wird nicht gelöscht.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Chat löschen" })).toBeEnabled();
  });
});
