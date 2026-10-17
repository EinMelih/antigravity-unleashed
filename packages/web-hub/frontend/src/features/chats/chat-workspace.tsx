import { Archive, ExternalLink, FolderOpen, LoaderCircle, RotateCcw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import type {
  ChatHistoryEntry,
  ConversationCatalogItem,
  ModelCatalogItem,
} from "@/api/contracts";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { ChatComposer, type ComposerPayload } from "@/features/chats/chat-composer";
import { ChatHistory } from "@/features/chats/chat-history";
import { QueuedMessagesList, type QueuedItem } from "@/features/chats/queued-messages";

export type DeliveryPhase = "idle" | "preparing" | "sending" | "verifying" | "confirmed" | "error";

interface ChatWorkspaceProps {
  activeModel: string;
  activePane?: boolean;
  conversation: ConversationCatalogItem;
  deliveryPhase: DeliveryPhase;
  embedded?: boolean;
  history: ChatHistoryEntry[];
  historyLoading: boolean;
  models: ModelCatalogItem[];
  modelSwitching: boolean;
  modelError?: string;
  mutationBusy: boolean;
  onArchiveChange: (archived: boolean) => Promise<void>;
  onDelete: () => Promise<void>;
  onModelChange: (model: string) => Promise<void>;
  onOpenBrain: () => Promise<void>;
  onOpenWindow: () => Promise<void>;
  onSend: (payload: ComposerPayload) => Promise<void>;
}

const deliveryLabels: Partial<Record<DeliveryPhase, string>> = {
  preparing: "Dediziertes AG-Fenster wird hochgefahren …",
  sending: "Nachricht wird an Anti-Gravity übergeben …",
  verifying: "Zugestellt · Persistenz wird verifiziert …",
  confirmed: "Zustellung bestätigt",
  error: "Zustellung fehlgeschlagen",
};

export function ChatWorkspace({
  activeModel,
  activePane = true,
  conversation,
  deliveryPhase,
  embedded = false,
  history,
  historyLoading,
  models,
  modelSwitching,
  modelError,
  mutationBusy,
  onArchiveChange,
  onDelete,
  onModelChange,
  onOpenBrain,
  onOpenWindow,
  onSend,
}: ChatWorkspaceProps) {
  const titleId = `chat-title-${conversation.convo_id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  const running = conversation.status === "running";
  const hubLocal = conversation.convo_id.startsWith("provider-") || conversation.convo_id.startsWith("proxy-");
  const deliveryLabel = hubLocal && deliveryPhase === "preparing"
    ? "Provider wird vorbereitet …"
    : hubLocal && deliveryPhase === "sending"
      ? "Nachricht wird verarbeitet …"
      : deliveryLabels[deliveryPhase];
  const [queueState, setQueueState] = useState<{
    conversationId: string;
    items: QueuedItem[];
  }>(() => ({ conversationId: conversation.convo_id, items: [] }));
  const [editState, setEditState] = useState<{
    conversationId: string;
    payload: ComposerPayload | null;
  }>(() => ({ conversationId: conversation.convo_id, payload: null }));
  const queuedMessages = useMemo(
    () => queueState.conversationId === conversation.convo_id ? queueState.items : [],
    [conversation.convo_id, queueState],
  );
  const editDraft = editState.conversationId === conversation.convo_id
    ? editState.payload
    : null;

  const setQueuedMessages = useCallback((update: (items: QueuedItem[]) => QueuedItem[]) => {
    setQueueState((current) => ({
      conversationId: conversation.convo_id,
      items: update(current.conversationId === conversation.convo_id ? current.items : []),
    }));
  }, [conversation.convo_id]);

  const setEditDraft = useCallback((payload: ComposerPayload | null) => {
    setEditState({ conversationId: conversation.convo_id, payload });
  }, [conversation.convo_id]);

  useEffect(() => {
    if (!running && deliveryPhase === "idle") {
      const next = queuedMessages[0];
      if (next) {
        const timeoutId = window.setTimeout(() => {
          setQueuedMessages((prev) => prev.filter((item) => item.id !== next.id));
          void onSend({ message: next.message, attachments: next.attachments });
        }, 0);

        return () => window.clearTimeout(timeoutId);
      }
    }
  }, [running, deliveryPhase, queuedMessages, onSend, setQueuedMessages]);

  async function handleComposerSend(payload: ComposerPayload) {
    if (running || deliveryPhase !== "idle") {
      setQueuedMessages((prev) => [
        ...prev,
        {
          id: `queue-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          message: payload.message,
          attachments: payload.attachments,
          createdAt: Date.now(),
        },
      ]);
      return;
    }
    await onSend(payload);
  }

  function handleEditQueueItem(item: QueuedItem) {
    setQueuedMessages((prev) => prev.filter((i) => i.id !== item.id));
    setEditDraft({ message: item.message, attachments: item.attachments });
  }

  function handleDeleteQueueItem(id: string) {
    setQueuedMessages((prev) => prev.filter((i) => i.id !== id));
  }

  function handleSendNowQueueItem(item: QueuedItem) {
    setQueuedMessages((prev) => prev.filter((i) => i.id !== item.id));
    void onSend({ message: item.message, attachments: item.attachments });
  }

  return (
    <section className="chat-workspace" aria-labelledby={titleId}>
      <header className="chat-workspace-header">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={running ? "healthy" : conversation.archived ? "attention" : "neutral"}>
              {conversation.archived ? "Archiviert" : running ? "Aktiv" : "Bereit"}
            </Badge>
            {conversation.project_name ? <span className="text-xs text-muted-foreground">{conversation.project_name}</span> : null}
          </div>
          <h1 className={embedded ? "sr-only" : "mt-2 truncate text-xl font-semibold"} id={titleId}>{conversation.title || "Unbenannter Chat"}</h1>
        </div>
        <TooltipProvider delayDuration={350}>
          <div className="chat-header-actions">
            <Tooltip>
              <TooltipTrigger asChild><Button aria-label="In Anti-Gravity öffnen" disabled={hubLocal || mutationBusy || conversation.archived} onClick={() => void onOpenWindow()} size="icon" variant="secondary"><ExternalLink className="size-4" /></Button></TooltipTrigger>
              <TooltipContent>{hubLocal ? "Lokaler Provider-Chat" : "In Anti-Gravity öffnen"}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild><Button aria-label="Brain-Ordner öffnen" disabled={hubLocal || mutationBusy} onClick={() => void onOpenBrain()} size="icon" variant="secondary"><FolderOpen className="size-4" /></Button></TooltipTrigger>
              <TooltipContent>{hubLocal ? "Kein Brain-Ordner bei lokalen Provider-Chats" : "Arbeitsordner öffnen"}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button aria-label={conversation.archived ? "Chat wiederherstellen" : "Chat archivieren"} disabled={mutationBusy} onClick={() => void onArchiveChange(!conversation.archived)} size="icon" variant="secondary">
                  {conversation.archived ? <RotateCcw className="size-4" /> : <Archive className="size-4" />}
                </Button>
              </TooltipTrigger>
              <TooltipContent>{conversation.archived ? "Chat wiederherstellen" : "Chat archivieren"}</TooltipContent>
            </Tooltip>
            <AlertDialog>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="inline-flex" tabIndex={running ? 0 : undefined}>
                    <AlertDialogTrigger asChild>
                      <Button aria-label="Chat löschen" disabled={mutationBusy || running} size="icon" variant="ghost"><Trash2 className="size-4" /></Button>
                    </AlertDialogTrigger>
                  </span>
                </TooltipTrigger>
                <TooltipContent>{running ? "Laufenden Chat zuerst abschließen" : "Chat dauerhaft löschen"}</TooltipContent>
              </Tooltip>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Chat dauerhaft löschen?</AlertDialogTitle>
                  <AlertDialogDescription>
                    {hubLocal
                      ? `„${conversation.title || "Unbenannter Chat"}“ wird aus dem Hub entfernt. Ein externer Provider-Thread bleibt beim Anbieter bestehen.`
                      : `„${conversation.title || "Unbenannter Chat"}“ wird aus dem Hub und aus Anti-Gravity entfernt.`} Diese Aktion kann nicht rückgängig gemacht werden.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel disabled={mutationBusy}>Abbrechen</AlertDialogCancel>
                  <AlertDialogAction disabled={mutationBusy || running} onClick={() => void onDelete()} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
                    Löschen
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </TooltipProvider>
      </header>

      {conversation.archived ? (
        <div className="chat-archived-banner">
          <Archive className="size-4" />
          <div><strong>Dieser Chat ist archiviert.</strong><p>Der Verlauf bleibt lesbar. Stelle ihn wieder her, bevor du schreibst.</p></div>
          <Button disabled={mutationBusy} onClick={() => void onArchiveChange(false)} size="sm">Wiederherstellen</Button>
        </div>
      ) : null}

      {deliveryPhase !== "idle" ? (
        <div className={`chat-delivery-phase is-${deliveryPhase}`} role="status">
          {!["confirmed", "error"].includes(deliveryPhase) ? <LoaderCircle className="size-4 motion-safe:animate-spin" /> : null}
          {deliveryLabel}
        </div>
      ) : null}

      {historyLoading && !history.length ? (
        <div className="chat-history-loading"><LoaderCircle className="size-5 motion-safe:animate-spin" /> Verlauf wird geladen …</div>
      ) : (
        <ChatHistory announce={activePane} entries={history} running={running && deliveryPhase === "idle"} />
      )}

      <QueuedMessagesList
        items={queuedMessages}
        onDelete={handleDeleteQueueItem}
        onEdit={handleEditQueueItem}
        onSendNow={handleSendNowQueueItem}
        running={running}
      />

      <ChatComposer
        key={conversation.convo_id}
        activeModel={activeModel}
        archived={conversation.archived}
        busy={mutationBusy}
        initialDraft={editDraft}
        models={models}
        modelSwitching={modelSwitching}
        modelError={modelError}
        onClearInitialDraft={() => setEditDraft(null)}
        onModelChange={onModelChange}
        onSend={handleComposerSend}
      />
    </section>
  );
}
