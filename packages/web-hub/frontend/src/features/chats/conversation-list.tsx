import { Archive, Bot, CheckSquare2, FolderGit2, MessageSquare, Search, Trash2 } from "lucide-react";

import type { ConversationCatalogItem, ConversationCounts } from "@/api/contracts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  ALL_PROJECTS_FILTER,
  conversationProjectOptions,
  filterConversations,
  formatRelativeTime,
  type ConversationProjectFilter,
  type ConversationScope,
  type ConversationTypeFilter,
} from "@/features/chats/model";
import type { InstanceIndicator } from "@/features/chats/instance-model";
import { cn } from "@/lib/utils";

interface ConversationListProps {
  conversations: ConversationCatalogItem[];
  counts: ConversationCounts;
  instanceIndicators?: Record<string, InstanceIndicator>;
  onSelect: (conversationId: string) => void;
  onBeginSelection?: () => void;
  onCancelSelection?: () => void;
  onRequestDeleteSelected?: () => void;
  onProjectFilterChange?: (project: ConversationProjectFilter) => void;
  scope: ConversationScope;
  projectFilter?: ConversationProjectFilter;
  search: string;
  selectedIds?: ReadonlySet<string>;
  selectedId: string | null;
  selectionBusy?: boolean;
  selectionMode?: boolean;
  typeFilter?: ConversationTypeFilter;
  onScopeChange: (scope: ConversationScope) => void;
  onSearchChange: (search: string) => void;
  onTypeFilterChange?: (type: ConversationTypeFilter) => void;
  onToggleSelected?: (conversationId: string) => void;
  onToggleVisible?: (conversationIds: string[], selected: boolean) => void;
}

const EMPTY_SELECTION: ReadonlySet<string> = new Set<string>();
const noop = () => undefined;

