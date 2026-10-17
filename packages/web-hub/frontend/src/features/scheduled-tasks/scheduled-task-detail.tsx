import { Edit3, LoaderCircle, Play, Trash2 } from "lucide-react";
import { useState } from "react";

import type { AntiGravityProject, ScheduledTask } from "@/api/contracts";
import { EntityDetailDrawer } from "@/components/entity-detail-drawer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { friendlySchedule, nextRun, taskProjectName } from "@/features/scheduled-tasks/model";

interface ScheduledTaskDetailProps {
  busy: boolean;
  events?: Array<Record<string, unknown>>;
  eventsLoading: boolean;
  onClose: () => void;
  onDelete: () => Promise<void>;
  onEdit: () => void;
  onRestart: () => Promise<void>;
  open: boolean;
  projects: AntiGravityProject[];
  task: ScheduledTask;
}

function eventTimestamp(event: Record<string, unknown>) {
  const value = event.timestampMs ?? event.timestamp_ms;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "Zeit unbekannt";
  return new Intl.DateTimeFormat("de-DE", { dateStyle: "short", timeStyle: "medium" }).format(new Date(numeric));
}

export function ScheduledTaskDetail({
  busy,
  events = [],
  eventsLoading,
  onClose,
  onDelete,
  onEdit,
  onRestart,
  open,
  projects,
  task,
}: ScheduledTaskDetailProps) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const tabs = [
    {
      id: "overview",
      label: "Übersicht",
      content: (
        <div className="detail-stack">
          <dl className="detail-grid">
            <div><dt>Status</dt><dd>{task.enabled ? "Aktiv" : "Pausiert"}</dd></div>
            <div><dt>Projekt</dt><dd>{taskProjectName(task, projects)}</dd></div>
            <div><dt>Zeitplan</dt><dd>{friendlySchedule(task.schedule)}</dd></div>
            <div><dt>Nächster Lauf</dt><dd>{nextRun(task.schedule)}</dd></div>
            <div><dt>Stabile ID</dt><dd><code>{task.id}</code></dd></div>
            <div><dt>Cron</dt><dd><code>{task.schedule}</code></dd></div>
          </dl>
          <section className="detail-section"><h3>Prompt</h3><p className="scheduled-detail-prompt">{task.prompt}</p></section>
          {task.last_error ? <section className="detail-section detail-danger"><h3>Letzter Fehler</h3><p>{task.last_error}</p></section> : null}
        </div>
      ),
    },
    {
      id: "events",
      label: `Events (${events.length})`,
      content: eventsLoading ? (
        <div className="chat-history-loading"><LoaderCircle className="size-4 motion-safe:animate-spin" /> Events werden geladen …</div>
      ) : events.length ? (
        <div className="scheduled-events">
          {events.map((event, index) => (
            <article key={`${eventTimestamp(event)}-${index}`}>
              <header><strong>Event {events.length - index}</strong><time>{eventTimestamp(event)}</time></header>
              <pre>{JSON.stringify(event, null, 2)}</pre>
            </article>
          ))}
        </div>
      ) : <p className="text-sm text-muted-foreground">Für diesen Task sind noch keine Events vorhanden.</p>,
    },
  ];

  return (
    <EntityDetailDrawer
      action={
        <div className="scheduled-detail-actions">
          <Button disabled={busy} onClick={onEdit} size="sm" variant="secondary"><Edit3 className="size-4" /> Bearbeiten</Button>
          <Button disabled={busy || !task.enabled} onClick={() => void onRestart()} size="sm" variant="secondary"><Play className="size-4" /> Scheduler neu starten</Button>
          {confirmDelete ? (
            <><span className="text-xs text-muted-foreground">Dauerhaft löschen?</span><Button disabled={busy} onClick={() => void onDelete()} size="sm" variant="destructive">Ja, löschen</Button><Button disabled={busy} onClick={() => setConfirmDelete(false)} size="sm" variant="ghost">Abbrechen</Button></>
          ) : <Button disabled={busy || task.is_bundled} onClick={() => setConfirmDelete(true)} size="sm" variant="ghost"><Trash2 className="size-4" /> Löschen</Button>}
        </div>
      }
      description={`${taskProjectName(task, projects)} · ${friendlySchedule(task.schedule)}`}
      entityKey={task.id}
      onOpenChange={(value) => !value && onClose()}
      open={open}
      status={<><Badge variant={task.last_error ? "blocked" : task.enabled ? "healthy" : "neutral"}>{task.last_error ? "Fehler" : task.enabled ? "Aktiv" : "Pausiert"}</Badge>{task.is_bundled ? <Badge variant="neutral">Systemtask</Badge> : null}</>}
      tabs={tabs}
      title={task.name}
    />
  );
}
