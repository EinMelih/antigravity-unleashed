import { Check, Circle, LoaderCircle } from "lucide-react";
import { type FormEvent, useId, useState } from "react";

import type { ControlApproval, ControlPrCandidate } from "@/api/contracts";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  evaluateTaskEvidence,
  mergeTaskOnGitHub,
  recordTaskApproval,
  runControlExecutorOnce,
  syncTaskGitHub,
} from "@/features/automation/api";
import type { HumanTestReproductionEvidence } from "@/features/automation/api";

interface WorkItemDeliveryProps {
  candidate: ControlPrCandidate;
  onChanged: () => Promise<void> | void;
}

type DeliveryAction =
  | "sync"
  | "evaluate"
  | "human_approve"
  | "human_reject"
  | "merge_approve"
  | "merge";

type ConfirmationAction = "human_approve" | "merge_approve" | "merge";

interface HumanTestRejectionDraft extends HumanTestReproductionEvidence {
  artifact_ref: string;
  diagnosis: string;
  note: string;
}

interface DeliveryFeedback {
  message: string;
  tone: "error" | "success" | "warning";
}

function isActiveApproval(
  approval: ControlApproval,
  type: "human_test" | "merge",
  sha: string,
) {
  return Boolean(
    approval.approval_type === type &&
      approval.decision === "approved" &&
      approval.sha.toLowerCase() === sha &&
      !approval.revoked_at,
  );
}

function evidenceStatusLabel(status?: string) {
  return {
    approved: "Freigegeben",
    blocked: "Blockiert",
    collecting: "Nachweise werden gesammelt",
    ready_for_human: "Bereit für Human-Test",
    rejected: "Abgelehnt",
  }[status ?? ""] ?? status ?? "Unbekannt";
}

function Gate({ detail, label, passed }: { detail: string; label: string; passed: boolean }) {
  return (
    <li className="items-start">
      {passed ? (
        <Check className="mt-0.5 size-4 shrink-0 text-success" />
      ) : (
        <Circle className="mt-0.5 size-4 shrink-0 text-warning" />
      )}
      <span className="grid min-w-0 gap-0.5">
        <strong className="font-medium text-foreground">{label}</strong>
        <small className="text-muted-foreground">{detail}</small>
      </span>
      <Badge className="ml-auto" variant={passed ? "healthy" : "attention"}>
        {passed ? "Erfüllt" : "Offen"}
      </Badge>
    </li>
  );
}

