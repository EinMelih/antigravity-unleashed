import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ConversationCatalogItem } from "@/api/contracts";
import { ChatDesk } from "@/features/chats/chat-desk";
import {
  createChatDeskState,
  focusDeskConversation,
  openDeskConversation,
  setChatDeskMode,
  type ChatDeskState,
} from "@/features/chats/chat-desk-model";

function conversation(convoId: string, title: string): ConversationCatalogItem {
  return {
    archived: false,
    conversation_type: "normal",
    convo_id: convoId,
    created_at: 1,
    project_name: "",
    project_uuid: "outside-of-project",
    repository_name: "",
    sidebar_position: 0,
    source: "antigravity",
    status: "complete",
    step_count: 0,
    title,
    updated_at: 2,
    visible_in_sidebar: true,
    workspace_path: "",
  };
}

function renderDesk(
  state: ChatDeskState,
  conversations: ConversationCatalogItem[],
  overrides: Partial<React.ComponentProps<typeof ChatDesk>> = {},
) {
  return render(
    <ChatDesk
      conversations={conversations}
      onClose={vi.fn()}
      onFocus={vi.fn()}
      onModeChange={vi.fn()}
      renderPane={(conversationId) => <div>{`Inhalt ${conversationId}`}</div>}
      state={state}
      {...overrides}
    />,
  );
}

describe("ChatDesk", () => {
  it("offers only Fokus and Mehrere without floating or edge controls", () => {
    const state = setChatDeskMode(
      openDeskConversation(createChatDeskState("chat-a"), "chat-b"),
      "grid",
    );
    const onClose = vi.fn();
    const onModeChange = vi.fn();

    renderDesk(
      state,
      [conversation("chat-a", "Chat A"), conversation("chat-b", "Chat B")],
      {
        instanceIndicators: {
          "chat-a": { label: "AG-01 · Arbeitet", tone: "healthy" },
          "chat-b": { label: "AG-02 · Bereit", tone: "healthy" },
        },
        onClose,
        onModeChange,
      },
    );

    const layout = screen.getByRole("group", { name: "Fensterlayout" });
    expect(within(layout).getAllByRole("button").map((button) => button.textContent))
      .toEqual(["Fokus", "Mehrere"]);
    fireEvent.click(within(layout).getByRole("button", { name: "Fokus" }));
    fireEvent.click(within(layout).getByRole("button", { name: "Mehrere" }));
    expect(onModeChange.mock.calls).toEqual([["single"], ["grid"]]);

    expect(screen.getByText("AG-01 · Arbeitet")).toHaveAttribute("data-tone", "healthy");
    expect(screen.queryByRole("button", { name: /andocken/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /maximieren/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /wiederherstellen/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /verschieben/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /größe ändern/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Ansicht Chat B schließen" }));
    expect(onClose).toHaveBeenCalledWith("chat-b");
  });

  it("keeps background panes mounted in focus mode so drafts survive focus changes", () => {
    const state = openDeskConversation(createChatDeskState("chat-a"), "chat-b");

    renderDesk(
      state,
      [conversation("chat-a", "Chat A"), conversation("chat-b", "Chat B")],
    );

    expect(screen.getByText("Inhalt chat-b")).toBeVisible();
    expect(screen.getByText("Inhalt chat-a")).toBeInTheDocument();
    expect(screen.getByText("Inhalt chat-a").closest("article"))
      .toHaveAttribute("aria-hidden", "true");
  });

  it("uses an adaptive automatic grid for one through ten stable panes", () => {
    const conversations = Array.from({ length: 10 }, (_, index) => {
      const suffix = String.fromCharCode("a".charCodeAt(0) + index);
      return conversation(`chat-${suffix}`, `Chat ${suffix.toUpperCase()}`);
    });
    const renderable = (state: ChatDeskState) => (
      <ChatDesk
        conversations={conversations}
        onClose={vi.fn()}
        onFocus={vi.fn()}
        onModeChange={vi.fn()}
        renderPane={(conversationId) => <div>{`Inhalt ${conversationId}`}</div>}
        state={state}
      />
    );
    const onePane = setChatDeskMode(createChatDeskState("chat-a"), "grid");
    const { container, rerender } = render(renderable(onePane));
    const stage = () => container.querySelector<HTMLElement>(".chat-desk-stage");

    expect(stage()).toHaveStyle({
      gridTemplateColumns: "minmax(0, 1fr)",
      gridTemplateRows: "minmax(0, 1fr)",
    });

    const twoPanes = openDeskConversation(onePane, "chat-b");
    rerender(renderable(twoPanes));
    expect(stage()).toHaveStyle({
      gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
      gridTemplateRows: "minmax(0, 1fr)",
    });

    const threePanes = openDeskConversation(twoPanes, "chat-c");
    rerender(renderable(threePanes));
    expect(stage()).toHaveStyle({
      gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
      gridTemplateRows: "repeat(2, minmax(0, 1fr))",
    });

    let tenPanes = threePanes;
    for (const conversationId of [
      "chat-d",
      "chat-e",
      "chat-f",
      "chat-g",
      "chat-h",
      "chat-i",
      "chat-j",
    ]) {
      tenPanes = openDeskConversation(tenPanes, conversationId);
    }
    tenPanes = focusDeskConversation(tenPanes, "chat-a");
    rerender(renderable(tenPanes));

    expect(screen.getAllByRole("article").map((pane) => pane.getAttribute("aria-label")))
      .toEqual(conversations.map((item) => `${item.title} Chatansicht`));
    expect(stage()).toHaveStyle({
      gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
      gridTemplateRows: "repeat(3, minmax(0, 1fr))",
    });
  });
});
