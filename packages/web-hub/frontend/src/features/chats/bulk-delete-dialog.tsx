import { LoaderCircle, Trash2 } from "lucide-react";

import type { ConversationCatalogItem } from "@/api/contracts";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

interface BulkDeleteDialogProps {
  blockedCount?: number;
  busy: boolean;
  conversations: ConversationCatalogItem[];
  error?: string | null;
  onConfirm: () => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  progress?: { completed: number; total: number } | null;
}

export function BulkDeleteDialog({
  blockedCount = 0,
  busy,
  conversations,
  error,
  onConfirm,
  onOpenChange,
  open,
  progress,
}: BulkDeleteDialogProps) {
  const archivedCount = conversations.filter((conversation) => conversation.archived).length;
  const activeCount = conversations.length - archivedCount;
  const preview = conversations.slice(0, 4);
  const remaining = conversations.length - preview.length;
  const chatCountLabel = conversations.length === 1
    ? "1 Chat"
    : `${conversations.length} Chats`;
  const activeCountLabel = activeCount === 1 ? "1 aktiver Chat" : `${activeCount} aktive Chats`;
  const archivedCountLabel = archivedCount === 1
    ? "1 archivierter Chat"
    : `${archivedCount} archivierte Chats`;

  return (
    <AlertDialog onOpenChange={(nextOpen) => !busy && onOpenChange(nextOpen)} open={open}>
      <AlertDialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto">
        <AlertDialogHeader>
          <AlertDialogTitle>
            {conversations.length ? `${chatCountLabel} dauerhaft löschen?` : "Keine löschbaren Chats"}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {conversations.length
              ? `${activeCountLabel} und ${archivedCountLabel} werden aus dem Hub entfernt. Native Chats werden zusätzlich aus Anti-Gravity gelöscht; externe Provider-Threads bleiben beim Anbieter bestehen. Diese Aktion kann nicht rückgängig gemacht werden.`
              : "Alle ausgewählten Chats arbeiten gerade und bleiben geschützt."}
          </AlertDialogDescription>
        </AlertDialogHeader>

        {preview.length ? (
          <ul className="max-h-36 space-y-1 overflow-y-auto rounded-md border bg-muted/35 p-3 text-sm" aria-label="Ausgewählte Chats">
            {preview.map((conversation) => (
              <li className="truncate" key={conversation.convo_id}>
                {conversation.title || "Unbenannter Chat"}
              </li>
            ))}
            {remaining > 0 ? <li className="text-muted-foreground">und {remaining} weitere …</li> : null}
          </ul>
        ) : null}

        {blockedCount > 0 ? (
          <div className="partial-error" role="status">
            {blockedCount === 1
              ? "1 laufender Chat bleibt geschützt und wird nicht gelöscht."
              : `${blockedCount} laufende Chats bleiben geschützt und werden nicht gelöscht.`}
          </div>
        ) : null}

        {busy && progress ? (
          <div aria-live="polite" className="flex items-center gap-2 text-sm text-muted-foreground">
            <LoaderCircle className="size-4 motion-safe:animate-spin" />
            {progress.completed} von {progress.total} verarbeitet
          </div>
        ) : null}
        {error ? <div className="partial-error" role="alert">{error}</div> : null}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Abbrechen</AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            disabled={busy || conversations.length === 0}
            onClick={(event) => {
              event.preventDefault();
              onConfirm();
            }}
          >
            {busy ? <LoaderCircle className="size-4 motion-safe:animate-spin" /> : <Trash2 className="size-4" />}
            {busy
              ? "Wird gelöscht …"
              : conversations.length === 0
                ? "Nichts zu löschen"
                : conversations.length === 1
                  ? "Chat löschen"
                  : `${conversations.length} Chats löschen`}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
