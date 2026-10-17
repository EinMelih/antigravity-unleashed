import { Brain, ChevronDown } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { ChatAttachment, ChatHistoryEntry } from "@/api/contracts";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ClaudeThinkingIndicator } from "@/features/chats/claude-thinking";
import {
  formatWorkDuration,
  groupAgentEntries,
  groupHistory,
  workDuration,
} from "@/features/chats/model";
import { RichText } from "@/features/chats/rich-text";
import { ToolActivityGroup } from "@/features/chats/tool-activity-group";
import { cn } from "@/lib/utils";

function attachmentUrl(attachment: ChatAttachment) {
  if (attachment.data?.startsWith("data:image/")) return attachment.data;
  return attachment.file_path
    ? `/api/antigravity/media?path=${encodeURIComponent(attachment.file_path)}`
    : "";
}

function MessageEntry({ entry }: { entry: ChatHistoryEntry }) {
  const assistant = entry.role === "assistant";
  const isWeb = entry.source === "web" || entry.source === "web_dashboard" || entry.source === "hub";
  const [thinkingOpen, setThinkingOpen] = useState(false);
  return (
    <article className={cn("chat-message", assistant ? "is-assistant" : "is-user")}>
      <p className="chat-message-author flex items-center gap-1.5">
        {assistant ? (
          entry.source === "custom"
            ? `Proxy · ${entry.model_name || "API-Modell"}`
            : "Anti-Gravity Agent"
        ) : (
          <>
            <span>Du</span>
            <span
              className={cn(
                "chat-origin-badge inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[0.68rem] font-medium transition-colors",
                isWeb
                  ? "bg-blue-500/15 text-blue-400 border border-blue-500/30"
                  : "bg-purple-500/15 text-purple-400 border border-purple-500/30"
              )}
            >
              {isWeb ? "🌐 Web Hub" : "💻 Desktop App"}
            </span>
          </>
        )}
      </p>
      {assistant && entry.thinking ? (
        <Collapsible className="chat-thinking" onOpenChange={setThinkingOpen} open={thinkingOpen}>
          <CollapsibleTrigger asChild>
            <Button className="h-auto gap-1.5 p-0 text-xs text-muted-foreground hover:bg-transparent hover:text-foreground" variant="ghost">
              <Brain className="size-3.5" /> Denkprozess
              <ChevronDown className={cn("size-3.5 transition-transform", thinkingOpen && "rotate-180")} />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <RichText content={entry.thinking} />
          </CollapsibleContent>
        </Collapsible>
      ) : null}
      <RichText content={entry.content} />
      {entry.attachments?.length ? (
        <div className="chat-message-images">
          {entry.attachments.map((attachment, index) => {
            const url = attachmentUrl(attachment);
            return url ? (
              <a href={url} key={`${attachment.file_path ?? attachment.name}-${index}`} target="_blank" rel="noreferrer">
                <img alt={attachment.file_name || attachment.name || "Angehängtes Bild"} src={url} />
              </a>
            ) : null;
          })}
        </div>
      ) : null}
    </article>
  );
}

function AgentWorkTurn({ announce, entries, live }: { announce: boolean; entries: ChatHistoryEntry[]; live: boolean }) {
  const groups = useMemo(() => groupAgentEntries(entries), [entries]);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [live]);

  const duration = workDuration(entries, live, now);
  return (
    <section className="agent-work-turn">
      {duration !== null || live ? (
        <div className="agent-work-duration" role={live && announce ? "status" : undefined}>
          {live ? (
            <ClaudeThinkingIndicator duration={duration ?? 0} />
          ) : (
            <span>Worked for {formatWorkDuration(duration ?? 0)}</span>
          )}
        </div>
      ) : null}
      <div className="agent-work-content">
        {groups.map((group) => group.type === "tools" ? (
          <ToolActivityGroup entries={group.entries} key={group.key} />
        ) : group.entries[0]?.type === "message" ? (
          <MessageEntry entry={group.entries[0]} key={group.key} />
        ) : null)}
      </div>
    </section>
  );
}

export function ChatHistory({ announce = true, entries, running }: { announce?: boolean; entries: ChatHistoryEntry[]; running: boolean }) {
  const endRef = useRef<HTMLDivElement>(null);
  const groups = useMemo(() => groupHistory(entries), [entries]);

  useEffect(() => {
    if (announce && typeof endRef.current?.scrollIntoView === "function") {
      endRef.current.scrollIntoView({ block: "end" });
    }
  }, [announce, entries.length, running]);

  return (
    <ScrollArea aria-live={announce ? "polite" : "off"} className="chat-history">
      <div className="chat-history-content">
        {groups.length ? groups.map((group, index) =>
          group.type === "agent" ? (
            <AgentWorkTurn announce={announce} entries={group.entries} key={group.key} live={running && index === groups.length - 1} />
          ) : group.entries[0]?.type === "message" ? (
            <MessageEntry entry={group.entries[0]} key={group.key} />
          ) : null,
        ) : (
          <div className="chat-history-empty">Dieser Chat enthält noch keine Nachrichten.</div>
        )}
        {running && groups.at(-1)?.type !== "agent" ? (
          <div className="chat-running-state" role={announce ? "status" : undefined}>
            <ClaudeThinkingIndicator />
          </div>
        ) : null}
        <div ref={endRef} />
      </div>
    </ScrollArea>
  );
}
