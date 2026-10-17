import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Check, LoaderCircle, Network, PencilLine, Play, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";

import type {
  ControlCampaign,
  ControlPlanningJob,
  ControlPlanningQuestion,
  ControlPolicy,
} from "@/api/contracts";
import { ApiError } from "@/api/errors";
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
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import {
  activateCampaignWave,
  answerPlanningQuestion,
  approveCampaign,
  decidePlanAmendment,
  getCampaignReadiness,
  getPlanAmendment,
  runControlExecutorOnce,
  startPlanAmendment,
  stopPlanning,
  updateControlPolicy,
} from "@/features/automation/api";
import { PlanAmendmentReview } from "@/features/automation/plan-amendment-review";
import { domainStatusLabel } from "@/lib/domain-labels";

const missingLabels: Record<string, string> = {
  goal: "Ziel fehlt",
  non_goals: "Nicht-Ziele fehlen",
  base_sha: "Repository-Baseline fehlt",
  alternatives: "Mindestens zwei echte Lösungsalternativen fehlen",
  review_strategy: "Review-Strategie fehlt",
  decision_ledger: "Entscheidungsprotokoll fehlt",
  pr_candidates: "Geplante PRs fehlen",
  candidate_contracts: "PR-Verträge fehlen",
  candidate_acceptance_criteria_invalid: "Akzeptanzkriterien sind unvollständig",
  candidate_verification_contract: "Test- oder Definition-of-Done-Vertrag fehlt",
  unresolved_questions: "Offene Planungsfragen",
  pivotal_fork: "Zentrale Architekturentscheidung fehlt",
  success_metrics: "Erfolgskriterien fehlen",
  rollout_plan: "Rollout-Plan fehlt",
  rollback_plan: "Rollback-Plan fehlt",
  repository_map: "Repository Map fehlt",
  design_document: "Design-Dokument fehlt",
  plan_simulation_artifact: "Gespeicherte Plan-Simulation fehlt",
  adr: "Architekturentscheidung fehlt",
  acceptance_matrix: "Akzeptanzmatrix fehlt",
  candidate_limit_exceeded: "PR-Limit überschritten",
  stale_base_sha: "Repository hat sich seit der Planung geändert",
  cyclic_pr_dependencies: "PR-Abhängigkeiten enthalten einen Zyklus",
};

const gateLabels: Record<string, string> = {
  outcome_contract: "Ziel und Erfolg",
  pivotal_fork: "Zentrale Entscheidung",
  repository_grounding: "Repository-Kontext",
  decision_ledger: "Entscheidungsprotokoll",
  alternatives_tradeoffs: "Alternativen und Abwägung",
  candidate_contracts: "PR-Verträge",
  dependency_conflict_simulation: "Reihenfolge und Konflikte",
  verification_release: "Prüfung und Auslieferung",
};

const openQuestionStates = new Set(["open", "researching", "contradiction"]);
const amendmentSourceStates = new Set(["approved", "active", "paused"]);
const minimumAmendmentTextLength = 12;

function isFutureCandidate(candidate: ControlCampaign["pr_candidates"][number]) {
  return candidate.status === "ready" && !candidate.work_order && !candidate.task;
}

function candidateTitle(campaign: ControlCampaign, candidateId: string) {
  return campaign.pr_candidates.find((candidate) => candidate.id === candidateId)?.title || candidateId;
}

function statusInSentence(value: string | null | undefined) {
  return domainStatusLabel(value, "Im vorherigen sicheren Zustand").toLocaleLowerCase("de-DE");
}

function QuestionAnswer({
  busy,
  onAnswer,
  question,
}: {
  busy: boolean;
  onAnswer: (question: ControlPlanningQuestion, answer: string) => Promise<void>;
  question: ControlPlanningQuestion;
}) {
  const [answer, setAnswer] = useState(question.answer || "");
  return (
    <article className="grid gap-2 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="attention">Frage offen</Badge>
        <span className="text-xs text-muted-foreground">{question.branch}</span>
      </div>
      <strong className="text-sm">{question.question}</strong>
      {question.rationale ? <p className="text-xs text-muted-foreground">{question.rationale}</p> : null}
      <Textarea
        aria-label={`Antwort auf: ${question.question}`}
        disabled={busy}
        onChange={(event) => setAnswer(event.target.value)}
        placeholder="Entscheidung und wichtigen Grund festhalten"
        rows={3}
        value={answer}
      />
      <Button
        className="justify-self-start"
        disabled={busy || answer.trim().length < 2}
        onClick={() => void onAnswer(question, answer.trim())}
        size="sm"
        type="button"
        variant="secondary"
      >
        Antwort speichern
      </Button>
    </article>
  );
}

