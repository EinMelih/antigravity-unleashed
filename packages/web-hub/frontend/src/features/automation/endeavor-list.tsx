import { AlertTriangle, CheckCircle2, LoaderCircle, RotateCcw, Sparkles, Square } from "lucide-react";
import { useMemo, useState } from "react";

import type { ControlCampaign, ControlPlanningJob, HubProject } from "@/api/contracts";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { retryPlanningJob, runControlExecutorOnce, stopPlanning } from "@/features/automation/api";
import {
  buildEndeavors,
  type AutomationEndeavor,
} from "@/features/automation/model";

function phaseTone(endeavor: AutomationEndeavor) {
  if (endeavor.phase === "failed") return "blocked" as const;
  if (["needs_answer", "plan_review", "human_review"].includes(endeavor.phase)) {
    return "attention" as const;
  }
  if (["planning", "implementing"].includes(endeavor.phase)) return "accent" as const;
  if (endeavor.phase === "complete") return "healthy" as const;
  return "neutral" as const;
}

function openActionLabel(endeavor: AutomationEndeavor) {
  if (endeavor.phase === "needs_answer") return "Antworten";
  if (endeavor.phase === "human_review") return "PR prüfen";
  if (endeavor.phase === "plan_review") {
    return endeavor.planningJob?.job_type === "plan_amendment"
      ? "Änderung prüfen"
      : "Plan prüfen";
  }
  return "Öffnen";
}

function planningErrorSummary(error: string) {
  const normalized = error.toLowerCase();
  if (
    normalized.includes("linked anti-gravity project") &&
    normalized.includes("did not become visible")
  ) {
    return "Die Projektverknüpfung konnte nicht bestätigt werden. Öffne das Projekt, prüfe die Anti-Gravity-Zuordnung und starte die Planung danach erneut.";
  }
  return "Die KI-Planung konnte nicht abgeschlossen werden. Prüfe die technischen Details oder beende das Vorhaben, bevor du es erneut startest.";
}

