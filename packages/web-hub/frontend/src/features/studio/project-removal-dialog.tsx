import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, GitBranch, LoaderCircle, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import type { HubProject } from "@/api/contracts";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { archiveProject, deleteProjectGitHubRepository, getProjectRemovalImpact } from "@/features/studio/api";

const dependencyLabels: Record<string, string> = {
  issues: "Aufgaben",
  agent_runs: "Agent-Läufe",
  subtasks: "Teilschritte",
  lessons: "Lessons",
  campaigns: "Kampagnen",
  pr_candidates: "Pull-Request-Pläne",
  work_orders: "Arbeitsaufträge",
  tasks: "Automationsaufgaben",
  planning_jobs: "Planungsläufe",
  attention: "Hinweise",
  proxy_chats: "Lokale Chats",
  deployments: "Deployments",
};

export function ProjectRemovalDialog({ onRemoved, project, trigger }: { onRemoved: () => Promise<void>; project: HubProject; trigger?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [deleteRemote, setDeleteRemote] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const impact = useQuery({
    queryKey: ["project-removal-impact", project.id],
    queryFn: () => getProjectRemovalImpact(project.id),
    enabled: open,
    retry: false,
  });
  const repository = impact.data?.project.github_repository.full_name
    || [project.github_owner, project.github_repo].filter(Boolean).join("/");
  const linkedRepository = Boolean(impact.data?.project.github_repository.linked ?? repository);
  const dependencies = Object.entries(impact.data?.dependencies ?? {}).filter(([, count]) => count.total > 0);
  const remoteConfirmed = !deleteRemote || Boolean(repository && confirmation.trim() === repository);

  function reset() {
    setDeleteRemote(false);
    setConfirmation("");
    setError("");
  }

  async function remove() {
    if (!remoteConfirmed || busy) return;
    setBusy(true);
    setError("");
    try {
      if (deleteRemote) {
        await deleteProjectGitHubRepository(project.id, repository);
      }
      await archiveProject(project.id);
      setOpen(false);
      reset();
      await onRemoved();
    } catch (removeError) {
      setError(removeError instanceof Error ? removeError.message : String(removeError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => { if (!busy) { setOpen(nextOpen); if (!nextOpen) reset(); } }}>
      <DialogTrigger asChild>
        {trigger ?? <Button aria-label={`${project.github_repo || project.name} entfernen`} size="icon" variant="ghost"><Trash2 className="size-4" /></Button>}
      </DialogTrigger>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Projekt aus Anti-Gravity entfernen?</DialogTitle>
          <DialogDescription>„{project.github_repo || project.name}“ verschwindet aus aktiven Ansichten. Verlauf und lokaler Projektordner bleiben erhalten.</DialogDescription>
        </DialogHeader>

        {impact.isPending ? <div className="dialog-progress" role="status"><LoaderCircle className="size-4 motion-safe:animate-spin" /> Abhängigkeiten werden geprüft …</div> : null}
        {impact.isError ? <p className="composer-error" role="alert">Abhängigkeiten konnten nicht geladen werden: {impact.error.message}</p> : null}
        {impact.data ? (
          <div className="grid gap-4">
            <div className="rounded-lg border border-border bg-muted/30 p-4">
              <strong className="text-sm">Das wird geordnet abgeschlossen</strong>
              {dependencies.length ? (
                <ul className="mt-2 grid gap-1 text-sm text-muted-foreground">
                  {dependencies.map(([key, count]) => (
                    <li className="flex justify-between gap-3" key={key}>
                      <span>{dependencyLabels[key] || key}</span>
                      <span>{count.active ?? count.open ?? 0} aktiv · {count.total} gesamt</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="mt-2 text-sm text-muted-foreground">Keine abhängigen Einträge.</p>}
            </div>

            {linkedRepository ? (
              <div className="rounded-lg border border-border p-4">
                <label className="flex items-start gap-3">
                  <Checkbox checked={deleteRemote} onChange={(event) => { setDeleteRemote(event.target.checked); setConfirmation(""); }} />
                  <span><strong className="flex items-center gap-2 text-sm"><GitBranch className="size-4" /> GitHub-Repository ebenfalls löschen</strong><small className="mt-1 block text-muted-foreground">Standardmäßig bleibt {repository} unverändert bestehen.</small></span>
                </label>
                {deleteRemote ? (
                  <div className="mt-4 grid gap-2">
                    <p className="flex gap-2 text-sm text-destructive"><AlertTriangle className="mt-0.5 size-4 shrink-0" /> GitHub-Löschung ist dauerhaft. Tippe zur Bestätigung exakt <strong>{repository}</strong>.</p>
                    <Input aria-label="GitHub-Repository bestätigen" autoComplete="off" onChange={(event) => setConfirmation(event.target.value)} placeholder={repository} value={confirmation} />
                  </div>
                ) : null}
              </div>
            ) : null}
            <p className="text-xs text-muted-foreground">Nicht gelöscht: lokaler Ordner, lokales Git-Repository und Hub-Historie.</p>
          </div>
        ) : null}
        {error ? <p className="composer-error" role="alert">{error}</p> : null}
        <DialogFooter>
          <Button disabled={busy} onClick={() => setOpen(false)} variant="secondary">Abbrechen</Button>
          <Button disabled={busy || !impact.data || !remoteConfirmed} onClick={() => void remove()} variant="destructive">
            {busy ? <LoaderCircle className="size-4 motion-safe:animate-spin" /> : <Trash2 className="size-4" />}
            {deleteRemote ? "GitHub löschen & entfernen" : "Aus Hub entfernen"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
