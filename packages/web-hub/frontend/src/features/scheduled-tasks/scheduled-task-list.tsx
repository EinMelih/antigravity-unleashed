import { AlertTriangle, CalendarClock, ChevronRight, FolderGit2, LoaderCircle } from "lucide-react";

import type { AntiGravityProject, ScheduledTask } from "@/api/contracts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { friendlySchedule, nextRun, taskProjectName } from "@/features/scheduled-tasks/model";

interface ScheduledTaskListProps {
  busyTaskId: string;
  onSelect: (taskId: string) => void;
  onToggle: (task: ScheduledTask) => Promise<void>;
  projects: AntiGravityProject[];
  tasks: ScheduledTask[];
}

export function ScheduledTaskList({ busyTaskId, onSelect, onToggle, projects, tasks }: ScheduledTaskListProps) {
  return (
    <div className="scheduled-list" role="list">
      {tasks.map((task) => {
        const busy = busyTaskId === task.id;
        return (
          <article className="scheduled-row" key={task.id} role="listitem">
            <button className="scheduled-row-main" onClick={() => onSelect(task.id)} type="button">
              <span className={`scheduled-state-dot ${task.last_error ? "is-error" : task.enabled ? "is-active" : "is-paused"}`} />
              <span className="scheduled-title-cell">
                <span className="flex min-w-0 items-center gap-2">
                  <strong className="truncate">{task.name}</strong>
                  {task.is_bundled ? <Badge variant="neutral">System</Badge> : null}
                </span>
                <span className="truncate">{task.prompt}</span>
              </span>
              <span className="scheduled-meta-cell">
                <CalendarClock className="size-3.5" />
                <span><strong>{friendlySchedule(task.schedule)}</strong><small>Nächster Lauf: {nextRun(task.schedule)}</small></span>
              </span>
              <span className="scheduled-meta-cell is-project">
                <FolderGit2 className="size-3.5" />
                <span><strong>{taskProjectName(task, projects)}</strong><small>{task.all_projects ? "Globaler Task" : "Projektbezogen"}</small></span>
              </span>
              <span className="scheduled-status-cell">
                {task.last_error ? (
                  <Badge variant="blocked"><AlertTriangle className="mr-1 size-3" /> Fehler</Badge>
                ) : (
                  <Badge variant={task.enabled ? "healthy" : "neutral"}>{task.enabled ? "Aktiv" : "Pausiert"}</Badge>
                )}
                <ChevronRight className="size-4 text-muted-foreground" />
              </span>
            </button>
            <div className="scheduled-row-toggle">
              <Button
                aria-pressed={task.enabled}
                disabled={busy}
                onClick={() => void onToggle(task)}
                size="sm"
                variant={task.enabled ? "secondary" : "default"}
              >
                {busy ? <LoaderCircle className="size-4 motion-safe:animate-spin" /> : null}
                {task.enabled ? "Pausieren" : "Aktivieren"}
              </Button>
            </div>
            {task.last_error ? <p className="scheduled-last-error">{task.last_error}</p> : null}
          </article>
        );
      })}
    </div>
  );
}
