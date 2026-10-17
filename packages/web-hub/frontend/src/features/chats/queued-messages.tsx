import { ArrowRight, ChevronDown, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";

import type { ChatAttachment } from "@/api/contracts";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

export interface QueuedItem {
  id: string;
  message: string;
  attachments: ChatAttachment[];
  createdAt: number;
}

interface QueuedMessagesProps {
  items: QueuedItem[];
  running: boolean;
  onEdit: (item: QueuedItem) => void;
  onDelete: (id: string) => void;
  onSendNow: (item: QueuedItem) => void;
}

export function QueuedMessagesList({
  items,
  running,
  onEdit,
  onDelete,
  onSendNow,
}: QueuedMessagesProps) {
  const [collapsed, setCollapsed] = useState(false);

  if (!items.length) return null;

  return (
    <div className="chat-queued-container" role="region" aria-label="Warteschlange für Nachrichten">
      <header className="chat-queued-header">
        <div className="chat-queued-title">
          <span className="chat-queued-badge">Queued Messages</span>
          <span className="chat-queued-count">{items.length}</span>
          <span className="chat-queued-subtext">
            {running ? "Wird gesendet, sobald der Agent fertig ist" : "Bereit zum Senden"}
          </span>
        </div>
        {items.length > 1 ? (
          <Button
            aria-label={collapsed ? "Warteschlange ausklappen" : "Warteschlange einklappen"}
            className="h-6 w-6 p-0"
            onClick={() => setCollapsed(!collapsed)}
            size="icon"
            type="button"
            variant="ghost"
          >
            <ChevronDown className={`size-4 transition-transform ${collapsed ? "-rotate-90" : ""}`} />
          </Button>
        ) : null}
      </header>

      {!collapsed ? (
        <div className="chat-queued-list">
          {items.map((item) => (
            <div className="chat-queued-item" key={item.id}>
              <div className="chat-queued-content">
                <p className="chat-queued-text">{item.message || "(Nur Anhang)"}</p>
                {item.attachments?.length ? (
                  <div className="chat-queued-attachments">
                    {item.attachments.map((att, idx) => (
                      <span className="chat-queued-thumb" key={`${att.name}-${idx}`}>
                        📷 {att.name || `Bild ${idx + 1}`}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
              <TooltipProvider delayDuration={350}>
                <div className="chat-queued-actions">
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        aria-label="Jetzt sofort senden"
                        className="h-7 w-7 p-0"
                        onClick={() => onSendNow(item)}
                        size="icon"
                        type="button"
                        variant="ghost"
                      >
                        <ArrowRight className="size-3.5" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Sofort senden</TooltipContent>
                  </Tooltip>

                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        aria-label="Nachricht bearbeiten"
                        className="h-7 w-7 p-0"
                        onClick={() => onEdit(item)}
                        size="icon"
                        type="button"
                        variant="ghost"
                      >
                        <Pencil className="size-3.5" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Bearbeiten</TooltipContent>
                  </Tooltip>

                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        aria-label="Aus Warteschlange löschen"
                        className="h-7 w-7 p-0 hover:text-destructive"
                        onClick={() => onDelete(item.id)}
                        size="icon"
                        type="button"
                        variant="ghost"
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Entfernen</TooltipContent>
                  </Tooltip>
                </div>
              </TooltipProvider>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
