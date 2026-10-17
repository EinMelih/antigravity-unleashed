import { Grid2X2, Square, X } from "lucide-react";
import { useMemo, type CSSProperties, type ReactNode } from "react";

import type { ConversationCatalogItem } from "@/api/contracts";
import { Button } from "@/components/ui/button";
import type {
  ChatDeskMode,
  ChatDeskState,
} from "@/features/chats/chat-desk-model";
import type { InstanceIndicator } from "@/features/chats/instance-model";
import { cn } from "@/lib/utils";

interface ChatDeskProps {
  compact?: boolean;
  conversations: ConversationCatalogItem[];
  instanceIndicators?: Record<string, InstanceIndicator>;
  onClose: (conversationId: string) => void;
  onFocus: (conversationId: string) => void;
  onModeChange: (mode: ChatDeskMode) => void;
  renderPane: (conversationId: string) => ReactNode;
  state: ChatDeskState;
}

const modes: Array<{ icon: typeof Square; label: string; value: ChatDeskMode }> = [
  { icon: Square, label: "Fokus", value: "single" },
  { icon: Grid2X2, label: "Mehrere", value: "grid" },
];

function gridStyle(paneCount: number): CSSProperties {
  const count = Math.max(1, paneCount);
  const columns = Math.ceil(Math.sqrt(count));
  const rows = Math.ceil(count / columns);
  const tracks = (amount: number) => amount === 1
    ? "minmax(0, 1fr)"
    : `repeat(${amount}, minmax(0, 1fr))`;
  return {
    gridTemplateColumns: tracks(columns),
    gridTemplateRows: tracks(rows),
  };
}

export function ChatDesk({
  compact = false,
  conversations,
  instanceIndicators = {},
  onClose,
  onFocus,
  onModeChange,
  renderPane,
  state,
}: ChatDeskProps) {
  const conversationById = useMemo(
    () => new Map(conversations.map((conversation) => [conversation.convo_id, conversation])),
    [conversations],
  );
  const effectiveMode: ChatDeskMode = compact ? "single" : state.mode;
  const panes = state.panes.filter((conversationId) => conversationById.has(conversationId));

  const paneContent = (conversationId: string) => {
    const conversation = conversationById.get(conversationId);
    if (!conversation) return null;
    const title = conversation.title || "Unbenannter Chat";
    const indicator = instanceIndicators[conversationId];
    const visible = effectiveMode === "grid" || conversationId === state.activeConversationId;
    return (
      <article
        aria-hidden={visible ? undefined : true}
        aria-label={`${title} Chatansicht`}
        className={cn(
          "chat-desk-pane",
          !visible && "is-hidden",
          state.activeConversationId === conversationId && "is-active",
        )}
        key={conversationId}
        onPointerDown={() => onFocus(conversationId)}
      >
        <div className="chat-desk-window-bar">
          <span className="chat-desk-window-title">{title}</span>
          <div className="chat-desk-window-meta">
            {indicator ? (
              <span
                className="chat-desk-instance-label"
                data-tone={indicator.tone}
                title={indicator.label}
              >
                {indicator.label}
              </span>
            ) : null}
            <Button
              aria-label={`Ansicht ${title} schließen`}
              onClick={() => onClose(conversationId)}
              size="icon"
              variant="ghost"
            >
              <X className="size-3.5" />
            </Button>
          </div>
        </div>
        <div className="chat-desk-pane-content">{renderPane(conversationId)}</div>
      </article>
    );
  };

  return (
    <section aria-label="Chat-Arbeitsbereich" className="chat-desk">
      <div className="chat-desk-toolbar">
        {!compact ? (
          <div aria-label="Fensterlayout" className="chat-desk-layout-switch" role="group">
            {modes.map(({ icon: Icon, label, value }) => (
              <Button
                aria-pressed={state.mode === value}
                key={value}
                onClick={() => onModeChange(value)}
                size="sm"
                variant={state.mode === value ? "secondary" : "ghost"}
              >
                <Icon className="size-3.5" />
                {label}
              </Button>
            ))}
          </div>
        ) : <span className="chat-desk-mobile-title">Aktive Ansicht</span>}
        <span className="chat-desk-summary">{state.panes.length} geöffnet</span>
      </div>
      <div
        className={cn("chat-desk-stage", `is-${effectiveMode}`)}
        style={effectiveMode === "grid" ? gridStyle(panes.length) : undefined}
      >
        {!panes.length ? (
          <div className="chat-desk-empty">Wähle links einen Chat aus.</div>
        ) : panes.map(paneContent)}
      </div>
    </section>
  );
}
