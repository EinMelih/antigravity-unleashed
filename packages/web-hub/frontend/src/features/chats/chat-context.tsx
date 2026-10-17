import { Bot, ChevronDown, FolderGit2, Monitor, Server } from "lucide-react";
import { useState } from "react";

import type { AntigravityInstance, ConversationCatalogItem, HubProject, WorkerSnapshot } from "@/api/contracts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { instanceActivityLabel } from "@/features/chats/instance-model";

interface ChatContextProps {
  conversation: ConversationCatalogItem;
  embedded?: boolean;
  instance?: AntigravityInstance;
  project?: HubProject;
  worker?: WorkerSnapshot;
}

export function ChatContext({ conversation, embedded = false, instance, project, worker }: ChatContextProps) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const hubLocal = conversation.convo_id.startsWith("provider-") || conversation.convo_id.startsWith("proxy-");
  const sourceLabel = conversation.source === "codex"
    ? "Codex"
    : conversation.source === "custom" ? "Custom API" : "Anti-Gravity";
  const runtimeLabel = instance
    ? instance.availability === "unreachable"
      ? "Nicht erreichbar"
      : instanceActivityLabel(instance.activity)
    : conversation.archived
      ? "Archiviert"
      : conversation.status === "running" ? "Arbeitet" : "Bereit";
  const runtimeVariant = instance?.availability === "unreachable" || instance?.activity === "error"
    ? "blocked"
    : instance?.activity === "waiting_human" || instance?.binding_status === "mismatch"
      ? "attention"
      : conversation.status === "running" || ["preparing", "sending", "working"].includes(instance?.activity ?? "")
        ? "healthy"
        : "neutral";

  return (
    <aside className={cn("chat-context-panel", embedded && "is-embedded")}>
      <ScrollArea className="h-full">
        <div className="space-y-4 p-4">
          <div>
            <p className="eyebrow">Kontext</p>
            <h2 className="mt-1 font-semibold">Aktiver Chat</h2>
          </div>
          <Card className="shadow-none">
            <CardContent className="p-4">
              <dl className="chat-context-list">
                <div>
                  <dt><Bot className="size-4" /> Status</dt>
                  <dd><Badge variant={runtimeVariant}>{runtimeLabel}</Badge></dd>
                </div>
                <div>
                  <dt><Monitor className="size-4" /> AG-Fenster</dt>
                  <dd>{hubLocal ? "Nicht benötigt" : instance?.instance_id || worker?.window_id || (worker ? worker.target_id : "Bei Bedarf")}</dd>
                </div>
                <div>
                  <dt><FolderGit2 className="size-4" /> Projekt</dt>
                  <dd>{conversation.project_name || "Ohne Projekt"}</dd>
                </div>
                <div>
                  <dt><Server className="size-4" /> Quelle</dt>
                  <dd>{sourceLabel}</dd>
                </div>
              </dl>
            </CardContent>
          </Card>
          {instance?.binding_status === "mismatch" ? (
            <p className="partial-error" role="status">Die Instanz zeigt einen anderen Chat als ihre letzte Hub-Zuordnung. Der Live-Chat wird verwendet.</p>
          ) : null}
          {project ? (
            <Card className="shadow-none">
              <CardHeader className="p-4 pb-2"><CardTitle className="text-sm">{project.github_repo || project.name}</CardTitle></CardHeader>
              <CardContent className="grid gap-3 p-4 pt-0">
                <span className="break-all text-xs text-muted-foreground">{project.integrity_workspace_path || project.path}</span>
                <Button asChild className="w-full" size="sm" variant="secondary"><a href={`#/projects/${project.id}`}>Projektübersicht öffnen</a></Button>
              </CardContent>
            </Card>
          ) : null}
          <Separator />
          <Collapsible onOpenChange={setDetailsOpen} open={detailsOpen}>
            <CollapsibleTrigger asChild>
              <Button className="w-full justify-between" variant="ghost">
                Technische Details
                <ChevronDown className={cn("size-4 transition-transform", detailsOpen && "rotate-180")} />
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <dl className="chat-mobile-details mt-3 px-3">
                <dt>Chat-ID</dt><dd>{conversation.convo_id}</dd>
                <dt>Schritte</dt><dd>{conversation.step_count}</dd>
                <dt>Workspace</dt><dd>{conversation.workspace_path || "–"}</dd>
              </dl>
            </CollapsibleContent>
          </Collapsible>
        </div>
      </ScrollArea>
    </aside>
  );
}