export function WorkItemDelivery({ candidate, onChanged }: WorkItemDeliveryProps) {
  const task = candidate.task;
  const pack = candidate.evidence_pack;
  const [busy, setBusy] = useState<DeliveryAction | null>(null);
  const [confirmation, setConfirmation] = useState<ConfirmationAction | null>(null);
  const [feedback, setFeedback] = useState<DeliveryFeedback | null>(null);
  const [rejectionDraft, setRejectionDraft] = useState<HumanTestRejectionDraft | null>(null);
  const [rejectionError, setRejectionError] = useState("");
  const rejectionFieldId = useId();

  if (!task) return null;

  const taskId = task.id;
  const prNumber = task.pr_number;
  const sha = String(task.current_sha || "").trim().toLowerCase();
  const hasSha = /^[0-9a-f]{40,64}$/.test(sha);
  const packMatchesSha = Boolean(hasSha && pack?.sha?.toLowerCase() === sha);
  const evidenceReady = Boolean(
    packMatchesSha && ["ready_for_human", "approved"].includes(pack?.status ?? ""),
  );
  const evidenceApproved = Boolean(packMatchesSha && pack?.status === "approved");
  const humanDecision = candidate.approvals.find(
    (approval) =>
      approval.approval_type === "human_test" &&
      approval.sha.toLowerCase() === sha &&
      !approval.revoked_at,
  );
  const humanApproved = candidate.approvals.some((approval) =>
    isActiveApproval(approval, "human_test", sha),
  );
  const humanRejected = humanDecision?.decision === "rejected";
  const mergeApproved = candidate.approvals.some((approval) =>
    isActiveApproval(approval, "merge", sha),
  );
  const pullRequestLinked = Boolean(task.pr_number && task.pr_url);
  const taskMergeable = !["completed", "cancelled", "failed"].includes(task.status);
  const canApproveMerge = Boolean(
    hasSha && evidenceApproved && humanApproved && !mergeApproved && taskMergeable,
  );
  const canMerge = Boolean(
    pullRequestLinked &&
      hasSha &&
      evidenceApproved &&
      humanApproved &&
      mergeApproved &&
      taskMergeable,
  );

  const confirmationCopy = confirmation
    ? {
        human_approve: {
          action: "Freigeben",
          description: `Die Human-Test-Freigabe gilt ausschließlich für ${sha.slice(0, 12)}. Bei einem neuen PR-Head verfällt dieses Gate.`,
          title: "Human-Test wirklich freigeben?",
        },
        merge_approve: {
          action: "Merge freigeben",
          description: `Die separate Merge-Freigabe gilt ausschließlich für ${sha.slice(0, 12)} und wird serverseitig nochmals geprüft.`,
          title: "Merge wirklich freigeben?",
        },
        merge: {
          action: "Jetzt mergen",
          description: `PR #${prNumber} wird nur gemergt, wenn GitHub weiterhin exakt ${sha.slice(0, 12)} als Head bestätigt. Dieser Schritt verändert den Ziel-Branch.`,
          title: "Pull Request wirklich mergen?",
        },
      }[confirmation]
    : null;

  async function refreshAfterSuccess(message: string, warning = "") {
    const successfulFeedback: DeliveryFeedback = warning
      ? { message: `${message} ${warning}`, tone: "warning" }
      : { message, tone: "success" };
    setFeedback(successfulFeedback);
    try {
      await onChanged();
    } catch (refreshError) {
      setFeedback({
        message: `${successfulFeedback.message} Die Ansicht konnte danach nicht aktualisiert werden: ${
          refreshError instanceof Error ? refreshError.message : String(refreshError)
        }`,
        tone: "warning",
      });
    }
  }

  async function refreshAfterFailure(message: string) {
    try {
      await onChanged();
      setFeedback({ message, tone: "error" });
    } catch (refreshError) {
      setFeedback({
        message: `${message} Auch die Ansicht konnte nicht aktualisiert werden: ${
          refreshError instanceof Error ? refreshError.message : String(refreshError)
        }`,
        tone: "error",
      });
    }
  }

  async function runAction(action: Exclude<DeliveryAction, "human_reject">) {
    if (busy) return;
    setBusy(action);
    setFeedback(null);
    setConfirmation(null);
    try {
      if (action === "sync") {
        const result = await syncTaskGitHub(taskId);
        const terminalNote = result.terminal_noop
          ? "Der Task ist bereits abgeschlossen; die Synchronisierung war ein No-op."
          : "";
        await refreshAfterSuccess("GitHub wurde synchronisiert.", terminalNote);
      } else if (action === "evaluate") {
        const result = await evaluateTaskEvidence(taskId);
        await refreshAfterSuccess(`Evidence neu bewertet: ${result.status}.`);
      } else if (action === "human_approve") {
        await recordTaskApproval(taskId, {
          approval_type: "human_test",
          decision: "approved",
          sha,
          reason: "Human-Test im Anti-Gravity Hub geprüft und freigegeben.",
        });
        await refreshAfterSuccess("Human-Test wurde freigegeben.");
      } else if (action === "merge_approve") {
        await recordTaskApproval(taskId, {
          approval_type: "merge",
          decision: "approved",
          sha,
          reason: "Merge-Gates im Anti-Gravity Hub geprüft und freigegeben.",
        });
        await refreshAfterSuccess("Merge wurde für den aktuellen SHA freigegeben.");
      } else {
        const result = await mergeTaskOnGitHub(taskId);
        await refreshAfterSuccess(
          `Pull Request wurde als ${result.merge.sha.slice(0, 12)} gemergt.`,
          result.issue_close_warning
            ? `Der nachgelagerte Issue-Abschluss braucht Aufmerksamkeit: ${result.issue_close_warning}`
            : "",
        );
      }
    } catch (actionError) {
      await refreshAfterFailure(
        actionError instanceof Error ? actionError.message : String(actionError),
      );
    } finally {
      setBusy(null);
    }
  }

  function openHumanTestRejection() {
    setRejectionError("");
    setRejectionDraft({
      artifact_ref: "",
      diagnosis: "",
      environment: "",
      executed_steps: "",
      expected_behavior: "",
      note: "",
      observed_behavior: "",
    });
  }

  function updateRejectionDraft(
    field: keyof HumanTestRejectionDraft,
    value: string,
  ) {
    setRejectionDraft((current) => (current ? { ...current, [field]: value } : current));
  }

  async function submitHumanTestRejection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!rejectionDraft || busy) return;

    const requiredEvidence = {
      environment: rejectionDraft.environment.trim(),
      executed_steps: rejectionDraft.executed_steps.trim(),
      expected_behavior: rejectionDraft.expected_behavior.trim(),
      observed_behavior: rejectionDraft.observed_behavior.trim(),
    };
    if (Object.values(requiredEvidence).some((value) => !value)) return;

    const diagnosis = rejectionDraft.diagnosis.trim();
    const artifactRef = rejectionDraft.artifact_ref.trim();
    const note = rejectionDraft.note.trim();
    const evidence: HumanTestReproductionEvidence = {
      ...requiredEvidence,
      ...(diagnosis ? { diagnosis } : {}),
      ...(artifactRef ? { artifact_ref: artifactRef } : {}),
      ...(note ? { note } : {}),
    };

    setBusy("human_reject");
    setFeedback(null);
    setRejectionError("");
    try {
      await recordTaskApproval(taskId, {
        approval_type: "human_test",
        decision: "rejected",
        sha,
        reason: "Human-Test im Anti-Gravity Hub mit Reproduktionspaket abgelehnt.",
        evidence,
      });
      let executorWarning = "";
      try {
        await runControlExecutorOnce();
      } catch (executorError) {
        executorWarning = `Der Executor konnte nicht sofort gestartet werden: ${
          executorError instanceof Error ? executorError.message : String(executorError)
        }. Der dauerhafte Executor übernimmt die eingeplante Reparatur.`;
      }
      setRejectionDraft(null);
      await refreshAfterSuccess(
        "Human-Test wurde abgelehnt. Reparatur wurde eingeplant.",
        executorWarning,
      );
    } catch (actionError) {
      const message = actionError instanceof Error ? actionError.message : String(actionError);
      setRejectionError(message);
      await refreshAfterFailure(message);
    } finally {
      setBusy(null);
    }
  }

  const pending = Boolean(busy);
  const rejectionComplete = Boolean(
    rejectionDraft?.executed_steps.trim() &&
      rejectionDraft.expected_behavior.trim() &&
      rejectionDraft.observed_behavior.trim() &&
      rejectionDraft.environment.trim(),
  );

  return (
    <>
      <section className="detail-section">
        <h3>Delivery-Gates</h3>
        <p className="detail-muted">
          Freigaben gelten nur für den angezeigten PR-Head. GitHub prüft den SHA beim Merge erneut.
        </p>
        <ul className="detail-checklist mt-3">
          <Gate
            detail={pullRequestLinked ? `PR #${prNumber}` : "Noch kein Pull Request verknüpft."}
            label="Pull Request verknüpft"
            passed={pullRequestLinked}
          />
          <Gate
            detail={hasSha ? sha : "Noch kein vollständiger Commit-SHA vorhanden."}
            label="Aktueller Commit-SHA"
            passed={hasSha}
          />
          <Gate
            detail={
              packMatchesSha
                ? `Status: ${evidenceStatusLabel(pack?.status)}`
                : "Evidence fehlt oder gehört zu einem älteren SHA."
            }
            label="Evidence für aktuellen SHA"
            passed={evidenceReady}
          />
          <Gate
            detail={
              humanApproved
                ? sha
                : humanRejected
                  ? "Für diesen SHA abgelehnt."
                  : "Noch nicht für den aktuellen SHA freigegeben."
            }
            label="Human-Test-Freigabe"
            passed={humanApproved}
          />
          <Gate
            detail={mergeApproved ? sha : "Separate Merge-Freigabe fehlt."}
            label="Merge-Freigabe"
            passed={mergeApproved}
          />
        </ul>
      </section>

      <section className="detail-section">
        <h3>Delivery steuern</h3>
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={pending || !pullRequestLinked}
            onClick={() => void runAction("sync")}
            size="sm"
            variant="secondary"
          >
            {busy === "sync" ? <LoaderCircle className="motion-safe:animate-spin" /> : null}
            Mit GitHub synchronisieren
          </Button>
          <Button
            disabled={pending}
            onClick={() => void runAction("evaluate")}
            size="sm"
            variant="secondary"
          >
            {busy === "evaluate" ? <LoaderCircle className="motion-safe:animate-spin" /> : null}
            Evidence neu bewerten
          </Button>
          <Button
            disabled={pending || !evidenceReady || !taskMergeable}
            onClick={() => setConfirmation("human_approve")}
            size="sm"
            variant="secondary"
          >
            Human-Test freigeben
          </Button>
          <Button
            disabled={pending || !evidenceReady || !taskMergeable}
            onClick={openHumanTestRejection}
            size="sm"
            variant="secondary"
          >
            Human-Test ablehnen
          </Button>
          <Button
            disabled={pending || !canApproveMerge}
            onClick={() => setConfirmation("merge_approve")}
            size="sm"
            variant="secondary"
          >
            Merge freigeben
          </Button>
          <Button
            disabled={pending || !canMerge}
            onClick={() => setConfirmation("merge")}
            size="sm"
          >
            Pull Request mergen
          </Button>
        </div>
        {!canMerge ? (
          <p className="detail-muted mt-3">
            Merge bleibt gesperrt, bis alle oben sichtbaren Gates für denselben SHA erfüllt sind.
          </p>
        ) : null}
        {feedback?.tone === "warning" ? (
          <div className="detail-attention mt-3" role="status">
            <strong>Aktion abgeschlossen, Nacharbeit nötig</strong>
            <p>{feedback.message}</p>
          </div>
        ) : feedback ? (
          <p
            className={feedback.tone === "error" ? "detail-error mt-3" : "detail-copy mt-3"}
            role={feedback.tone === "error" ? "alert" : "status"}
          >
            {feedback.message}
          </p>
        ) : null}
      </section>

      <Dialog
        onOpenChange={(nextOpen) => {
          if (!nextOpen && !busy) {
            setRejectionDraft(null);
            setRejectionError("");
          }
        }}
        open={Boolean(rejectionDraft)}
      >
        <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
          <form className="grid gap-4" onSubmit={(event) => void submitHumanTestRejection(event)}>
            <DialogHeader>
              <DialogTitle>Human-Test ablehnen</DialogTitle>
              <DialogDescription>
                Dokumentiere den reproduzierbaren Fehler. Anti-Gravity öffnet daraus einen
                verpflichtenden Befund und plant den Task erneut zur Reparatur ein.
              </DialogDescription>
            </DialogHeader>

            <div className="rounded-md border border-warning/25 bg-warning/10 p-3 text-sm">
              <strong className="block text-foreground">Geprüfter Commit-SHA</strong>
              <code className="mt-1 block break-all text-xs text-muted-foreground">{sha}</code>
            </div>

            <div className="grid gap-2">
              <label className="text-sm font-medium" htmlFor={`${rejectionFieldId}-steps`}>
                Ausgeführte Schritte
              </label>
              <Textarea
                id={`${rejectionFieldId}-steps`}
                maxLength={4000}
                onChange={(event) => updateRejectionDraft("executed_steps", event.target.value)}
                required
                rows={4}
                value={rejectionDraft?.executed_steps ?? ""}
              />
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="grid gap-2">
                <label className="text-sm font-medium" htmlFor={`${rejectionFieldId}-expected`}>
                  Erwartetes Verhalten
                </label>
                <Textarea
                  id={`${rejectionFieldId}-expected`}
                  maxLength={4000}
                  onChange={(event) =>
                    updateRejectionDraft("expected_behavior", event.target.value)
                  }
                  required
                  rows={3}
                  value={rejectionDraft?.expected_behavior ?? ""}
                />
              </div>
              <div className="grid gap-2">
                <label className="text-sm font-medium" htmlFor={`${rejectionFieldId}-observed`}>
                  Beobachtetes Verhalten
                </label>
                <Textarea
                  id={`${rejectionFieldId}-observed`}
                  maxLength={4000}
                  onChange={(event) =>
                    updateRejectionDraft("observed_behavior", event.target.value)
                  }
                  required
                  rows={3}
                  value={rejectionDraft?.observed_behavior ?? ""}
                />
              </div>
            </div>
            <div className="grid gap-2">
              <label className="text-sm font-medium" htmlFor={`${rejectionFieldId}-environment`}>
                Umgebung
              </label>
              <Input
                id={`${rejectionFieldId}-environment`}
                maxLength={2000}
                onChange={(event) => updateRejectionDraft("environment", event.target.value)}
                placeholder="z. B. Windows 11, Chrome 128, lokale Vorschau"
                required
                value={rejectionDraft?.environment ?? ""}
              />
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="grid gap-2">
                <label className="text-sm font-medium" htmlFor={`${rejectionFieldId}-diagnosis`}>
                  Diagnose (optional)
                </label>
                <Textarea
                  id={`${rejectionFieldId}-diagnosis`}
                  maxLength={4000}
                  onChange={(event) => updateRejectionDraft("diagnosis", event.target.value)}
                  rows={2}
                  value={rejectionDraft?.diagnosis ?? ""}
                />
              </div>
              <div className="grid gap-2">
                <label className="text-sm font-medium" htmlFor={`${rejectionFieldId}-artifact`}>
                  Artefakt (optional)
                </label>
                <Input
                  id={`${rejectionFieldId}-artifact`}
                  maxLength={2000}
                  onChange={(event) => updateRejectionDraft("artifact_ref", event.target.value)}
                  placeholder="URL oder Workspace-Pfad"
                  value={rejectionDraft?.artifact_ref ?? ""}
                />
              </div>
            </div>
            <div className="grid gap-2">
              <label className="text-sm font-medium" htmlFor={`${rejectionFieldId}-note`}>
                Notiz (optional)
              </label>
              <Textarea
                id={`${rejectionFieldId}-note`}
                maxLength={4000}
                onChange={(event) => updateRejectionDraft("note", event.target.value)}
                rows={2}
                value={rejectionDraft?.note ?? ""}
              />
            </div>

            {rejectionError ? (
              <p className="detail-error" role="alert">
                {rejectionError}
              </p>
            ) : null}

            <DialogFooter>
              <Button
                disabled={busy === "human_reject"}
                onClick={() => {
                  setRejectionDraft(null);
                  setRejectionError("");
                }}
                type="button"
                variant="secondary"
              >
                Abbrechen
              </Button>
              <Button disabled={!rejectionComplete || pending} type="submit" variant="destructive">
                {busy === "human_reject" ? (
                  <LoaderCircle className="motion-safe:animate-spin" />
                ) : null}
                Ablehnung einplanen
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog
        onOpenChange={(nextOpen) => {
          if (!nextOpen) setConfirmation(null);
        }}
        open={Boolean(confirmationCopy)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirmationCopy?.title}</AlertDialogTitle>
            <AlertDialogDescription>{confirmationCopy?.description}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Abbrechen</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (confirmation) void runAction(confirmation);
              }}
            >
              {confirmationCopy?.action}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