export function ConversationList({
  conversations,
  counts,
  instanceIndicators = {},
  onBeginSelection,
  onCancelSelection = noop,
  onRequestDeleteSelected = noop,
  onProjectFilterChange = noop,
  onScopeChange,
  onSearchChange,
  onSelect,
  onTypeFilterChange = noop,
  onToggleSelected = noop,
  onToggleVisible = noop,
  projectFilter = ALL_PROJECTS_FILTER,
  scope,
  search,
  selectedIds = EMPTY_SELECTION,
  selectedId,
  selectionBusy = false,
  selectionMode = false,
  typeFilter = "all",
}: ConversationListProps) {
  const projectOptions = conversationProjectOptions(
    filterConversations(conversations, scope, "", "project"),
  );
  const effectiveProjectFilter = projectOptions.some(
    (option) => option.value === projectFilter,
  ) ? projectFilter : ALL_PROJECTS_FILTER;
  const visible = filterConversations(
    conversations,
    scope,
    search,
    typeFilter,
    effectiveProjectFilter,
  );
  const selectableVisibleIds = visible
    .filter((conversation) => conversation.status !== "running")
    .map((conversation) => conversation.convo_id);
  const selectedVisibleCount = visible.filter(
    (conversation) => selectedIds.has(conversation.convo_id),
  ).length;
  const selectedSelectableVisibleCount = selectableVisibleIds.filter(
    (id) => selectedIds.has(id),
  ).length;
  const allVisibleSelected = selectableVisibleIds.length > 0
    && selectedSelectableVisibleCount === selectableVisibleIds.length;

  return (
    <aside aria-label="Chatliste" className="chat-list-panel">
      <div className="chat-list-tools">
        <div className="flex items-center gap-2">
          <label className="chat-search relative block min-w-0 flex-1">
            <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 z-10 size-4 -translate-y-1/2 text-muted-foreground" />
            <span className="sr-only">Chats durchsuchen</span>
            <Input
              className="h-9 bg-background pl-9"
              disabled={selectionBusy}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder="Chats durchsuchen"
              type="search"
              value={search}
            />
          </label>
          {!selectionMode && onBeginSelection ? (
            <Button data-chat-selection-begin onClick={onBeginSelection} size="sm" variant="secondary">
              <CheckSquare2 className="size-3.5" /> Auswählen
            </Button>
          ) : null}
        </div>
        <ToggleGroup
          aria-label="Chatfilter"
          className="mt-2 grid w-full grid-cols-3 gap-1"
          disabled={selectionBusy}
          onValueChange={(value) => value && onScopeChange(value as ConversationScope)}
          type="single"
          value={scope}
          variant="outline"
        >
          {([
            ["active", `${counts.visible ?? 0} Chats`],
            ["archived", `${counts.archived ?? 0} archiviert`],
            ["all", "Alle"],
          ] as const).map(([value, label]) => (
            <ToggleGroupItem
              className="h-8 min-w-0 px-2 text-[0.7rem]"
              key={value}
              value={value}
            >
              {label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <ToggleGroup
          aria-label="Chattyp"
          className="mt-2 grid w-full grid-cols-3 gap-1"
          disabled={selectionBusy}
          onValueChange={(value) => value && onTypeFilterChange(value as ConversationTypeFilter)}
          type="single"
          value={typeFilter}
          variant="outline"
        >
          {([
            ["all", "Alle Typen"],
            ["normal", "Normalchats"],
            ["project", "Projektchats"],
          ] as const).map(([value, label]) => (
            <ToggleGroupItem
              className="h-8 min-w-0 px-2 text-[0.7rem]"
              key={value}
              value={value}
            >
              {label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        {typeFilter === "project" ? (
          <div className="mt-2">
            <Select
              disabled={selectionBusy}
              onValueChange={onProjectFilterChange}
              value={effectiveProjectFilter}
            >
              <SelectTrigger aria-label="Projekt filtern" className="h-8 w-full text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_PROJECTS_FILTER}>Alle Projekte</SelectItem>
                {projectOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label} ({option.count})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}
        {selectionMode ? (
          <div aria-label="Chatauswahl" className="mt-2 flex flex-wrap items-center gap-1.5" role="toolbar">
            <span aria-live="polite" className="mr-auto text-xs font-medium text-muted-foreground">
              {selectedVisibleCount} ausgewählt
            </span>
            <Button
              disabled={selectionBusy || selectableVisibleIds.length === 0}
              onClick={() => onToggleVisible(selectableVisibleIds, !allVisibleSelected)}
              size="sm"
              variant="ghost"
            >
              {allVisibleSelected ? "Sichtbare abwählen" : "Sichtbare auswählen"}
            </Button>
            <Button
              disabled={selectionBusy || selectedSelectableVisibleCount === 0}
              onClick={onRequestDeleteSelected}
              size="sm"
              variant="destructive"
            >
              <Trash2 className="size-3.5" /> Löschen
            </Button>
            <Button data-chat-selection-cancel disabled={selectionBusy} onClick={onCancelSelection} size="sm" variant="ghost">
              Abbrechen
            </Button>
          </div>
        ) : null}
      </div>

      <ScrollArea className="chat-list-scroll">
        <div className="space-y-1 p-2">
        {visible.length ? (
          visible.map((conversation) => {
            const isProject = conversation.conversation_type === "project";
            const Icon = conversation.archived
              ? Archive
              : isProject
                ? FolderGit2
                : MessageSquare;
            const indicator = instanceIndicators[conversation.convo_id];
            const running = conversation.status === "running";
            const title = conversation.title || "Unbenannter Chat";
            const rowContent = (
              <>
                <span className="conversation-row-icon">
                  <Icon className="size-4" />
                </span>
                <span className="min-w-0 flex-1 text-left">
                  <span className="block truncate text-sm font-medium">
                    {title}
                  </span>
                  <span className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                    <Badge
                      className="shrink-0 px-1.5 py-0 text-[0.65rem] font-medium"
                      variant={isProject ? "accent" : "neutral"}
                    >
                      {isProject ? "Projekt" : "Normalchat"}
                    </Badge>
                    {conversation.project_name ? (
                      <span className="truncate">{conversation.project_name}</span>
                    ) : null}
                    <span aria-hidden="true">·</span>
                    <span className="shrink-0">{formatRelativeTime(conversation.updated_at)}</span>
                  </span>
                </span>
                {selectionMode && running ? (
                  <Badge className="shrink-0" variant="attention">Arbeitet gerade</Badge>
                ) : indicator ? (
                  <Badge className="max-w-32 shrink-0 truncate" title={indicator.label} variant={indicator.tone}>
                    <Bot className="mr-1 size-3" /> {indicator.label}
                  </Badge>
                ) : running ? (
                  <Badge className="shrink-0" variant="healthy">
                    <Bot className="mr-1 size-3" /> Aktiv
                  </Badge>
                ) : null}
              </>
            );
            if (selectionMode) {
              return (
                <label
                  aria-disabled={running || undefined}
                  className={cn(
                    "conversation-row flex h-auto items-center gap-2 rounded-md px-4 py-2 text-sm transition-colors",
                    running ? "cursor-not-allowed opacity-70" : "cursor-pointer hover:bg-accent",
                    selectedIds.has(conversation.convo_id) && !running && "is-selected",
                  )}
                  key={conversation.convo_id}
                >
                  <Checkbox
                    aria-label={`${title} auswählen`}
                    checked={selectedIds.has(conversation.convo_id)}
                    disabled={selectionBusy || running}
                    onChange={() => onToggleSelected(conversation.convo_id)}
                  />
                  {rowContent}
                </label>
              );
            }
            return (
              <Button
                aria-current={selectedId === conversation.convo_id ? "page" : undefined}
                className={cn(
                  "conversation-row h-auto justify-start whitespace-normal",
                  selectedId === conversation.convo_id && "is-selected",
                )}
                key={conversation.convo_id}
                onClick={() => onSelect(conversation.convo_id)}
                type="button"
                variant="ghost"
              >
                {rowContent}
              </Button>
            );
          })
        ) : (
          <div className="chat-list-empty">
            <MessageSquare className="size-5" />
            <p>Keine passenden Chats.</p>
          </div>
        )}
        </div>
      </ScrollArea>
    </aside>
  );
}