export function EndeavorList({
  campaigns,
  jobs,
  onChanged,
  onInspectCampaign,
  onInspectJob,
  onInspectWorkItem,
  projects,
}: {
  campaigns: ControlCampaign[];
  jobs: ControlPlanningJob[];
  onChanged: () => Promise<void> | void;
  onInspectCampaign?: (
    campaign: ControlCampaign,
    planningJob?: ControlPlanningJob,
  ) => void;
  onInspectJob: (job: ControlPlanningJob) => void;
  onInspectWorkItem?: (workItemId: string) => void;
  projects: HubProject[];
}) {
  const [retryingId, setRetryingId] = useState("");
  const [stoppingJob, setStoppingJob] = useState<ControlPlanningJob>();
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState("");
  const endeavors = useMemo(
    () => buildEndeavors({ campaigns, planning_jobs: jobs }, projects),
    [campaigns, jobs, projects],
  );

  if (!endeavors.length) return null;

  function inspect(endeavor: AutomationEndeavor) {
    if (endeavor.phase === "human_review" && endeavor.reviewWorkItemId && onInspectWorkItem) {
      onInspectWorkItem(endeavor.reviewWorkItemId);
      return;
    }
    const planningJob = endeavor.planningJob;
    if (planningJob?.status === "waiting_human") {
      onInspectJob(planningJob);
      return;
    }
    if (endeavor.campaign && onInspectCampaign) {
      onInspectCampaign(endeavor.campaign, planningJob);
      return;
    }
    if (planningJob?.campaign_id) onInspectJob(planningJob);
  }

  async function retry(job: ControlPlanningJob) {
    if (retryingId) return;
    setRetryingId(job.id);
    setError("");
    try {
      await retryPlanningJob(job.id);
      try {
        await runControlExecutorOnce();
      } catch {
        // The durable executor will retry the queued job on its next regular cycle.
      }
      await onChanged();
    } catch (retryError) {
      setError(retryError instanceof Error ? retryError.message : String(retryError));
    } finally {
      setRetryingId("");
    }
  }

  async function stop() {
    if (!stoppingJob || stopping) return;
    setStopping(true);
    setError("");
    try {
      await stopPlanning(stoppingJob);
      try {
        await onChanged();
      } catch {
        // The regular overview refresh will reconcile the already stopped job.
      }
      setStoppingJob(undefined);
    } catch (stopError) {
      setError(stopError instanceof Error ? stopError.message : String(stopError));
    } finally {
      setStopping(false);
    }
  }

  return (
    <section aria-labelledby="endeavors-title" className="grid min-w-0 gap-3">
      <div className="min-w-0">
        <p className="eyebrow">Von der Idee bis zur Prüfung</p>
        <h2 className="mt-1 text-xl font-semibold" id="endeavors-title">
          Vorhaben
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Planung, geordnete PRs und menschliche Prüfung in einem Ablauf.
        </p>
      </div>
      <div className="grid min-w-0 gap-2">
        {endeavors.map((endeavor) => {
          const job = endeavor.planningJob;
          const running = ["planning", "implementing"].includes(endeavor.phase);
          const openable = Boolean(
            (endeavor.phase === "human_review" && endeavor.reviewWorkItemId && onInspectWorkItem) ||
            (job?.status === "waiting_human" && job.campaign_id) ||
            (endeavor.campaign && onInspectCampaign),
          );
          return (
            <article
              className="flex min-w-0 flex-col gap-3 rounded-xl border border-border bg-card p-4 shadow-sm sm:flex-row sm:items-center"
              key={endeavor.id}
            >
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted">
                {endeavor.phase === "failed" ? (
                  <AlertTriangle className="size-4 text-destructive" />
                ) : ["needs_answer", "plan_review", "human_review"].includes(endeavor.phase) ? (
                  <CheckCircle2 className="size-4 text-warning" />
                ) : running ? (
                  <LoaderCircle className="size-4 text-primary motion-safe:animate-spin" />
                ) : (
                  <Sparkles className="size-4 text-muted-foreground" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <strong className="min-w-0 max-w-full truncate text-sm">{endeavor.title}</strong>
                  <Badge variant={phaseTone(endeavor)}>
                    {endeavor.phaseLabel}
                  </Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {endeavor.projectName} · Schritt {endeavor.stage} von 4
                  {job?.waiting_reason === "question" && job.round_number > 0
                    ? ` · Rückfrage ${job.round_number}`
                    : ""}
                </p>
                <p className="mt-1 text-sm text-muted-foreground">{endeavor.description}</p>
                {endeavor.totalPrs > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    <span>{endeavor.completedPrs} von {endeavor.totalPrs} PRs abgeschlossen</span>
                    {endeavor.activePrs > 0 ? <span>{endeavor.activePrs} offen</span> : null}
                  </div>
                ) : null}
                {job?.last_error ? (
                  <div className="mt-2 text-sm text-destructive">
                    <p>{planningErrorSummary(job.last_error)}</p>
                    <details className="mt-1 text-xs text-muted-foreground">
                      <summary className="cursor-pointer">Technische Details</summary>
                      <pre className="mt-1 whitespace-pre-wrap break-words font-mono">{job.last_error}</pre>
                    </details>
                  </div>
                ) : null}
                {job?.agent_gate ? (
                  <p className="mt-2 text-sm text-warning">
                    Eingabe erforderlich: {job.agent_gate.recommendation || job.agent_gate.consequence}
                  </p>
                ) : null}
              </div>
              <div className="flex shrink-0 flex-wrap gap-2">
                {job?.status === "failed" ? (
                  <Button
                    disabled={Boolean(retryingId)}
                    onClick={() => void retry(job)}
                    size="sm"
                    variant="secondary"
                  >
                    {retryingId === job.id ? (
                      <LoaderCircle className="motion-safe:animate-spin" />
                    ) : (
                      <RotateCcw />
                    )}
                    Erneut planen
                  </Button>
                ) : null}
                {openable ? (
                  <Button
                    aria-label={endeavor.phase !== "human_review" && onInspectCampaign &&
                      !["needs_answer", "plan_review"].includes(endeavor.phase)
                      ? `Plan öffnen: ${endeavor.title}`
                      : undefined}
                    onClick={() => inspect(endeavor)}
                    size="sm"
                    variant="secondary"
                  >
                    {openActionLabel(endeavor)}
                  </Button>
                ) : null}
                {job ? (
                  <Button
                    disabled={Boolean(retryingId) || stopping}
                    onClick={() => {
                      setError("");
                      setStoppingJob(job);
                    }}
                    size="sm"
                    variant="ghost"
                  >
                    <Square />
                    {job.job_type === "plan_amendment" ? "Planänderung abbrechen" : "Planung beenden"}
                  </Button>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
      {error && !stoppingJob ? <p className="composer-error" role="alert">{error}</p> : null}
      <AlertDialog
        onOpenChange={(open) => {
          if (!open && !stopping) setStoppingJob(undefined);
        }}
        open={Boolean(stoppingJob)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {stoppingJob?.job_type === "plan_amendment"
                ? "Planänderung abbrechen?"
                : "Planung wirklich beenden?"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {stoppingJob?.job_type === "plan_amendment"
                ? "Die fokussierte Neuplanung wird beendet und der vorherige sichere Campaign-Status wiederhergestellt. Der genehmigte Plan bleibt unverändert."
                : stoppingJob?.waiting_reason === "plan_approval"
                ? "Der erzeugte Planentwurf wird verworfen. Es wird keine Arbeit gestartet."
                : "Die laufende Planung wird beendet. Es wird keine Arbeit gestartet."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {error ? <p className="composer-error" role="alert">{error}</p> : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={stopping}>Zurück</AlertDialogCancel>
            <AlertDialogAction
              disabled={stopping}
              onClick={(event) => {
                event.preventDefault();
                void stop();
              }}
            >
              {stopping ? <LoaderCircle className="motion-safe:animate-spin" /> : null}
              {stoppingJob?.job_type === "plan_amendment" ? "Planänderung abbrechen" : "Planung beenden"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
