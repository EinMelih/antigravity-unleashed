import { LoaderCircle, Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";

import type {
  ControlActivationPolicy,
  ControlPlanningDepth,
  ControlPlanningJob,
  HubProject,
} from "@/api/contracts";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { createPlanningJob, runControlExecutorOnce } from "@/features/automation/api";

const candidateDefaults: Record<ControlPlanningDepth, number> = {
  compact: 5,
  balanced: 12,
  deep: 30,
  exhaustive: 100,
};

interface NewEndeavorDialogProps {
  onCreated: (job: ControlPlanningJob) => Promise<void> | void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  projects: HubProject[];
}

export function NewEndeavorDialog({
  onCreated,
  onOpenChange,
  open,
  projects,
}: NewEndeavorDialogProps) {
  const [projectId, setProjectId] = useState("");
  const [wish, setWish] = useState("");
  const [activationPolicy, setActivationPolicy] =
    useState<ControlActivationPolicy>("campaign_wave");
  const [planningDepth, setPlanningDepth] = useState<ControlPlanningDepth>("deep");
  const [maxCandidates, setMaxCandidates] = useState(candidateDefaults.deep);
  const [constraints, setConstraints] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const selectedProjectId = projectId || (open && projects[0] ? String(projects[0].id) : "");

  function reset() {
    setWish("");
    setActivationPolicy("campaign_wave");
    setPlanningDepth("deep");
    setMaxCandidates(candidateDefaults.deep);
    setConstraints("");
    setError("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const numericProjectId = Number(selectedProjectId);
    if (!numericProjectId || wish.trim().length < 10 || busy) return;

    setBusy(true);
    setError("");
    try {
      const job = await createPlanningJob({
        project_id: numericProjectId,
        wish: wish.trim(),
        planning_depth: planningDepth,
        max_candidates: maxCandidates,
        activation_policy: activationPolicy,
        constraints: constraints
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean),
      });
      try {
        await runControlExecutorOnce();
      } catch {
        // The durable executor will pick up the queued job on its next regular cycle.
      }
      await onCreated(job);
      reset();
      onOpenChange(false);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : String(submitError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      onOpenChange={(nextOpen) => {
        if (!busy) onOpenChange(nextOpen);
      }}
      open={open}
    >
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Idee beschreiben</DialogTitle>
          <DialogDescription>
            Beschreibe das Ergebnis. Anti-Gravity untersucht das Repository und erstellt daraus
            einen prüfbaren Plan mit kleinen, geordneten PR-Slices. Noch wird kein Code geändert.
          </DialogDescription>
        </DialogHeader>

        <form className="grid gap-5" onSubmit={(event) => void submit(event)}>
          <div className="hub-field">
            <span>Projekt</span>
            <Select disabled={!projects.length || busy} onValueChange={setProjectId} value={selectedProjectId}>
              <SelectTrigger aria-label="Projekt">
                <SelectValue placeholder="Projekt auswählen" />
              </SelectTrigger>
              <SelectContent>
                {projects.map((project) => (
                  <SelectItem key={project.id} value={String(project.id)}>
                    {project.github_repo || project.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {!projects.length ? (
              <small>
                Zuerst ein <a className="underline" href="#/projects/new">Projekt hinzufügen</a>.
              </small>
            ) : null}
          </div>

          <label className="hub-field">
            <span>Was soll Anti-Gravity umsetzen?</span>
            <Textarea
              autoFocus
              disabled={busy}
              maxLength={50000}
              minLength={10}
              onChange={(event) => setWish(event.target.value)}
              placeholder="Zum Beispiel: Baue eine zugängliche Projektsuche mit Tests, Dokumentation und sicherem Rollout."
              required
              rows={7}
              value={wish}
            />
          </label>

          <fieldset className="grid gap-2">
            <legend className="text-sm font-medium">Nach der Planprüfung</legend>
            <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3">
              <input
                aria-label="Plan einmal freigeben, danach automatisch in sicherer Reihenfolge abarbeiten"
                checked={activationPolicy === "campaign_wave"}
                className="mt-1"
                disabled={busy}
                name="activation-policy"
                onChange={() => setActivationPolicy("campaign_wave")}
                type="radio"
              />
              <span>
                <strong className="block text-sm">
                  Plan einmal freigeben, danach automatisch in sicherer Reihenfolge abarbeiten
                </strong>
                <small className="mt-1 block text-muted-foreground">
                  Abhängigkeiten, Konflikte und Worker-Limits bestimmen die nächste sichere PR-Welle.
                </small>
              </span>
            </label>
            <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3">
              <input
                aria-label="Vor jedem PR noch einmal fragen"
                checked={activationPolicy === "per_candidate"}
                className="mt-1"
                disabled={busy}
                name="activation-policy"
                onChange={() => setActivationPolicy("per_candidate")}
                type="radio"
              />
              <span>
                <strong className="block text-sm">Vor jedem PR noch einmal fragen</strong>
                <small className="mt-1 block text-muted-foreground">
                  Jeder einzelne Slice benötigt später eine eigene Freigabe.
                </small>
              </span>
            </label>
          </fieldset>

          <details className="rounded-lg border border-border p-3">
            <summary className="cursor-pointer text-sm font-medium">Erweiterte Planung</summary>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <div className="hub-field">
                <span>Planungstiefe</span>
                <Select
                  disabled={busy}
                  onValueChange={(value) => {
                    const depth = value as ControlPlanningDepth;
                    setPlanningDepth(depth);
                    setMaxCandidates(candidateDefaults[depth]);
                  }}
                  value={planningDepth}
                >
                  <SelectTrigger aria-label="Planungstiefe">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="compact">Kompakt</SelectItem>
                    <SelectItem value="balanced">Ausgewogen</SelectItem>
                    <SelectItem value="deep">Gründlich</SelectItem>
                    <SelectItem value="exhaustive">Vollständig</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <label className="hub-field">
                <span>Maximale PR-Slices</span>
                <Input
                  disabled={busy}
                  max={100}
                  min={1}
                  onChange={(event) => setMaxCandidates(Number(event.target.value))}
                  type="number"
                  value={maxCandidates}
                />
              </label>
              <label className="hub-field sm:col-span-2">
                <span>Feste Grenzen (optional, eine pro Zeile)</span>
                <Textarea
                  disabled={busy}
                  onChange={(event) => setConstraints(event.target.value)}
                  placeholder="Keine Datenbankmigration\nBestehende API bleibt kompatibel"
                  rows={4}
                  value={constraints}
                />
              </label>
            </div>
          </details>

          {error ? <p className="composer-error" role="alert">{error}</p> : null}

          <DialogFooter>
            <Button disabled={busy} onClick={() => onOpenChange(false)} type="button" variant="secondary">
              Abbrechen
            </Button>
            <Button disabled={busy || !projects.length || wish.trim().length < 10} type="submit">
              {busy ? <LoaderCircle className="motion-safe:animate-spin" /> : <Sparkles />}
              {busy ? "Planung wird gestartet …" : "KI-Planung starten"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
