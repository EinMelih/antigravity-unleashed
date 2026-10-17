import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ConversationCatalogItem } from "@/api/contracts";
import { ChatHistory } from "@/features/chats/chat-history";
import { ChatWorkspace } from "@/features/chats/chat-workspace";
import { ConversationList } from "@/features/chats/conversation-list";

const conversation: ConversationCatalogItem = {
  archived: true,
  conversation_type: "project",
  convo_id: "12345678-1234-1234-1234-123456789012",
  created_at: 1,
  project_name: "Antigravity Agent",
  project_uuid: "project-1",
  repository_name: "antigravity-agent",
  sidebar_position: null,
  source: "antigravity",
  status: "complete",
  step_count: 4,
  title: "Saubere Chat-Steuerung",
  updated_at: 2,
  visible_in_sidebar: false,
  workspace_path: "D:\\Antigravity Agent",
};

describe("chat components", () => {
  it("shows compact counts and selects a conversation", () => {
    const onSelect = vi.fn();
    render(
      <ConversationList
        conversations={[conversation]}
        counts={{ archived: 1, complete: 0, running: 0, visible: 0 }}
        onScopeChange={vi.fn()}
        onSearchChange={vi.fn()}
        onSelect={onSelect}
        scope="archived"
        search=""
        selectedId={null}
      />,
    );
    expect(screen.getByRole("radio", { name: "0 Chats" })).toBeVisible();
    expect(screen.getByRole("radio", { name: "1 archiviert" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Saubere Chat-Steuerung/ }));
    expect(onSelect).toHaveBeenCalledWith(conversation.convo_id);
  });

  it("offers a controlled conversation type filter", () => {
    const onTypeFilterChange = vi.fn();
    render(
      <ConversationList
        conversations={[{ ...conversation, conversation_type: "normal" }]}
        counts={{ archived: 1, complete: 0, running: 0, visible: 0 }}
        onScopeChange={vi.fn()}
        onSearchChange={vi.fn()}
        onSelect={vi.fn()}
        onTypeFilterChange={onTypeFilterChange}
        scope="archived"
        search=""
        selectedId={null}
        typeFilter="normal"
      />,
    );

    expect(screen.getByRole("radiogroup", { name: "Chattyp" })).toBeVisible();
    expect(screen.getByRole("radio", { name: "Alle Typen" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "Normalchats" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "Projektchats" }));
    expect(onTypeFilterChange).toHaveBeenCalledWith("project");
  });

  it("offers a dedicated project selector for project chats", async () => {
    const user = userEvent.setup();
    const onProjectFilterChange = vi.fn();
    const secondProject = {
      ...conversation,
      convo_id: "22345678-1234-1234-1234-123456789012",
      project_name: "sample-api",
      project_uuid: "project-2",
      title: "API-Projektchat",
      workspace_path: "D:\\projects\\sample-api",
    };
    render(
      <ConversationList
        conversations={[conversation, secondProject]}
        counts={{ archived: 2, complete: 0, running: 0, visible: 0 }}
        onProjectFilterChange={onProjectFilterChange}
        onScopeChange={vi.fn()}
        onSearchChange={vi.fn()}
        onSelect={vi.fn()}
        projectFilter="path:d:/antigravity agent"
        scope="archived"
        search=""
        selectedId={null}
        typeFilter="project"
      />,
    );

    const projectFilter = screen.getByRole("combobox", { name: "Projekt filtern" });
    expect(projectFilter).toHaveTextContent("Antigravity Agent (1)");
    await user.click(projectFilter);
    expect(await screen.findByRole("option", { name: "Alle Projekte" })).toBeVisible();
    expect(screen.getByRole("option", { name: "Antigravity Agent (1)" })).toBeVisible();
    await user.click(screen.getByRole("option", { name: "sample-api (1)" }));
    expect(onProjectFilterChange).toHaveBeenCalledWith("path:d:/projects/sample-api");
  });

  it("labels every row by conversation type and keeps project context", () => {
    const projectConversation = { ...conversation, archived: false, title: "Projektzeile" };
    const normalConversation = {
      ...conversation,
      archived: false,
      conversation_type: "normal",
      convo_id: "43345678-1234-1234-1234-123456789012",
      project_name: "",
      project_uuid: "outside-of-project",
      title: "Normalzeile",
    };
    render(
      <ConversationList
        conversations={[projectConversation, normalConversation]}
        counts={{ archived: 0, complete: 2, running: 0, visible: 2 }}
        onScopeChange={vi.fn()}
        onSearchChange={vi.fn()}
        onSelect={vi.fn()}
        scope="active"
        search=""
        selectedId={null}
      />,
    );

    const projectRow = screen.getByRole("button", { name: /Projektzeile/ });
    expect(within(projectRow).getByText("Projekt")).toBeVisible();
    expect(within(projectRow).getByText("Antigravity Agent")).toBeVisible();
    expect(within(screen.getByRole("button", { name: /Normalzeile/ })).getByText("Normalchat")).toBeVisible();
  });

  it("does not render an unknown native instance as healthy", () => {
    render(
      <ConversationList
        conversations={[conversation]}
        counts={{ archived: 1, complete: 0, running: 0, visible: 0 }}
        instanceIndicators={{
          [conversation.convo_id]: { label: "AG-01 · Unbekannt", tone: "attention" },
        }}
        onScopeChange={vi.fn()}
        onSearchChange={vi.fn()}
        onSelect={vi.fn()}
        scope="archived"
        search=""
        selectedId={null}
      />,
    );

    const badge = screen.getByTitle("AG-01 · Unbekannt");
    expect(badge).toHaveClass("text-warning");
    expect(badge).not.toHaveClass("text-success");
  });

  it("starts selection mode and toggles only selectable conversations in the visible filter", () => {
    const matching = { ...conversation, archived: false, title: "Saubere Auswahl" };
    const running = {
      ...conversation,
      archived: false,
      convo_id: "22345678-1234-1234-1234-123456789012",
      status: "running",
      title: "Saubere laufende Arbeit",
    };
    const filteredOut = {
      ...conversation,
      archived: false,
      convo_id: "32345678-1234-1234-1234-123456789012",
      title: "Anderer Chat",
    };
    const onBeginSelection = vi.fn();
    const onToggleVisible = vi.fn();
    const { rerender } = render(
      <ConversationList
        conversations={[matching, running, filteredOut]}
        counts={{ archived: 0, complete: 2, running: 1, visible: 3 }}
        onBeginSelection={onBeginSelection}
        onScopeChange={vi.fn()}
        onSearchChange={vi.fn()}
        onSelect={vi.fn()}
        onToggleVisible={onToggleVisible}
        scope="active"
        search="Saubere"
        selectedId={null}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Auswählen" }));
    expect(onBeginSelection).toHaveBeenCalledTimes(1);

    rerender(
      <ConversationList
        conversations={[matching, running, filteredOut]}
        counts={{ archived: 0, complete: 2, running: 1, visible: 3 }}
        onBeginSelection={onBeginSelection}
        onScopeChange={vi.fn()}
        onSearchChange={vi.fn()}
        onSelect={vi.fn()}
        onToggleVisible={onToggleVisible}
        scope="active"
        search="Saubere"
        selectedId={null}
        selectionMode
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Sichtbare auswählen" }));
    expect(onToggleVisible).toHaveBeenCalledWith([matching.convo_id], true);

    rerender(
      <ConversationList
        conversations={[matching, running, filteredOut]}
        counts={{ archived: 0, complete: 2, running: 1, visible: 3 }}
        onBeginSelection={onBeginSelection}
        onScopeChange={vi.fn()}
        onSearchChange={vi.fn()}
        onSelect={vi.fn()}
        onToggleVisible={onToggleVisible}
        scope="active"
        search="Saubere"
        selectedId={null}
        selectedIds={new Set([matching.convo_id])}
        selectionMode
      />,
    );

    expect(screen.getByText("1 ausgewählt")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Sichtbare abwählen" }));
    expect(onToggleVisible).toHaveBeenLastCalledWith([matching.convo_id], false);
  });

  it("applies search and type filters to visible selection", () => {
    const projectConversation = {
      ...conversation,
      archived: false,
      title: "Saubere Projektarbeit",
    };
    const normalConversation = {
      ...conversation,
      archived: false,
      conversation_type: "normal",
      convo_id: "33345678-1234-1234-1234-123456789012",
      project_name: "",
      project_uuid: "outside-of-project",
      title: "Saubere Unterhaltung",
    };
    const otherProjectConversation = {
      ...projectConversation,
      convo_id: "53345678-1234-1234-1234-123456789012",
      project_name: "sample-api",
      project_uuid: "project-2",
      title: "Saubere Projektarbeit API",
      workspace_path: "D:\\projects\\sample-api",
    };
    const onToggleVisible = vi.fn();

    render(
      <ConversationList
        conversations={[projectConversation, otherProjectConversation, normalConversation]}
        counts={{ archived: 0, complete: 3, running: 0, visible: 3 }}
        onScopeChange={vi.fn()}
        onSearchChange={vi.fn()}
        onSelect={vi.fn()}
        onToggleVisible={onToggleVisible}
        scope="active"
        search="Saubere"
        selectedId={null}
        selectionMode
        projectFilter="path:d:/antigravity agent"
        typeFilter="project"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Sichtbare auswählen" }));
    expect(onToggleVisible).toHaveBeenCalledWith([projectConversation.convo_id], true);
  });

  it("selects a row without navigation and exposes delete, cancel and running state", () => {
    const selectable = { ...conversation, archived: false, title: "Chat zum Löschen" };
    const running = {
      ...conversation,
      archived: false,
      convo_id: "42345678-1234-1234-1234-123456789012",
      status: "running",
      title: "Laufender Chat",
    };
    const onCancelSelection = vi.fn();
    const onRequestDeleteSelected = vi.fn();
    const onSelect = vi.fn();
    const onToggleSelected = vi.fn();

    render(
      <ConversationList
        conversations={[selectable, running]}
        counts={{ archived: 0, complete: 1, running: 1, visible: 2 }}
        onCancelSelection={onCancelSelection}
        onRequestDeleteSelected={onRequestDeleteSelected}
        onScopeChange={vi.fn()}
        onSearchChange={vi.fn()}
        onSelect={onSelect}
        onToggleSelected={onToggleSelected}
        scope="active"
        search=""
        selectedId={null}
        selectedIds={new Set([selectable.convo_id])}
        selectionMode
      />,
    );

    fireEvent.click(screen.getByText("Chat zum Löschen"));
    expect(onToggleSelected).toHaveBeenCalledWith(selectable.convo_id);
    expect(onSelect).not.toHaveBeenCalled();

    expect(screen.getByRole("checkbox", { name: "Laufender Chat auswählen" })).toBeDisabled();
    expect(screen.getByText("Arbeitet gerade")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Löschen" }));
    expect(onRequestDeleteSelected).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Abbrechen" }));
    expect(onCancelSelection).toHaveBeenCalledTimes(1);
  });

  it("keeps a selected chat visibly selected if it starts running", () => {
    const running = {
      ...conversation,
      archived: false,
      status: "running",
      title: "Gerade gestarteter Chat",
    };

    render(
      <ConversationList
        conversations={[running]}
        counts={{ archived: 0, complete: 0, running: 1, visible: 1 }}
        onCancelSelection={vi.fn()}
        onRequestDeleteSelected={vi.fn()}
        onScopeChange={vi.fn()}
        onSearchChange={vi.fn()}
        onSelect={vi.fn()}
        onToggleSelected={vi.fn()}
        scope="active"
        search=""
        selectedId={null}
        selectedIds={new Set([running.convo_id])}
        selectionMode
      />,
    );

    expect(screen.getByText("1 ausgewählt")).toBeVisible();
    expect(screen.getByRole("checkbox", { name: "Gerade gestarteter Chat auswählen" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Gerade gestarteter Chat auswählen" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Löschen" })).toBeDisabled();
  });

  it("uses the title and locks archived composers until restore", () => {
    render(
      <ChatWorkspace
        activeModel="Gemini 3.6 Flash (High)"
        conversation={conversation}
        deliveryPhase="idle"
        history={[]}
        historyLoading={false}
        models={[{ label: "Gemini 3.6 Flash (High)", source: "official" }]}
        modelSwitching={false}
        mutationBusy={false}
        onArchiveChange={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn().mockResolvedValue(undefined)}
        onModelChange={vi.fn().mockResolvedValue(undefined)}
        onOpenBrain={vi.fn().mockResolvedValue(undefined)}
        onOpenWindow={vi.fn().mockResolvedValue(undefined)}
        onSend={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    expect(screen.getByRole("heading", { name: "Saubere Chat-Steuerung" })).toBeVisible();
    expect(screen.getByText("Dieser Chat ist archiviert.")).toBeVisible();
    expect(screen.getByLabelText("Nachricht an Anti-Gravity")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Wiederherstellen" })).toBeVisible();
  });

  it("allows pasting image files from clipboard into composer", async () => {
    const activeConvo: ConversationCatalogItem = {
      ...conversation,
      archived: false,
    };
    render(
      <ChatWorkspace
        activeModel="Gemini 3.6 Flash (High)"
        conversation={activeConvo}
        deliveryPhase="idle"
        history={[]}
        historyLoading={false}
        models={[{ label: "Gemini 3.6 Flash (High)", source: "official" }]}
        modelSwitching={false}
        mutationBusy={false}
        onArchiveChange={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn().mockResolvedValue(undefined)}
        onModelChange={vi.fn().mockResolvedValue(undefined)}
        onOpenBrain={vi.fn().mockResolvedValue(undefined)}
        onOpenWindow={vi.fn().mockResolvedValue(undefined)}
        onSend={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const textarea = screen.getByLabelText("Nachricht an Anti-Gravity");
    const file = new File(["fake-image-data"], "test_paste.png", { type: "image/png" });

    fireEvent.paste(textarea, {
      clipboardData: {
        items: [
          {
            getAsFile: () => file,
            kind: "file",
            type: "image/png",
          },
        ],
      },
    });

    expect(await screen.findByAltText("test_paste.png")).toBeInTheDocument();
  });

  it("queues messages when agent is busy and allows edit / delete", async () => {
    const runningConvo: ConversationCatalogItem = {
      ...conversation,
      archived: false,
      status: "running",
    };
    render(
      <ChatWorkspace
        activeModel="Gemini 3.6 Flash (High)"
        conversation={runningConvo}
        deliveryPhase="idle"
        history={[]}
        historyLoading={false}
        models={[{ label: "Gemini 3.6 Flash (High)", source: "official" }]}
        modelSwitching={false}
        mutationBusy={false}
        onArchiveChange={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn().mockResolvedValue(undefined)}
        onModelChange={vi.fn().mockResolvedValue(undefined)}
        onOpenBrain={vi.fn().mockResolvedValue(undefined)}
        onOpenWindow={vi.fn().mockResolvedValue(undefined)}
        onSend={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const textarea = screen.getByLabelText("Nachricht an Anti-Gravity");
    fireEvent.change(textarea, { target: { value: "Queued test message" } });
    fireEvent.keyDown(textarea, { key: "Enter", code: "Enter" });

    expect(await screen.findByText("Queued Messages")).toBeInTheDocument();
    expect(screen.getByText("Queued test message")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Chat löschen" })).toBeDisabled();

    const editBtn = screen.getByLabelText("Nachricht bearbeiten");
    fireEvent.click(editBtn);

    expect(screen.queryByText("Queued Messages")).not.toBeInTheDocument();
    expect(textarea).toHaveValue("Queued test message");
  });

  it("does not carry a queued message or draft into another conversation", async () => {
    vi.useFakeTimers();
    try {
      const onSend = vi.fn().mockResolvedValue(undefined);
      const firstConversation: ConversationCatalogItem = {
        ...conversation,
        archived: false,
        convo_id: "11111111-1111-1111-1111-111111111111",
        status: "running",
        title: "Chat A",
      };
      const secondConversation: ConversationCatalogItem = {
        ...conversation,
        archived: false,
        convo_id: "22222222-2222-2222-2222-222222222222",
        status: "complete",
        title: "Chat B",
      };
      const sharedProps = {
        activeModel: "Gemini 3.6 Flash (High)",
        deliveryPhase: "idle" as const,
        history: [],
        historyLoading: false,
        models: [{ label: "Gemini 3.6 Flash (High)", source: "official" as const }],
        modelSwitching: false,
        mutationBusy: false,
        onArchiveChange: vi.fn().mockResolvedValue(undefined),
        onDelete: vi.fn().mockResolvedValue(undefined),
        onModelChange: vi.fn().mockResolvedValue(undefined),
        onOpenBrain: vi.fn().mockResolvedValue(undefined),
        onOpenWindow: vi.fn().mockResolvedValue(undefined),
        onSend,
      };
      const { rerender } = render(
        <ChatWorkspace {...sharedProps} conversation={firstConversation} />,
      );

      const firstComposer = screen.getByLabelText("Nachricht an Anti-Gravity");
      fireEvent.change(firstComposer, { target: { value: "Nur für Chat A" } });
      fireEvent.keyDown(firstComposer, { key: "Enter", code: "Enter" });
      fireEvent.change(firstComposer, { target: { value: "Entwurf aus Chat A" } });

      rerender(<ChatWorkspace {...sharedProps} conversation={secondConversation} />);
      act(() => vi.runAllTimers());

      expect(onSend).not.toHaveBeenCalled();
      expect(screen.queryByText("Nur für Chat A")).not.toBeInTheDocument();
      expect(screen.getByLabelText("Nachricht an Anti-Gravity")).toHaveValue("");
    } finally {
      vi.useRealTimers();
    }
  });



  it("groups tool activity and exposes background task details", () => {
    render(
      <ChatHistory
        entries={[
          {
            enriched: { background_task: true, command: "npm run dev", summary: "Frontend starten" },
            idx: 1,
            is_running: true,
            state: "running",
            tool_name: "run_command",
            type: "tool_call",
          },
          { idx: 2, output: "Port 5173", type: "tool_output" },
        ]}
        running={false}
      />,
    );
    expect(screen.getByText("Ran 1 command")).toBeVisible();
    expect(screen.getByText("Run")).toBeVisible();
    expect(screen.getByText("npm run dev")).toBeVisible();
  });
});
