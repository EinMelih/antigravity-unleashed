import { useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Plus, RefreshCw, Search } from "lucide-react";
import { useMemo, useState } from "react";

import type { ScheduledTask, ScheduledTaskInput } from "@/api/contracts";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  createScheduledTask,
  deleteScheduledTask,
  restartScheduledTask,
  setScheduledTaskEnabled,
  updateScheduledTask,
} from "@/features/scheduled-tasks/api";
import { filterTasks, type TaskFilter } from "@/features/scheduled-tasks/model";
import { ScheduledTaskDetail } from "@/features/scheduled-tasks/scheduled-task-detail";
import { ScheduledTaskDialog } from "@/features/scheduled-tasks/scheduled-task-dialog";
import { ScheduledTaskList } from "@/features/scheduled-tasks/scheduled-task-list";
import { useScheduledTasksData } from "@/features/scheduled-tasks/use-scheduled-tasks-data";
import { cn } from "@/lib/utils";

export function ScheduledTasksPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editingTask, setEditingTask] = useState<ScheduledTask | null | undefined>();
  const [filter, setFilter] = useState<TaskFilter>("all");
  const [search, setSearch] = useState("");
  const [busyTaskId, setBusyTaskId] = useState("");
  const [operationError, setOperationError] = useState("");
  const data = useScheduledTasksData(selectedId);
  const tasks = useMemo(() => data.tasks.data?.tasks ?? [], [data.tasks.data]);
  const projects = useMemo(() => data.projects.data?.projects ?? [], [data.projects.data]);
  const selected = tasks.find((task) => task.id === selectedId) ?? null;
  const visibleTasks = filterTasks(tasks, projects, filter, search);

  async function refresh() {
    await Promise.all([data.tasks.refetch(), data.projects.refetch(), data.events.refetch()]);
  }

  async function mutate(taskId: string, operation: () => Promise<unknown>) {
    setBusyTaskId(taskId);
    setOperationError("");
    try {
      await operation();
      await queryClient.invalidateQueries({ queryKey: ["scheduled-tasks"] });
      if (selectedId) await queryClient.invalidateQueries({ queryKey: ["scheduled-task-events", selectedId] });
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : String(error));
      throw error;
    } finally {
      setBusyTaskId("");
    }
  }

  async function save(input: ScheduledTaskInput) {
    const taskId = editingTask?.id ?? "new";
    await mutate(taskId, () => editingTask ? updateScheduledTask(editingTask.id, input) : createScheduledTask(input));
  }

  async function toggle(task: ScheduledTask) {
    try {
      await mutate(task.id, () => setScheduledTaskEnabled(task.id, !task.enabled));
    } catch {
      // The visible error panel owns mutation feedback.
    }
  }

  async function restart(task: ScheduledTask) {
    try {
      await mutate(task.id, () => restartScheduledTask(task.id));
    } catch {
      // The visible error panel owns mutation feedback.
    }
  }

  async function remove(task: ScheduledTask) {
    try {
      await mutate(task.id, () => deleteScheduledTask(task.id));
      setSelectedId(null);
    } catch {
      // The visible error panel owns mutation feedback.
    }
  }

  if (data.tasks.isPending) return <LoadingState description="Native Anti-Gravity-Zeitpläne werden geladen." />;
  if (data.tasks.isError) {
    return (
      <ErrorState
        description={`${data.tasks.error instanceof Error ? data.tasks.error.message : String(data.tasks.error)} Starte Anti-Gravity und versuche es erneut.`}
        onRetry={() => void refresh()}
        title="Anti-Gravity Scheduled Tasks nicht bereit"
      />
    );
  }

  return (
    <div className="scheduled-page">
      <header className="scheduled-page-header">
        <div><p className="eyebrow">Automation</p><h1 className="mt-1 text-3xl font-semibold tracking-tight">Scheduled Tasks</h1><p className="mt-2 text-sm text-muted-foreground">Native Anti-Gravity-Zeitpläne zentral erstellen, überwachen und pausieren.</p></div>
        <div className="flex gap-2"><Button aria-label="Tasks aktualisieren" onClick={() => void refresh()} size="icon" variant="secondary"><RefreshCw className="size-4" /></Button><Button onClick={() => setEditingTask(null)}><Plus className="size-4" /> Neuer Task</Button></div>
      </header>

      <div className="scheduled-toolbar">
        <label className="scheduled-search"><Search className="size-4" /><span className="sr-only">Tasks durchsuchen</span><Input className="h-auto border-0 bg-transparent px-0 shadow-none focus-visible:ring-0" onChange={(event) => setSearch(event.target.value)} placeholder="Tasks durchsuchen" type="search" value={search} /></label>
        <div aria-label="Taskfilter" className="automation-filter">
          {([ ["all", "Alle"], ["active", "Aktiv"], ["paused", "Pausiert"], ["error", "Fehler"] ] as const).map(([value, label]) => <button aria-pressed={filter === value} className={cn(filter === value && "is-active")} key={value} onClick={() => setFilter(value)} type="button">{label}</button>)}
        </div>
        <span className="scheduled-count">{visibleTasks.length} von {tasks.length} Tasks · {data.tasks.data?.connected ? "Live" : "Getrennt"}</span>
      </div>

      {operationError ? <div className="partial-error" role="alert">{operationError}<Button className="ml-auto" onClick={() => setOperationError("")} size="sm" variant="ghost">Schließen</Button></div> : null}
      {data.projects.isError ? <div className="partial-error" role="status">Projektliste momentan nicht verfügbar. Bestehende Tasks bleiben sichtbar.</div> : null}

      {visibleTasks.length ? (
        <ScheduledTaskList busyTaskId={busyTaskId} onSelect={setSelectedId} onToggle={toggle} projects={projects} tasks={visibleTasks} />
      ) : (
        <div className="scheduled-empty"><CalendarClock className="size-6" /><h2>{search || filter !== "all" ? "Keine passenden Tasks" : "Noch keine Scheduled Tasks"}</h2><p>{search || filter !== "all" ? "Passe Suche oder Filter an." : "Erstelle den ersten nativen Anti-Gravity-Zeitplan."}</p>{!search && filter === "all" ? <Button onClick={() => setEditingTask(null)}>Ersten Task erstellen</Button> : null}</div>
      )}

      {editingTask !== undefined ? <ScheduledTaskDialog key={editingTask?.id ?? "new"} onClose={() => setEditingTask(undefined)} onSave={save} projects={projects} task={editingTask ?? undefined} /> : null}
      {selected ? <ScheduledTaskDetail busy={busyTaskId === selected.id} events={data.events.data?.events} eventsLoading={data.events.isPending} onClose={() => setSelectedId(null)} onDelete={() => remove(selected)} onEdit={() => setEditingTask(selected)} onRestart={() => restart(selected)} open projects={projects} task={selected} /> : null}
    </div>
  );
}
