import { useQueryClient } from "@tanstack/react-query";
import { Info, List, MessageSquarePlus, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { ConversationCatalogItem, ModelCatalogItem, WorkerSnapshot } from "@/api/contracts";
import { ApiError } from "@/api/errors";
import { EmptyState, ErrorState, LoadingState, OfflineState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { ChatContext } from "@/features/chats/chat-context";
import type { ComposerPayload } from "@/features/chats/chat-composer";
import { ChatDesk } from "@/features/chats/chat-desk";
import {
  CHAT_DESK_MAX_PANES,
  canOpenDeskConversation,
  type ChatDeskMode,
} from "@/features/chats/chat-desk-model";
import { ChatPane } from "@/features/chats/chat-pane";
import { createChat, deleteConversation } from "@/features/chats/api";
import { BulkDeleteDialog } from "@/features/chats/bulk-delete-dialog";
import {
  cleanupWarningSuffix,
  deleteConversationsSequentially,
  includeMissingSelectedConversations,
  type ConversationDeleteProgress,
  updateConversationSelection,
} from "@/features/chats/bulk-delete";
import { ConversationList } from "@/features/chats/conversation-list";
import { instanceIndicator, instancesByConversation } from "@/features/chats/instance-model";
import { NewChatDialog } from "@/features/chats/new-chat-dialog";
import {
  ALL_PROJECTS_FILTER,
  type ConversationProjectFilter,
  type ConversationScope,
  type ConversationTypeFilter,
} from "@/features/chats/model";
import { useChatDesk } from "@/features/chats/use-chat-desk";
import { useChatContextData, useConversationCatalog } from "@/features/chats/use-chats-data";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useAntigravityInstances } from "@/hooks/use-antigravity-instances";

function workerConversationId(worker: WorkerSnapshot | null | undefined): string | null {
  return worker?.loaded_chat_id || worker?.chat_id || null;
}

export function ChatsPage() {
  const queryClient = useQueryClient();
  const [scope, setScope] = useState<ConversationScope | null>(null);
  const [typeFilter, setTypeFilter] = useState<ConversationTypeFilter>("all");
  const [projectFilter, setProjectFilter] = useState<ConversationProjectFilter>(
    ALL_PROJECTS_FILTER,
  );
  const [search, setSearch] = useState("");
  const [newChatOpen, setNewChatOpen] = useState(false);
  const [conversationSheetOpen, setConversationSheetOpen] = useState(false);
  const [contextSheetOpen, setContextSheetOpen] = useState(false);
  const [deskNotice, setDeskNotice] = useState<string | null>(null);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedConversationIds, setSelectedConversationIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [selectedConversationSnapshots, setSelectedConversationSnapshots] = useState(
    () => new Map<string, ConversationCatalogItem>(),
  );
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
  const [bulkDeleteBusy, setBulkDeleteBusy] = useState(false);
  const [bulkDeleteError, setBulkDeleteError] = useState<string | null>(null);
  const [bulkDeleteProgress, setBulkDeleteProgress] = useState<ConversationDeleteProgress | null>(null);
  const [bulkDeleteNotice, setBulkDeleteNotice] = useState<string | null>(null);
  const selectionFocusReady = useRef(false);
  const desktopLayout = useMediaQuery("(min-width: 901px)", true);
  const catalog = useConversationCatalog();
  const fleet = useAntigravityInstances();
  const conversations = useMemo(
    () => catalog.data?.conversations ?? [],
    [catalog.data],
  );
  const conversationIds = useMemo(
    () => conversations.map((conversation) => conversation.convo_id),
    [conversations],
  );
  const listConversations = useMemo(
    () => includeMissingSelectedConversations(
      conversations,
      selectedConversationIds,
      selectedConversationSnapshots,
    ),
    [conversations, selectedConversationIds, selectedConversationSnapshots],
  );
  const selectedConversations = useMemo(
    () => listConversations.filter(
      (conversation) => selectedConversationIds.has(conversation.convo_id),
    ),
    [listConversations, selectedConversationIds],
  );
  const deletableSelectedConversations = useMemo(
    () => selectedConversations.filter((conversation) => conversation.status !== "running"),
    [selectedConversations],
  );
  const blockedSelectedConversationCount = selectedConversations.length
    - deletableSelectedConversations.length;
  const validSelectedConversationIds = useMemo(
    () => new Set(selectedConversations.map((conversation) => conversation.convo_id)),
    [selectedConversations],
  );
  const desk = useChatDesk(conversationIds, catalog.data !== undefined);
  const selectedId = desk.state.activeConversationId;
  const selected = conversations.find((conversation) => conversation.convo_id === selectedId) ?? null;
  const context = useChatContextData();
  const effectiveScope: ConversationScope =
    scope ?? ((catalog.data?.counts.visible ?? 0) > 0 ? "active" : "archived");

  useEffect(() => {
    if (!selectionFocusReady.current) {
      selectionFocusReady.current = true;
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      const selector = selectionMode
        ? "[data-chat-selection-cancel]"
        : "[data-chat-selection-begin]";
      document.querySelector<HTMLButtonElement>(selector)?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [selectionMode]);

  function selectConversation(conversationId: string) {
    if (!canOpenDeskConversation(desk.state, conversationId)) {
      setDeskNotice(
        `Maximal ${CHAT_DESK_MAX_PANES} Chatansichten sind geöffnet. Schließe zuerst eine Ansicht mit ×.`,
      );
      setConversationSheetOpen(false);
      return;
    }
    setDeskNotice(null);
    desk.open(conversationId);
    setConversationSheetOpen(false);
  }

  async function refreshChats() {
    await Promise.all([
      catalog.refetch(),
      queryClient.invalidateQueries({ queryKey: ["chat-history"] }),
      queryClient.invalidateQueries({ queryKey: ["antigravity-workers"] }),
      queryClient.invalidateQueries({ queryKey: ["antigravity-instances"] }),
    ]);
  }

  async function create(input: ComposerPayload & {
    conversationType: "normal" | "project";
    model?: ModelCatalogItem;
    projectId?: number;
  }) {
    const result = await createChat(input);
    await queryClient.invalidateQueries({ queryKey: ["conversation-catalog"] });
    const conversationId = result.conversation_id || result.convo_id;
    if (conversationId) {
      selectConversation(conversationId);
      setScope("active");
    }
  }

  function beginSelection() {
    setBulkDeleteNotice(null);
    setBulkDeleteError(null);
    setSelectedConversationSnapshots(new Map());
    setSelectionMode(true);
  }

  function cancelSelection() {
    setSelectionMode(false);
    setSelectedConversationIds(new Set());
    setSelectedConversationSnapshots(new Map());
    setBulkDeleteOpen(false);
    setBulkDeleteError(null);
    setBulkDeleteProgress(null);
  }

  function toggleSelected(conversationId: string) {
    const selecting = !validSelectedConversationIds.has(conversationId);
    setSelectedConversationSnapshots((current) => {
      const next = new Map(current);
      if (selecting) {
        const conversation = listConversations.find(
          (item) => item.convo_id === conversationId,
        );
        if (conversation) next.set(conversationId, conversation);
      } else {
        next.delete(conversationId);
      }
      return next;
    });
    setSelectedConversationIds((current) => updateConversationSelection(
      current,
      conversationId,
      selecting,
    ));
  }

  function toggleVisible(conversationIdsToToggle: string[], selectedValue: boolean) {
    setSelectedConversationSnapshots((current) => {
      const next = new Map(current);
      conversationIdsToToggle.forEach((conversationId) => {
        if (selectedValue) {
          const conversation = listConversations.find(
            (item) => item.convo_id === conversationId,
          );
          if (conversation) next.set(conversationId, conversation);
        } else {
          next.delete(conversationId);
        }
      });
      return next;
    });
    setSelectedConversationIds((current) => {
      const next = new Set(current);
      conversationIdsToToggle.forEach((conversationId) => {
        if (selectedValue) next.add(conversationId);
        else next.delete(conversationId);
      });
      return next;
    });
  }

  function changeScope(nextScope: ConversationScope) {
    setScope(nextScope);
    setSelectedConversationIds(new Set());
    setSelectedConversationSnapshots(new Map());
    setBulkDeleteError(null);
  }

  function changeTypeFilter(nextType: ConversationTypeFilter) {
    setTypeFilter(nextType);
    if (nextType !== "project") setProjectFilter(ALL_PROJECTS_FILTER);
    setSelectedConversationIds(new Set());
    setSelectedConversationSnapshots(new Map());
    setBulkDeleteError(null);
  }

  function changeProjectFilter(nextProject: ConversationProjectFilter) {
    setProjectFilter(nextProject);
    setSelectedConversationIds(new Set());
    setSelectedConversationSnapshots(new Map());
    setBulkDeleteError(null);
  }

  function changeSearch(nextSearch: string) {
    setSearch(nextSearch);
    setSelectedConversationIds(new Set());
    setSelectedConversationSnapshots(new Map());
    setBulkDeleteError(null);
  }

  function requestBulkDelete() {
    if (!selectedConversations.length) return;
    setBulkDeleteError(null);
    setBulkDeleteProgress(null);
    setBulkDeleteOpen(true);
  }

  async function performBulkDelete() {
    if (bulkDeleteBusy || !selectedConversations.length) return;
    const blockedIds = selectedConversations
      .filter((conversation) => conversation.status === "running")
      .map((conversation) => conversation.convo_id);
    const deletableIds = selectedConversations
      .filter((conversation) => conversation.status !== "running")
      .map((conversation) => conversation.convo_id);

    if (!deletableIds.length) {
      setBulkDeleteError("Die ausgewählten Chats arbeiten gerade und können nicht gesammelt gelöscht werden.");
      return;
    }

    setBulkDeleteBusy(true);
    setBulkDeleteError(null);
    setBulkDeleteProgress({ completed: 0, total: deletableIds.length });
    try {
      const result = await deleteConversationsSequentially(
        deletableIds,
        deleteConversation,
        setBulkDeleteProgress,
      );
      result.deletedIds.forEach((conversationId) => {
        desk.close(conversationId);
        queryClient.removeQueries({ queryKey: ["chat-history", conversationId], exact: true });
        queryClient.removeQueries({ queryKey: ["active-model", conversationId], exact: true });
      });

      const failedIds = [
        ...blockedIds,
        ...result.failures.map((failure) => failure.conversationId),
      ];
      setSelectedConversationIds(new Set(failedIds));
      setSelectedConversationSnapshots((current) => {
        const next = new Map<string, ConversationCatalogItem>();
        failedIds.forEach((conversationId) => {
          const snapshot = current.get(conversationId)
            ?? listConversations.find((item) => item.convo_id === conversationId);
          if (snapshot) next.set(conversationId, snapshot);
        });
        return next;
      });
      await refreshChats();

      const cleanupSuffix = cleanupWarningSuffix(result.cleanupWarnings.length);
      if (failedIds.length) {
        const reason = result.failures[0]?.message;
        setBulkDeleteError(
          `${result.deletedIds.length} gelöscht, ${failedIds.length} nicht gelöscht.${reason ? ` ${reason}` : " Laufende Chats bleiben geschützt."}${cleanupSuffix}`,
        );
      } else {
        const absentSuffix = result.alreadyAbsentIds.length
          ? result.alreadyAbsentIds.length === 1
            ? " (1 war bereits entfernt)"
            : ` (${result.alreadyAbsentIds.length} waren bereits entfernt)`
          : "";
        const deletedLabel = result.deletedIds.length === 1 ? "1 Chat" : `${result.deletedIds.length} Chats`;
        setBulkDeleteNotice(`${deletedLabel} gelöscht${absentSuffix}.${cleanupSuffix}`);
        setBulkDeleteOpen(false);
        setSelectionMode(false);
        setSelectedConversationSnapshots(new Map());
      }
    } finally {
      setBulkDeleteBusy(false);
      setBulkDeleteProgress(null);
    }
  }

  if (catalog.isPending) {
    return <div className="grid h-full place-items-center p-6"><LoadingState description="Chats und Anti-Gravity-Zustand werden synchronisiert." /></div>;
  }
  if (catalog.isError && catalog.error instanceof ApiError && catalog.error.offline) {
    return <div className="grid h-full place-items-center p-6"><OfflineState onRetry={() => void refreshChats()} /></div>;
  }
  if (catalog.isError) {
    return (
      <div className="grid h-full place-items-center p-6"><ErrorState
        description={catalog.error instanceof Error ? catalog.error.message : String(catalog.error)}
        onRetry={() => void refreshChats()}
      /></div>
    );
  }

  const workerRows = [
    ...(context.workers.data?.primary ? [context.workers.data.primary] : []),
    ...(context.workers.data?.workers ?? []),
  ];
  const workersByConversation = new Map(
    workerRows
      .map((worker) => [workerConversationId(worker), worker] as const)
      .filter((entry): entry is [string, WorkerSnapshot] => Boolean(entry[0])),
  );
  const nativeInstancesByConversation = instancesByConversation(fleet.data?.instances ?? []);
  const instanceIndicators = Object.fromEntries(
    [...nativeInstancesByConversation].map(([conversationId, instance]) => [
      conversationId,
      instanceIndicator(instance),
    ]),
  );
  const selectedWorker = selected ? workersByConversation.get(selected.convo_id) : undefined;
  const selectedInstance = selected ? nativeInstancesByConversation.get(selected.convo_id) : undefined;
  const selectedProject = selected?.workspace_path
    ? context.projects.data?.projects.find((item) => item.integrity_workspace_path === selected.workspace_path)
    : undefined;
  const conversationList = (
    <ConversationList
      conversations={listConversations}
      counts={catalog.data?.counts ?? { archived: 0, complete: 0, running: 0 }}
      instanceIndicators={instanceIndicators}
      onBeginSelection={beginSelection}
      onCancelSelection={cancelSelection}
      onRequestDeleteSelected={requestBulkDelete}
      onProjectFilterChange={changeProjectFilter}
      onScopeChange={changeScope}
      onSearchChange={changeSearch}
      onSelect={selectConversation}
      onToggleSelected={toggleSelected}
      onToggleVisible={toggleVisible}
      onTypeFilterChange={changeTypeFilter}
      projectFilter={projectFilter}
      scope={effectiveScope}
      search={search}
      selectedIds={validSelectedConversationIds}
      selectedId={selectedId}
      selectionBusy={bulkDeleteBusy}
      selectionMode={selectionMode}
      typeFilter={typeFilter}
    />
  );
  const workspace = (
    <ChatDesk
      compact={!desktopLayout}
      conversations={conversations}
      instanceIndicators={instanceIndicators}
      onClose={(conversationId) => {
        desk.close(conversationId);
        setDeskNotice(null);
      }}
      onFocus={desk.focus}
      onModeChange={(mode: ChatDeskMode) => desk.setMode(mode)}
      renderPane={(conversationId) => {
        const conversation = conversations.find((item) => item.convo_id === conversationId);
        return conversation
          ? <ChatPane active={desk.state.activeConversationId === conversationId} conversation={conversation} key={conversationId} onDeleted={desk.close} />
          : null;
      }}
      state={desk.state}
    />
  );

  return (
    <div className="chats-page">
      <header className="chats-page-header">
        <div className="flex min-w-0 items-center gap-3">
          {!desktopLayout ? <Button aria-label="Chatliste öffnen" onClick={() => setConversationSheetOpen(true)} size="icon" variant="secondary"><List className="size-4" /></Button> : null}
          <div className="min-w-0">
            <h1 className="truncate text-base font-semibold tracking-tight">Chats</h1>
            <p className="hidden truncate text-xs text-muted-foreground sm:block">{desk.state.panes.length} geöffnet · {conversations.filter((item) => !item.archived).length} aktiv</p>
          </div>
        </div>
        <div className="flex gap-2">
          {selected ? <Button aria-label="Chatkontext öffnen" onClick={() => setContextSheetOpen(true)} size="icon" variant="secondary"><Info className="size-4" /></Button> : null}
          <Button aria-label="Chats aktualisieren" onClick={() => void refreshChats()} size="icon" variant="secondary"><RefreshCw className={`size-4 ${catalog.isFetching ? "motion-safe:animate-spin" : ""}`} /></Button>
          <Button aria-label="Neuer Chat" onClick={() => setNewChatOpen(true)}><MessageSquarePlus className="size-4" /><span className="hidden sm:inline">Neuer Chat</span></Button>
        </div>
      </header>

      {!catalog.data?.sidebar.available ? (
        <div className="partial-error" role="status">
          Die native Anti-Gravity-Verbindung ist noch nicht bereit. Lokale Provider-Chats bleiben verfügbar.
        </div>
      ) : null}

      {deskNotice ? <div className="chat-desk-notice" role="status">{deskNotice}</div> : null}
      {bulkDeleteNotice ? <div className="chat-desk-notice" role="status">{bulkDeleteNotice}</div> : null}

      {listConversations.length ? (
        desktopLayout ? (
          <ResizablePanelGroup className="chat-layout" orientation="horizontal">
            <ResizablePanel defaultSize="21" maxSize="32" minSize="16">{conversationList}</ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize="79" minSize="50">{workspace}</ResizablePanel>
          </ResizablePanelGroup>
        ) : <div className="chat-layout is-mobile">{workspace}</div>
      ) : (
        <div className="grid min-h-0 flex-1 place-items-center"><EmptyState action={<Button onClick={() => setNewChatOpen(true)}>Ersten Chat starten</Button>} description="Starte eine Conversation oder arbeite direkt in einem verknüpften Projekt." title="Noch keine Chats" /></div>
      )}

      {!desktopLayout ? (
        <Sheet onOpenChange={setConversationSheetOpen} open={conversationSheetOpen}>
          <SheetContent className="w-[min(92vw,23rem)] p-0" side="left">
            <SheetHeader className="sr-only"><SheetTitle>Chatliste</SheetTitle><SheetDescription>Conversation auswählen oder durchsuchen</SheetDescription></SheetHeader>
            <div className="h-full pt-12">{conversationList}</div>
          </SheetContent>
        </Sheet>
      ) : null}

      {selected ? (
        <Sheet onOpenChange={setContextSheetOpen} open={contextSheetOpen}>
          <SheetContent className="w-[min(92vw,25rem)] p-0" side="right">
            <SheetHeader className="sr-only"><SheetTitle>Chatkontext</SheetTitle><SheetDescription>Status, Projekt und technische Informationen</SheetDescription></SheetHeader>
            <ChatContext conversation={selected} embedded instance={selectedInstance} project={selectedProject} worker={selectedWorker} />
          </SheetContent>
        </Sheet>
      ) : null}

      <NewChatDialog
        onClose={() => setNewChatOpen(false)}
        onCreate={create}
        open={newChatOpen}
        projects={context.projects.data?.projects ?? []}
      />
      <BulkDeleteDialog
        blockedCount={blockedSelectedConversationCount}
        busy={bulkDeleteBusy}
        conversations={deletableSelectedConversations}
        error={bulkDeleteError}
        onConfirm={() => void performBulkDelete()}
        onOpenChange={setBulkDeleteOpen}
        open={bulkDeleteOpen}
        progress={bulkDeleteProgress}
      />
    </div>
  );
}