export function CampaignPlanDialog({
  campaign,
  onChanged,
  onOpenChange,
  open,
  planningJob,
  policy,
}: {
  campaign?: ControlCampaign;
  onChanged: () => Promise<void> | void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  planningJob?: ControlPlanningJob;
  policy: ControlPolicy;
}) {
  const [busy, setBusy] = useState(false);
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [stopConfirmationOpen, setStopConfirmationOpen] = useState(false);
  const [error, setError] = useState("");
  const [answerNotice, setAnswerNotice] = useState<{
    tone: "success" | "warning";
    text: string;
  }>();
  const [amendmentNotice, setAmendmentNotice] = useState("");
  const [amendmentFormOpen, setAmendmentFormOpen] = useState(false);
  const [amendmentReason, setAmendmentReason] = useState("");
  const [amendmentRequestedChange, setAmendmentRequestedChange] = useState("");
  const [selectedAmendmentBranches, setSelectedAmendmentBranches] = useState<string[]>([]);
  const [amendmentStartNotice, setAmendmentStartNotice] = useState("");
  const campaignId = campaign?.id || "";
  const amendmentSummary = campaign?.amendments?.find(
    (amendment) => amendment.id === planningJob?.amendment_id,
  ) ?? campaign?.amendments?.find((amendment) => ["planning", "review"].includes(amendment.status));
  const amendmentId = planningJob?.amendment_id || amendmentSummary?.id || "";
  const amendmentMode = Boolean(
    planningJob?.job_type === "plan_amendment" || amendmentId,
  );
  const questionMode = Boolean(
    (
      planningJob?.status === "waiting_human" &&
      planningJob.waiting_reason === "question"
    ) || answerNotice,
  );
  const amendmentQuestionMode = amendmentMode && questionMode;
  const amendmentReviewMode = amendmentMode && !questionMode && Boolean(
    planningJob?.waiting_reason === "amendment_approval" || amendmentSummary?.status === "review",
  );
  const canAmendCampaign = Boolean(
    campaign && amendmentSourceStates.has(campaign.status) && !amendmentSummary,
  );
  const needsReadiness = campaign?.status === "draft" || canAmendCampaign;
  const amendmentQuery = useQuery({
    queryKey: ["plan-amendment", amendmentId],
    queryFn: () => getPlanAmendment(amendmentId),
    enabled: open && amendmentReviewMode && Boolean(amendmentId),
  });
  const readinessQuery = useQuery({
    queryKey: ["campaign-readiness", campaignId, campaign?.version, campaign?.base_sha],
    queryFn: () => getCampaignReadiness(campaignId),
    enabled: open && !questionMode && Boolean(campaignId) && needsReadiness,
  });
  const readiness = readinessQuery.data;
  const loading = open && needsReadiness && readinessQuery.isPending;
  const openQuestions = useMemo(
    () => (campaign?.questions ?? []).filter((question) => openQuestionStates.has(question.status)),
    [campaign?.questions],
  );
  const futureCandidates = useMemo(
    () => (campaign?.pr_candidates ?? []).filter(isFutureCandidate),
    [campaign?.pr_candidates],
  );
  const activeQuestion = questionMode
    ? campaign?.questions?.find((question) => question.id === planningJob?.active_question_id)
    : undefined;

  if (!campaign) return null;
  const activeCampaign = campaign;
  const profile = activeCampaign.profile;
  const activationPolicy = profile?.activation_policy || "per_candidate";
  const automatic = ["campaign_wave", "autopilot"].includes(activationPolicy);
  const simulation = readiness?.simulation;
  const canApprove = activeCampaign.status === "draft" && Boolean(
    readiness?.ready && readiness.plan_signature,
  );
  const canStart = ["approved", "active"].includes(activeCampaign.status) && automatic && !policy.paused;
  const completed = ["completed", "cancelled"].includes(activeCampaign.status);
  const exactAmendmentIdentityAvailable = Boolean(
    readiness?.plan_signature && typeof readiness.plan_signature_version === "number",
  );
  const amendmentFormValid =
    amendmentReason.trim().length >= minimumAmendmentTextLength &&
    amendmentRequestedChange.trim().length >= minimumAmendmentTextLength &&
    exactAmendmentIdentityAvailable;

  if (amendmentReviewMode) {
    return (
      <PlanAmendmentReview
        amendment={amendmentQuery.data ?? amendmentSummary}
        busy={busy}
        canCancel={Boolean(planningJob)}
        campaign={activeCampaign}
        detailVerified={amendmentQuery.isSuccess && Boolean(amendmentQuery.data)}
        error={error || (amendmentQuery.isError
          ? amendmentQuery.error instanceof Error
            ? amendmentQuery.error.message
            : "Planänderung konnte nicht geladen werden."
          : "")}
        loading={amendmentQuery.isPending}
        notice={amendmentNotice}
        onApprove={() => decideAmendment("approved")}
        onCancel={cancelAmendment}
        onClose={() => onOpenChange(false)}
        onReject={() => decideAmendment("rejected")}
        open={open}
      />
    );
  }

  async function decideAmendment(decision: "approved" | "rejected") {
    const selectedAmendment = decision === "approved"
      ? amendmentQuery.data
      : amendmentQuery.data ?? amendmentSummary;
    if (!selectedAmendment || busy) return;
    setBusy(true);
    setError("");
    try {
      await decidePlanAmendment(
        selectedAmendment,
        decision,
        decision === "approved"
          ? "Geprüften Zielplan als neuen Campaign-Entwurf übernehmen."
          : "Vorgeschlagene Planänderung nach menschlicher Prüfung ablehnen.",
      );
      setAmendmentNotice(
        decision === "approved"
          ? `Planänderung übernommen. Plan v${selectedAmendment.proposed_version} ist jetzt ein Entwurf und braucht noch die normale Planfreigabe.`
          : `Planänderung abgelehnt. Der Plan ist wieder ${statusInSentence(selectedAmendment.prior_campaign_status)}.`,
      );
      try {
        await onChanged();
      } catch {
        setError("Die Entscheidung wurde gespeichert, aber die Ansicht konnte nicht sofort aktualisiert werden.");
      }
    } catch (decisionError) {
      if (decisionError instanceof ApiError && decisionError.status === 409) {
        setAmendmentNotice("");
        setError("Die Planänderung hat sich seit deiner Ansicht geändert. Die neuesten Prüfsummen wurden geladen; bitte prüfe Ausgangs- und Zielplan erneut.");
        try {
          await amendmentQuery.refetch();
        } catch {
          // The stale message remains actionable even when the immediate refetch fails.
        }
        try {
          await onChanged();
        } catch {
          // The regular overview refresh will reconcile the stale decision state.
        }
      } else {
        setError(decisionError instanceof Error ? decisionError.message : String(decisionError));
      }
    } finally {
      setBusy(false);
    }
  }

  async function cancelAmendment() {
    if (!planningJob || busy) {
      setError("Der Planungsauftrag dieser Planänderung ist nicht mehr verfügbar. Bitte Ansicht aktualisieren.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await stopPlanning(
        planningJob,
        "Planänderung und fokussierte Neuplanung abbrechen.",
      );
      const restoredStatus = statusInSentence(amendmentSummary?.prior_campaign_status);
      setAmendmentNotice(`Planänderung abgebrochen. Der Plan ist wieder ${restoredStatus}.`);
      try {
        await onChanged();
      } catch {
        setError("Die Planänderung wurde abgebrochen, aber die Ansicht konnte nicht sofort aktualisiert werden.");
      }
    } catch (cancelError) {
      setError(cancelError instanceof Error ? cancelError.message : String(cancelError));
    } finally {
      setBusy(false);
    }
  }

  async function requestPlanAmendment() {
    if (!canAmendCampaign || busy || !readiness?.plan_signature) return;
    if (typeof readiness.plan_signature_version !== "number") {
      setError("Die exakte Signaturversion fehlt. Bitte Planprüfung neu laden.");
      return;
    }
    setBusy(true);
    setError("");
    setAmendmentStartNotice("");
    try {
      await startPlanAmendment(activeCampaign.id, {
        reason: amendmentReason.trim(),
        focus: {
          branches: selectedAmendmentBranches,
          requested_change: amendmentRequestedChange.trim(),
        },
        expected_version: activeCampaign.version,
        expected_base_sha: activeCampaign.base_sha,
        expected_plan_signature: readiness.plan_signature,
        expected_plan_signature_version: readiness.plan_signature_version,
      });
      setAmendmentFormOpen(false);
      setAmendmentStartNotice(
        "Planänderung gestartet. Der Plan wird pausiert; dieselbe KI plant den betroffenen Teil weiter und stellt dir bei Bedarf pro Runde höchstens eine Rückfrage.",
      );
      try {
        await onChanged();
      } catch {
        setError("Die Planänderung wurde gestartet, aber die Ansicht konnte nicht sofort aktualisiert werden.");
      }
    } catch (startError) {
      if (startError instanceof ApiError && startError.status === 409) {
        setError("Der Plan hat sich seit deiner Ansicht geändert. Die exakte Plan-Identität wurde neu geladen; bitte prüfe sie und starte die Änderung erneut.");
        try {
          await readinessQuery.refetch();
        } catch {
          // Keep the stale warning visible when the immediate refetch is unavailable.
        }
        try {
          await onChanged();
        } catch {
          // The next overview refresh will reconcile the source Campaign.
        }
      } else {
        setError(startError instanceof Error ? startError.message : String(startError));
      }
    } finally {
      setBusy(false);
    }
  }

  function toggleAmendmentBranch(candidateId: string) {
    setSelectedAmendmentBranches((current) => current.includes(candidateId)
      ? current.filter((id) => id !== candidateId)
      : [...current, candidateId]);
  }

  async function answerQuestion(question: ControlPlanningQuestion, answer: string) {
    setBusy(true);
    setError("");
    setAnswerNotice(undefined);
    try {
      await answerPlanningQuestion(question.id, answer);
      let warning = "";
      try {
        await runControlExecutorOnce();
      } catch {
        warning = "Antwort gespeichert. Die Planung ist eingeplant, konnte aber nicht sofort fortgesetzt werden. Der Hintergrunddienst übernimmt automatisch.";
      }
      try {
        await onChanged();
      } catch {
        warning = warning || "Antwort gespeichert. Die Planung läuft weiter, aber die Ansicht konnte nicht sofort aktualisiert werden.";
      }
      setAnswerNotice({
        tone: warning ? "warning" : "success",
        text: warning || "Antwort gespeichert. Die Planung läuft weiter.",
      });
    } catch (answerError) {
      setError(answerError instanceof Error ? answerError.message : String(answerError));
    } finally {
      setBusy(false);
    }
  }

  async function approveAndStart() {
    if (busy || completed || (!canApprove && !canStart)) return;
    setBusy(true);
    setError("");
    let executorUnavailable = false;
    try {
      if (activeCampaign.status === "draft") {
        const viewedSignature = readiness?.plan_signature;
        if (!viewedSignature) {
          setError("Die angezeigte Plan-Signatur fehlt. Bitte Planprüfung neu laden.");
          return;
        }
        await approveCampaign(activeCampaign, viewedSignature);
      }
      if (!policy.paused && automatic) {
        if (activationPolicy === "autopilot") {
          if (policy.mode !== "autopilot") await updateControlPolicy("autopilot");
        } else if (!["campaign", "autopilot"].includes(policy.mode)) {
          await updateControlPolicy("campaign");
        }
        await activateCampaignWave(activeCampaign.id);
        try {
          await runControlExecutorOnce();
        } catch (tickError) {
          executorUnavailable = true;
          setError(
            `Work Orders sind eingeplant, aber der Executor konnte gerade nicht gestartet werden: ${
              tickError instanceof Error ? tickError.message : String(tickError)
            }`,
          );
        }
      }
      await onChanged();
      if (!executorUnavailable) onOpenChange(false);
    } catch (actionError) {
      if (
        actionError instanceof ApiError &&
        actionError.status === 409 &&
        actionError.code === "stale_plan_signature"
      ) {
        setConfirmationOpen(false);
        setError("Der Plan hat sich seit deiner Ansicht geändert. Die Planprüfung wurde neu geladen; bitte prüfe und bestätige die neue Signatur.");
        await readinessQuery.refetch();
      } else {
        setError(actionError instanceof Error ? actionError.message : String(actionError));
      }
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function stopQuestionPlanning() {
    if (!planningJob || busy) return;
    setBusy(true);
    setError("");
    try {
      await stopPlanning(planningJob);
      try {
        await onChanged();
      } catch {
        // The regular overview refresh will reconcile the already stopped job.
      }
      setStopConfirmationOpen(false);
      onOpenChange(false);
    } catch (stopError) {
      setError(stopError instanceof Error ? stopError.message : String(stopError));
    } finally {
      setBusy(false);
    }
  }

  const actionLabel = policy.paused
    ? campaign.status === "draft"
      ? "Plan freigeben (Automation bleibt pausiert)"
      : "Automation ist pausiert"
    : campaign.status === "draft"
      ? automatic
        ? "Plan freigeben und Abarbeitung starten"
        : "Plan freigeben"
      : campaign.status === "paused"
        ? "Campaign ist pausiert"
        : automatic
        ? campaign.status === "active"
          ? "Nächste sichere Wave starten"
          : "Abarbeitung starten"
        : "Plan ist freigegeben";

  if (questionMode) {
    return (
      <>
        <Dialog
          onOpenChange={(nextOpen) => {
            if (busy) return;
            if (!nextOpen) setAnswerNotice(undefined);
            onOpenChange(nextOpen);
          }}
          open={open}
        >
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>
                {amendmentQuestionMode ? "Rückfrage zur Planänderung" : "Rückfrage zur Planung"}
              </DialogTitle>
              <DialogDescription>{campaign.goal}</DialogDescription>
            </DialogHeader>
            <div className="grid gap-4">
              {planningJob && planningJob.round_number > 0 ? (
                <p className="text-xs text-muted-foreground">Rückfrage {planningJob.round_number}</p>
              ) : null}
              {amendmentQuestionMode ? (
                <p className="text-xs text-muted-foreground">
                  Nur der betroffene Plan-Zweig wird neu geklärt; der übrige freigegebene Plan bleibt unverändert.
                </p>
              ) : null}
              {answerNotice ? (
                <p
                  className={answerNotice.tone === "warning"
                    ? "rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm text-warning"
                    : "rounded-lg border border-success/30 bg-success/5 p-3 text-sm text-success"}
                  role="status"
                >
                  {answerNotice.text}
                </p>
              ) : activeQuestion ? (
                <QuestionAnswer busy={busy} onAnswer={answerQuestion} question={activeQuestion} />
              ) : (
                <p className="composer-error" role="alert">
                  Die aktive Rückfrage ist nicht mehr verfügbar. Bitte aktualisiere die Ansicht.
                </p>
              )}
              {error && !stopConfirmationOpen ? <p className="composer-error" role="alert">{error}</p> : null}
            </div>
            <DialogFooter>
              <Button
                disabled={busy}
                onClick={() => {
                  setError("");
                  setStopConfirmationOpen(true);
                }}
                variant="ghost"
              >
                {amendmentQuestionMode ? "Planänderung abbrechen" : "Planung beenden"}
              </Button>
              <Button
                disabled={busy}
                onClick={() => {
                  setAnswerNotice(undefined);
                  onOpenChange(false);
                }}
                variant="secondary"
              >
                Schließen
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        <AlertDialog
          onOpenChange={(nextOpen) => { if (!busy) setStopConfirmationOpen(nextOpen); }}
          open={stopConfirmationOpen}
        >
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>
                {amendmentQuestionMode ? "Planänderung abbrechen?" : "Planung wirklich beenden?"}
              </AlertDialogTitle>
              <AlertDialogDescription>
                {amendmentQuestionMode
                  ? "Die fokussierte Neuplanung wird beendet und der vorherige sichere Planstatus wiederhergestellt. Der freigegebene Plan bleibt unverändert."
                  : "Die Rückfrage und der unfertige Planentwurf werden beendet. Es wird keine Arbeit gestartet."}
              </AlertDialogDescription>
            </AlertDialogHeader>
            {error ? <p className="composer-error" role="alert">{error}</p> : null}
            <AlertDialogFooter>
              <AlertDialogCancel disabled={busy}>Zurück</AlertDialogCancel>
              <AlertDialogAction
                disabled={busy}
                onClick={(event) => {
                  event.preventDefault();
                  void stopQuestionPlanning();
                }}
              >
                {busy ? <LoaderCircle className="motion-safe:animate-spin" /> : null}
                {amendmentQuestionMode ? "Planänderung abbrechen" : "Planung beenden"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </>
    );
  }

  return (
    <Dialog onOpenChange={(nextOpen) => { if (!busy) onOpenChange(nextOpen); }} open={open}>
      <DialogContent className="max-h-[92svh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Plan prüfen: {campaign.title}</DialogTitle>
          <DialogDescription>{campaign.goal}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-5">
          <section className="grid gap-3 rounded-xl border border-border bg-muted/25 p-4 sm:grid-cols-[1fr_auto] sm:items-center">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                {loading ? (
                  <LoaderCircle className="size-4 motion-safe:animate-spin" />
                ) : readiness?.ready ? (
                  <ShieldCheck className="size-4 text-success" />
                ) : (
                  <AlertTriangle className="size-4 text-warning" />
                )}
                <strong className="text-sm">
                  {loading
                    ? "Plan wird geprüft …"
                    : readiness?.ready
                      ? "Plan ist bereit"
                      : "Plan braucht noch Entscheidungen"}
                </strong>
                {readiness ? (
                  <Badge variant={readiness.ready ? "healthy" : "attention"}>
                    {readiness.gates?.length
                      ? `${readiness.gates.filter((gate) => gate.passed).length}/${readiness.gates.length} Gates`
                      : `${Math.round(readiness.score)} %`}
                  </Badge>
                ) : null}
                <Badge variant="neutral">
                  {automatic ? "Automatische sichere Reihenfolge" : "Freigabe vor jedem PR"}
                </Badge>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                Plan v{campaign.version} · Basis {campaign.base_sha.slice(0, 12) || "nicht gesetzt"} · {campaign.pr_candidates.length} geplante PRs
              </p>
              {readiness?.plan_signature ? (
                <p className="mt-1 break-all font-mono text-[0.68rem] text-muted-foreground">
                  Signatur v{readiness.plan_signature_version ?? 1}: {readiness.plan_signature}
                </p>
              ) : null}
            </div>
            {simulation ? (
              <div className="flex items-center gap-2 text-sm font-medium">
                <Network className="size-4" />
                {simulation.max_wave} sichere {simulation.max_wave === 1 ? "Welle" : "Wellen"}
              </div>
            ) : null}
          </section>

          {readiness?.missing.length ? (
            <section className="grid gap-2">
              <h3 className="text-sm font-semibold">Vor der Freigabe noch offen</h3>
              <ul className="grid gap-2 sm:grid-cols-2">
                {readiness.missing.map((missing) => (
                  <li className="flex items-start gap-2 rounded-lg border border-warning/30 p-3 text-sm" key={missing}>
                    <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
                    {missingLabels[missing] || missing}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {readiness?.gates?.length ? (
            <details className="rounded-lg border border-border p-3">
              <summary className="cursor-pointer text-sm font-medium">Alle Plan-Gates prüfen</summary>
              <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                {readiness.gates.map((gate) => (
                  <li className="rounded-md bg-muted/40 p-2 text-xs" key={gate.key}>
                    <span className="flex items-center gap-2 font-medium">
                      {gate.passed
                        ? <Check className="size-4 text-success" />
                        : <AlertTriangle className="size-4 text-warning" />}
                      {gateLabels[gate.key] || gate.key}
                    </span>
                    <span className="mt-1 block text-muted-foreground">
                      {gate.passed
                        ? gate.evidence.join(" · ") || "Erfüllt"
                        : gate.missing.map((item) => missingLabels[item] || item).join(" · ")}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}

          {openQuestions.length ? (
            <section className="grid gap-3">
              <div>
                <h3 className="text-sm font-semibold">Deine Entscheidung wird benötigt</h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  Antworten verändern den Planstand; danach wird Readiness erneut geprüft.
                </p>
              </div>
              {openQuestions.map((question) => (
                <QuestionAnswer busy={busy} key={question.id} onAnswer={answerQuestion} question={question} />
              ))}
            </section>
          ) : null}

          <section className="grid gap-3">
            <div>
              <h3 className="text-sm font-semibold">Reihenfolge und sichere Wellen</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                Abhängige oder konfliktbehaftete Slices werden nicht gleichzeitig gestartet.
              </p>
            </div>
            {simulation?.waves.length ? (
              <div className="grid gap-3">
                {simulation.waves.map((wave) => (
                  <article className="rounded-lg border border-border p-3" key={wave.wave}>
                    <div className="flex items-center justify-between gap-3">
                      <strong className="text-sm">Welle {wave.wave}</strong>
                      <Badge variant="neutral">{wave.parallel_count} parallel</Badge>
                    </div>
                    <ol className="mt-3 grid gap-2">
                      {wave.candidate_ids.map((candidateId) => {
                        const candidate = campaign.pr_candidates.find((item) => item.id === candidateId);
                        const dependencies = simulation.dependencies[candidateId] ?? [];
                        const conflicts = simulation.conflicts.filter(
                          (conflict) =>
                            conflict.candidate_id === candidateId ||
                            conflict.conflicts_with_id === candidateId,
                        );
                        return (
                          <li className="rounded-md bg-muted/40 p-3" key={candidateId}>
                            <div className="flex items-start gap-2">
                              <Check className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                              <span className="min-w-0">
                                <strong className="block text-sm">{candidate?.title || candidateId}</strong>
                                {candidate?.scope ? (
                                  <span className="mt-1 block text-xs text-muted-foreground">
                                    {candidate.scope}
                                  </span>
                                ) : null}
                                <small className="mt-1 block text-muted-foreground">
                                  {dependencies.length
                                    ? `Nach: ${dependencies.map((id) => candidateTitle(campaign, id)).join(", ")}`
                                    : "Kann nach der Planfreigabe beginnen"}
                                </small>
                                {candidate?.acceptance_criteria.length ? (
                                  <small className="mt-1 block text-muted-foreground">
                                    {candidate.acceptance_criteria.length} Akzeptanzkriterien
                                  </small>
                                ) : null}
                                {conflicts.length ? (
                                  <small className="mt-1 block text-warning">
                                    {conflicts.map((conflict) => {
                                      const otherId = conflict.candidate_id === candidateId
                                        ? conflict.conflicts_with_id
                                        : conflict.candidate_id;
                                      return `Konflikt mit ${candidateTitle(campaign, otherId)}: ${conflict.reason}`;
                                    }).join(" · ")}
                                  </small>
                                ) : null}
                                {candidate ? (
                                  <details className="mt-2 rounded-md border border-border/70 p-2">
                                    <summary className="cursor-pointer text-xs font-medium">PR-Vertrag prüfen</summary>
                                    <div className="mt-2 grid gap-3 text-xs text-muted-foreground">
                                      <div>
                                        <strong className="text-foreground">Akzeptanzkriterien</strong>
                                        <ul className="mt-1 list-disc space-y-1 pl-4">
                                          {candidate.acceptance_criteria.map((criterion) => <li key={criterion}>{criterion}</li>)}
                                        </ul>
                                      </div>
                                      <div>
                                        <strong className="text-foreground">Automatische Checks</strong>
                                        <p className="mt-1">{candidate.contract?.required_checks.join(", ") || "Noch nicht definiert"}</p>
                                      </div>
                                      <div>
                                        <strong className="text-foreground">Manuelle Tests</strong>
                                        <p className="mt-1">{candidate.contract?.manual_tests.join(", ") || "Noch nicht definiert"}</p>
                                      </div>
                                    </div>
                                  </details>
                                ) : null}
                              </span>
                            </div>
                          </li>
                        );
                      })}
                    </ol>
                  </article>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Die Wellen werden angezeigt, sobald die Planprüfung abgeschlossen ist.
              </p>
            )}
          </section>

          <details className="rounded-lg border border-border p-3">
            <summary className="cursor-pointer text-sm font-medium">Plan- und Dokumentdetails</summary>
            <div className="mt-4 grid gap-4 text-sm">
              {campaign.non_goals ? <p><strong>Nicht-Ziele:</strong> {campaign.non_goals}</p> : null}
              {profile?.pivotal_fork ? <p><strong>Zentrale Entscheidung:</strong> {profile.pivotal_fork}</p> : null}
              {profile?.rollout_plan ? <p><strong>Rollout:</strong> {profile.rollout_plan}</p> : null}
              {profile?.rollback_plan ? <p><strong>Rollback:</strong> {profile.rollback_plan}</p> : null}
              {(campaign.questions ?? []).filter((question) => !openQuestionStates.has(question.status)).length ? (
                <div>
                  <strong>Entscheidungsprotokoll</strong>
                  <ul className="mt-2 grid gap-2">
                    {(campaign.questions ?? [])
                      .filter((question) => !openQuestionStates.has(question.status))
                      .map((question) => (
                        <li className="rounded-md bg-muted/40 p-2" key={question.id}>
                          <span className="block font-medium">{question.question}</span>
                          <span className="mt-1 block text-muted-foreground">
                            {question.answer || `Status: ${question.status}`}
                          </span>
                        </li>
                      ))}
                  </ul>
                </div>
              ) : null}
              <div>
                <strong>Artefakte</strong>
                {(campaign.artifacts ?? []).length ? (
                  <ul className="mt-2 grid gap-2 text-muted-foreground">
                    {(campaign.artifacts ?? []).map((artifact) => (
                      <li className="rounded-md bg-muted/40 p-2" key={artifact.id}>
                        <details>
                          <summary className="cursor-pointer">
                            {artifact.title} · {artifact.status} · v{artifact.version}
                          </summary>
                          <p className="mt-2 text-xs">{artifact.relative_path || "Nur im Control Center gespeichert"}</p>
                          {artifact.content_text ? (
                            <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-background p-3 text-xs text-foreground">
                              {artifact.content_text}
                            </pre>
                          ) : null}
                        </details>
                      </li>
                    ))}
                  </ul>
                ) : <p className="mt-2 text-muted-foreground">Noch keine Artefakte.</p>}
              </div>
            </div>
          </details>

          {policy.paused ? (
            <p className="rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm text-warning">
              Automation ist pausiert. Der Plan kann freigegeben werden, aber neue Arbeit startet erst nach bewusstem Fortsetzen.
            </p>
          ) : null}
          {error || readinessQuery.isError ? (
            <p className="composer-error" role="alert">
              {error || (readinessQuery.error instanceof Error
                ? readinessQuery.error.message
                : "Plan-Readiness konnte nicht geprüft werden.")}
            </p>
          ) : null}
          {amendmentStartNotice ? (
            <p className="rounded-lg border border-success/30 bg-success/5 p-3 text-sm text-success" role="status">
              {amendmentStartNotice}
            </p>
          ) : null}
        </div>

        <DialogFooter>
          {canAmendCampaign ? (
            <Button
              disabled={busy || loading || !exactAmendmentIdentityAvailable || Boolean(amendmentStartNotice)}
              onClick={() => {
                setError("");
                setAmendmentFormOpen(true);
              }}
              variant="secondary"
            >
              <PencilLine />
              Plan gezielt ändern
            </Button>
          ) : null}
          <Button disabled={busy} onClick={() => onOpenChange(false)} variant="secondary">
            Schließen
          </Button>
          {!completed ? (
            <Button
              disabled={
                busy ||
                loading ||
                Boolean(openQuestions.length) ||
                (!canApprove && !canStart)
              }
              onClick={() => setConfirmationOpen(true)}
            >
              {busy ? <LoaderCircle className="motion-safe:animate-spin" /> : <Play />}
              {actionLabel}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
      <AlertDialog onOpenChange={setConfirmationOpen} open={confirmationOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Plan wirklich freigeben?</AlertDialogTitle>
            <AlertDialogDescription>
              Plan v{campaign.version} auf {campaign.base_sha.slice(0, 12)} mit {campaign.pr_candidates.length} geplanten PRs
              {simulation ? ` in ${simulation.max_wave} sicheren Wellen` : ""}.
              {policy.paused
                ? " Automation bleibt pausiert; es werden noch keine Work Orders angelegt."
                : automatic
                  ? " Der Campaign-Modus wird bei Bedarf global aktiviert und die erste sichere Welle als Work Orders angelegt."
                  : " Danach bestätigst du jeden PR-Slice einzeln."}
              {readiness?.plan_signature ? (
                <span className="mt-3 block break-all font-mono text-xs">
                  Exakte Plan-Signatur v{readiness.plan_signature_version ?? 1}: {readiness.plan_signature}
                </span>
              ) : null}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Noch einmal prüfen</AlertDialogCancel>
            <AlertDialogAction
              disabled={busy}
              onClick={(event) => {
                event.preventDefault();
                setConfirmationOpen(false);
                void approveAndStart();
              }}
            >
              {automatic && !policy.paused ? "Freigeben und starten" : "Plan freigeben"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog
        onOpenChange={(nextOpen) => { if (!busy) setAmendmentFormOpen(nextOpen); }}
        open={amendmentFormOpen}
      >
        <AlertDialogContent className="sm:max-w-xl">
          <AlertDialogHeader>
            <AlertDialogTitle>Plan gezielt ändern</AlertDialogTitle>
            <AlertDialogDescription>
              Anti-Gravity pausiert den Plan und plant nur die noch veränderbare Zukunft neu. Laufende Arbeit, Prüfnachweise, GitHub-Daten und Auslieferungen bleiben unverändert.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-2 text-sm">
              <label className="font-medium" htmlFor="plan-amendment-reason">
                Warum muss der Plan geändert werden?
              </label>
              <Textarea
                aria-describedby="plan-amendment-reason-help"
                disabled={busy}
                id="plan-amendment-reason"
                onChange={(event) => setAmendmentReason(event.target.value)}
                placeholder="Zum Beispiel: Neue Erkenntnisse aus Projekt oder Prüfung"
                rows={2}
                value={amendmentReason}
              />
              <span className="text-xs text-muted-foreground" id="plan-amendment-reason-help">
                Mindestens {minimumAmendmentTextLength} Zeichen.
              </span>
            </div>
            <div className="grid gap-2 text-sm">
              <label className="font-medium" htmlFor="plan-amendment-change">
                Was soll sich am Plan ändern?
              </label>
              <Textarea
                disabled={busy}
                id="plan-amendment-change"
                onChange={(event) => setAmendmentRequestedChange(event.target.value)}
                placeholder="Gewünschte Zieländerung in eigenen Worten"
                rows={3}
                value={amendmentRequestedChange}
              />
            </div>
            <fieldset className="grid gap-2 rounded-lg border border-border p-3">
              <legend className="px-1 text-sm font-medium">Betroffene zukünftige geplante PRs (optional)</legend>
              <p className="text-xs text-muted-foreground">
                Keine Auswahl bedeutet: Die KI prüft alle relevanten, noch nicht gestarteten geplanten PRs.
              </p>
              {futureCandidates.length ? futureCandidates.map((candidate) => (
                <label className="flex items-start gap-2 text-sm" key={candidate.id}>
                  <Checkbox
                    aria-label={candidate.title}
                    checked={selectedAmendmentBranches.includes(candidate.id)}
                    disabled={busy}
                    onChange={() => toggleAmendmentBranch(candidate.id)}
                  />
                  <span>
                    <span className="block font-medium">{candidate.title}</span>
                    <span className="block text-xs text-muted-foreground">{candidate.scope}</span>
                  </span>
                </label>
              )) : (
                <p className="text-xs text-muted-foreground">Keine einzelnen zukünftigen geplanten PRs auswählbar.</p>
              )}
            </fieldset>
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">Technische Ausgangsreferenz</summary>
              <p className="mt-2 break-all font-mono text-[0.68rem]">
                Source: Plan v{activeCampaign.version} · {activeCampaign.base_sha.slice(0, 12)} · Signatur v{readiness?.plan_signature_version ?? "?"}: {readiness?.plan_signature || "wird geladen"}
              </p>
            </details>
            {error ? <p className="composer-error" role="alert">{error}</p> : null}
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Abbrechen</AlertDialogCancel>
            <AlertDialogAction
              disabled={busy || !amendmentFormValid}
              onClick={(event) => {
                event.preventDefault();
                void requestPlanAmendment();
              }}
            >
              {busy ? <LoaderCircle className="motion-safe:animate-spin" /> : null}
              Planänderung starten
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Dialog>
  );
}
