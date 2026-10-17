import { AlertTriangle, ArrowUpRight, GitPullRequest, LoaderCircle } from "lucide-react";

import type { ControlTask, HubProject } from "@/api/contracts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface ActiveWorkItemsProps {
  projects: HubProject[];
  tasks: ControlTask[];
}

const statusLabels: Record<string, string> = {
  leased: "Vorbereitung",
  running: "In Arbeit",
  waiting_ci: "Tests laufen",
  waiting_review: "Review offen",
  waiting_human: "Entscheidung nötig",
  repair: "Reparatur",
};

function statusTone(status: string) {
  if (["waiting_human", "repair"].includes(status)) return "attention" as const;
  if (["running", "waiting_ci"].includes(status)) return "accent" as const;
  return "neutral" as const;
}

export function ActiveWorkItems({ projects, tasks }: ActiveWorkItemsProps) {
  const projectNames = new Map(
    projects.map((project) => [project.id, project.github_repo || project.name]),
  );

  return (
    <section aria-labelledby="active-work-title">
      <div className="mb-4 flex items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Laufende Arbeit</p>
          <h2 className="mt-1 text-xl font-semibold" id="active-work-title">
            Aktive Aufgaben
          </h2>
        </div>
        <span className="text-xs text-muted-foreground">{tasks.length} aktiv</span>
      </div>
      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-panel">
        {tasks.length === 0 ? (
          <div className="flex min-h-24 items-center gap-3 px-5 py-6 text-sm text-muted-foreground">
            <LoaderCircle className="size-4" />
            Zurzeit ist kein Work Item aktiv.
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {tasks.slice(0, 8).map((task) => (
              <li className="work-item-row" key={task.id}>
                <span className="work-item-icon">
                  {task.last_error ? (
                    <AlertTriangle className="size-4 text-warning" />
                  ) : (
                    <GitPullRequest className="size-4 text-primary" />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate text-sm font-medium">
                      {projectNames.get(task.project_id) || `Projekt ${task.project_id}`}
                    </p>
                    <Badge variant={statusTone(task.status)}>
                      {statusLabels[task.status] || task.status}
                    </Badge>
                  </div>
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {task.branch_name || task.id}
                    {task.pr_number ? ` · PR #${task.pr_number}` : ""}
                  </p>
                </div>
                <Button asChild aria-label="Aufgabe in Automation öffnen" size="icon" variant="ghost">
                  <a href="#/automation">
                    <ArrowUpRight className="size-4" />
                  </a>
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
