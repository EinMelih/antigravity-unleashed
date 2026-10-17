import { LoaderCircle, Pencil, Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";

import type {
  ControlActivationPolicy,
  ControlIdeaSeed,
  ControlPlanningDepth,
  HubProject,
} from "@/api/contracts";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  dispositionIdeaSeed,
  planIdeaSeed,
  runControlExecutorOnce,
  updateIdeaSeed,
} from "@/features/automation/api";

interface IdeaSeedInboxProps {
  error: unknown;
  isError: boolean;
  isPending: boolean;
  onChanged: () => Promise<void> | void;
  onRetry: () => Promise<unknown> | void;
  projects: HubProject[];
  seeds?: ControlIdeaSeed[];
}

interface EditDraft {
  note: string;
  seed: ControlIdeaSeed;
  title: string;
}

interface DispositionDraft {
  reason: string;
  seed: ControlIdeaSeed;
  target: "deferred" | "dismissed";
}

interface PlanDraft {
  activationPolicy: ControlActivationPolicy;
  constraints: string;
  maxCandidates: number;
  planningDepth: ControlPlanningDepth;
  seed: ControlIdeaSeed;
}

interface InboxFeedback {
  message: string;
  tone: "error" | "success" | "warning";
}

const candidateDefaults: Record<ControlPlanningDepth, number> = {
  compact: 5,
  balanced: 12,
  deep: 30,
  exhaustive: 100,
};

const statusLabels: Record<ControlIdeaSeed["status"], string> = {
  inbox: "Offen",
  deferred: "Zurückgestellt",
  dismissed: "Verworfen",
  planning: "In Planung",
  planned: "Geplant",
};

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function seedDomId(seed: ControlIdeaSeed) {
  return `idea-seed-${seed.id.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

function IdeaSeedCard({
  busy,
  onDismiss,
  onEdit,
  onPlan,
  onReopen,
  onDefer,
  projectName,
  seed,
}: {
  busy: boolean;
  onDismiss: () => void;
  onEdit: () => void;
  onPlan: () => void;
  onReopen: () => void;
  onDefer: () => void;
  projectName: string;
  seed: ControlIdeaSeed;
}) {
  const plannable = seed.status === "inbox" || seed.status === "deferred";
  return (
    <article
      aria-labelledby={seedDomId(seed)}
      className="grid gap-4 rounded-xl border border-border bg-card p-4 shadow-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-medium" id={seedDomId(seed)}>{seed.title}</h3>
          <p className="mt-1 text-xs text-muted-foreground">{projectName} · {seed.source}</p>
        </div>
        <Badge variant={seed.status === "inbox" ? "healthy" : "neutral"}>
          {statusLabels[seed.status]}
        </Badge>
      </div>
      <p className="whitespace-pre-wrap text-sm leading-6 text-muted-foreground">{seed.note}</p>
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy} onClick={onEdit} size="sm" variant="secondary">
          <Pencil className="size-3.5" />
          Bearbeiten
        </Button>
        {plannable ? (
          <Button disabled={busy} onClick={onPlan} size="sm">
            <Sparkles className="size-3.5" />
            Mit KI planen
          </Button>
        ) : null}
        {seed.status === "inbox" ? (
          <Button disabled={busy} onClick={onDefer} size="sm" variant="secondary">
            Zurückstellen
          </Button>
        ) : null}
        {seed.status === "deferred" || seed.status === "dismissed" ? (
          <Button disabled={busy} onClick={onReopen} size="sm" variant="secondary">
            Wieder öffnen
          </Button>
        ) : null}
        {seed.status === "inbox" || seed.status === "deferred" ? (
          <Button disabled={busy} onClick={onDismiss} size="sm" variant="secondary">
            Verwerfen
          </Button>
        ) : null}
      </div>
    </article>
  );
}

export function IdeaSeedInbox({
  error,
  isError,
  isPending,
  onChanged,
  onRetry,
  projects,
  seeds,
}: IdeaSeedInboxProps) {
  const [showDismissed, setShowDismissed] = useState(false);
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null);
  const [dispositionDraft, setDispositionDraft] = useState<DispositionDraft | null>(null);
  const [planDraft, setPlanDraft] = useState<PlanDraft | null>(null);
  const [busy, setBusy] = useState("");
  const [modalError, setModalError] = useState("");
  const [feedback, setFeedback] = useState<InboxFeedback | null>(null);

  const availableSeeds = seeds ?? [];
  const activeSeeds = availableSeeds.filter(
    (seed) => seed.status === "inbox" || seed.status === "deferred",
  );
  const dismissedSeeds = availableSeeds.filter((seed) => seed.status === "dismissed");
  const projectNames = new Map(
    projects.map((project) => [project.id, project.github_repo || project.name]),
  );

  function projectName(seed: ControlIdeaSeed) {
    return projectNames.get(seed.project_id) || `Projekt ${seed.project_id}`;
  }

  async function finishMutation(message: string, warning = "") {
    const initialFeedback: InboxFeedback = warning
      ? { message: `${message} ${warning}`, tone: "warning" }
      : { message, tone: "success" };
    setFeedback(initialFeedback);
    try {
      await onChanged();
    } catch (refreshError) {
      setFeedback({
        message: `${initialFeedback.message} Die Inbox konnte danach nicht aktualisiert werden: ${errorMessage(refreshError)}`,
        tone: "warning",
      });
    }
  }

  function openEdit(seed: ControlIdeaSeed) {
    setModalError("");
    setEditDraft({ note: seed.note, seed, title: seed.title });
  }

  function openDisposition(seed: ControlIdeaSeed, target: "deferred" | "dismissed") {
    setModalError("");
    setDispositionDraft({ reason: "", seed, target });
  }

  function openPlan(seed: ControlIdeaSeed) {
    setModalError("");
    setPlanDraft({
      activationPolicy: "campaign_wave",
      constraints: "",
      maxCandidates: candidateDefaults.deep,
      planningDepth: "deep",
      seed,
    });
  }

  async function submitEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editDraft || busy) return;
    const title = editDraft.title.trim();
    const note = editDraft.note.trim();
    if (title.length < 3 || note.length < 3) return;
    setBusy(`edit:${editDraft.seed.id}`);
    setModalError("");
    try {
      await updateIdeaSeed(editDraft.seed.id, { title, note });
      setEditDraft(null);
      await finishMutation("Idee wurde gespeichert.");
    } catch (updateError) {
      setModalError(errorMessage(updateError));
    } finally {
      setBusy("");
    }
  }

  async function submitDisposition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dispositionDraft || busy) return;
    const reason = dispositionDraft.reason.trim();
    if (!reason) return;
    const { seed, target } = dispositionDraft;
    setBusy(`disposition:${seed.id}`);
    setModalError("");
    try {
      await dispositionIdeaSeed(seed.id, { disposition: target, reason });
      setDispositionDraft(null);
      await finishMutation(
        target === "deferred" ? "Idee wurde zurückgestellt." : "Idee wurde verworfen.",
      );
    } catch (dispositionError) {
      setModalError(errorMessage(dispositionError));
    } finally {
      setBusy("");
    }
  }

  async function reopen(seed: ControlIdeaSeed) {
    if (busy) return;
    setBusy(`reopen:${seed.id}`);
    setFeedback(null);
    try {
      await dispositionIdeaSeed(seed.id, { disposition: "inbox", reason: "" });
      await finishMutation("Idee ist wieder offen.");
    } catch (reopenError) {
      setFeedback({ message: errorMessage(reopenError), tone: "error" });
    } finally {
      setBusy("");
    }
  }

  async function submitPlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!planDraft || busy) return;
    setBusy(`plan:${planDraft.seed.id}`);
    setModalError("");
    try {
      await planIdeaSeed(planDraft.seed.id, {
        activation_policy: planDraft.activationPolicy,
        planning_depth: planDraft.planningDepth,
        max_candidates: planDraft.maxCandidates,
        constraints: planDraft.constraints
          .split("\n")
          .map((item) => item.trim())
          .filter(Boolean),
      });
      let executorWarning = "";
      try {
        await runControlExecutorOnce();
      } catch (executorError) {
        executorWarning = `Der Executor konnte nicht sofort gestartet werden: ${errorMessage(executorError)}. Der dauerhafte Executor übernimmt den eingeplanten Job.`;
      }
      setPlanDraft(null);
      await finishMutation("Planung ist eingeplant.", executorWarning);
    } catch (planError) {
      setModalError(errorMessage(planError));
    } finally {
      setBusy("");
    }
  }

  const mutationBusy = Boolean(busy);

  return (
    <section aria-labelledby="idea-seed-inbox-title" className="space-y-4">
      <div className="automation-list-heading">
        <div>
          <p className="eyebrow">Ideen-Inbox</p>
          <h2 className="mt-1 text-xl font-semibold" id="idea-seed-inbox-title">Ideen</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Ideen sammeln, schärfen und erst dann als prüfbaren KI-Plan starten.
          </p>
        </div>
        {!isPending && !isError ? (
          <span className="text-xs text-muted-foreground">{activeSeeds.length} aktiv</span>
        ) : null}
      </div>

      {feedback?.tone === "warning" ? (
        <div className="detail-attention" role="status">
          <strong>Aktion abgeschlossen, Aktualisierung unvollständig</strong>
          <p>{feedback.message}</p>
        </div>
      ) : feedback ? (
        <p
          className={feedback.tone === "error" ? "detail-error" : "detail-copy"}
          role={feedback.tone === "error" ? "alert" : "status"}
        >
          {feedback.message}
        </p>
      ) : null}

      {isPending ? (
        <div className="flex items-center gap-2 rounded-xl border border-border p-4 text-sm text-muted-foreground">
          <LoaderCircle className="size-4 motion-safe:animate-spin" />
          Ideen werden geladen …
        </div>
      ) : isError ? (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4" role="alert">
          <strong className="text-sm">Ideen-Inbox nicht erreichbar</strong>
          <p className="mt-1 text-sm text-muted-foreground">{errorMessage(error)}</p>
          <Button className="mt-3" onClick={() => void onRetry()} size="sm" variant="secondary">
            Ideen erneut laden
          </Button>
        </div>
      ) : (
        <>
          {activeSeeds.length ? (
            <div className="grid gap-3 lg:grid-cols-2">
              {activeSeeds.map((seed) => (
                <IdeaSeedCard
                  busy={mutationBusy}
                  key={seed.id}
                  onDefer={() => openDisposition(seed, "deferred")}
                  onDismiss={() => openDisposition(seed, "dismissed")}
                  onEdit={() => openEdit(seed)}
                  onPlan={() => openPlan(seed)}
                  onReopen={() => void reopen(seed)}
                  projectName={projectName(seed)}
                  seed={seed}
                />
              ))}
            </div>
          ) : (
            <div className="automation-local-empty">
              <strong>Keine offenen Ideen</strong>
              <span>Neue Vorhaben können weiterhin über „Idee beschreiben“ gestartet werden.</span>
            </div>
          )}

          {dismissedSeeds.length ? (
            <div className="space-y-3">
              <Button
                onClick={() => setShowDismissed((visible) => !visible)}
                size="sm"
                variant="secondary"
              >
                {showDismissed
                  ? "Verworfene Ideen ausblenden"
                  : `${dismissedSeeds.length} ${dismissedSeeds.length === 1 ? "verworfene Idee" : "verworfene Ideen"} anzeigen`}
              </Button>
              {showDismissed ? (
                <div className="grid gap-3 lg:grid-cols-2">
                  {dismissedSeeds.map((seed) => (
                    <IdeaSeedCard
                      busy={mutationBusy}
                      key={seed.id}
                      onDefer={() => undefined}
                      onDismiss={() => undefined}
                      onEdit={() => openEdit(seed)}
                      onPlan={() => undefined}
                      onReopen={() => void reopen(seed)}
                      projectName={projectName(seed)}
                      seed={seed}
                    />
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </>
      )}

      <Dialog
        onOpenChange={(open) => {
          if (!open && !mutationBusy) setEditDraft(null);
        }}
        open={Boolean(editDraft)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Idee bearbeiten</DialogTitle>
            <DialogDescription>
              Titel und Beschreibung werden im bestehenden Idea Seed aktualisiert.
            </DialogDescription>
          </DialogHeader>
          {editDraft ? (
            <form className="grid gap-4" onSubmit={(event) => void submitEdit(event)}>
              <label className="hub-field">
                <span>Titel</span>
                <Input
                  disabled={mutationBusy}
                  maxLength={200}
                  minLength={3}
                  onChange={(event) => setEditDraft({ ...editDraft, title: event.target.value })}
                  required
                  value={editDraft.title}
                />
              </label>
              <label className="hub-field">
                <span>Beschreibung</span>
                <Textarea
                  disabled={mutationBusy}
                  maxLength={5000}
                  minLength={3}
                  onChange={(event) => setEditDraft({ ...editDraft, note: event.target.value })}
                  required
                  rows={7}
                  value={editDraft.note}
                />
              </label>
              {modalError ? <p className="composer-error" role="alert">{modalError}</p> : null}
              <DialogFooter>
                <Button disabled={mutationBusy} onClick={() => setEditDraft(null)} type="button" variant="secondary">
                  Abbrechen
                </Button>
                <Button
                  disabled={mutationBusy || editDraft.title.trim().length < 3 || editDraft.note.trim().length < 3}
                  type="submit"
                >
                  {busy.startsWith("edit:") ? <LoaderCircle className="motion-safe:animate-spin" /> : null}
                  Speichern
                </Button>
              </DialogFooter>
            </form>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog
        onOpenChange={(open) => {
          if (!open && !mutationBusy) setDispositionDraft(null);
        }}
        open={Boolean(dispositionDraft)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dispositionDraft?.target === "deferred" ? "Idee zurückstellen" : "Idee verwerfen"}
            </DialogTitle>
            <DialogDescription>
              Die Entscheidung wird protokolliert. Verworfene Ideen können später wieder geöffnet werden.
            </DialogDescription>
          </DialogHeader>
          {dispositionDraft ? (
            <form className="grid gap-4" onSubmit={(event) => void submitDisposition(event)}>
              <label className="hub-field">
                <span>Begründung</span>
                <Textarea
                  autoFocus
                  disabled={mutationBusy}
                  onChange={(event) => setDispositionDraft({ ...dispositionDraft, reason: event.target.value })}
                  placeholder="Warum soll diese Idee jetzt nicht weiterverfolgt werden?"
                  required
                  rows={4}
                  value={dispositionDraft.reason}
                />
              </label>
              {modalError ? <p className="composer-error" role="alert">{modalError}</p> : null}
              <DialogFooter>
                <Button disabled={mutationBusy} onClick={() => setDispositionDraft(null)} type="button" variant="secondary">
                  Abbrechen
                </Button>
                <Button disabled={mutationBusy || !dispositionDraft.reason.trim()} type="submit">
                  {busy.startsWith("disposition:") ? <LoaderCircle className="motion-safe:animate-spin" /> : null}
                  {dispositionDraft.target === "deferred" ? "Zurückstellen" : "Verwerfen"}
                </Button>
              </DialogFooter>
            </form>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog
        onOpenChange={(open) => {
          if (!open && !mutationBusy) setPlanDraft(null);
        }}
        open={Boolean(planDraft)}
      >
        <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Idee mit KI planen</DialogTitle>
            <DialogDescription>
              Anti-Gravity plant den bestehenden Seed. Es wird keine zweite Idee angelegt und noch kein Code geändert.
            </DialogDescription>
          </DialogHeader>
          {planDraft ? (
            <form className="grid gap-5" onSubmit={(event) => void submitPlan(event)}>
              <div className="rounded-lg border border-border bg-muted/40 p-3">
                <strong className="text-sm">{planDraft.seed.title}</strong>
                <p className="mt-1 text-xs text-muted-foreground">{projectName(planDraft.seed)}</p>
              </div>
              <fieldset className="grid gap-2">
                <legend className="text-sm font-medium">Wie soll der fertige Plan ausgeführt werden?</legend>
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3">
                  <input
                    aria-label="Plan freigeben, dann sichere PR-Wellen automatisch abarbeiten"
                    checked={planDraft.activationPolicy === "campaign_wave"}
                    className="mt-1"
                    disabled={mutationBusy}
                    name="seed-activation-policy"
                    onChange={() => setPlanDraft({ ...planDraft, activationPolicy: "campaign_wave" })}
                    type="radio"
                  />
                  <span>
                    <strong className="block text-sm">Einmal freigeben, dann sichere PR-Wellen abarbeiten</strong>
                    <small className="mt-1 block text-muted-foreground">Abhängigkeiten und Konflikte bestimmen automatisch die Reihenfolge.</small>
                  </span>
                </label>
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3">
                  <input
                    aria-label="Vor jedem PR erneut fragen"
                    checked={planDraft.activationPolicy === "per_candidate"}
                    className="mt-1"
                    disabled={mutationBusy}
                    name="seed-activation-policy"
                    onChange={() => setPlanDraft({ ...planDraft, activationPolicy: "per_candidate" })}
                    type="radio"
                  />
                  <span>
                    <strong className="block text-sm">Vor jedem PR erneut fragen</strong>
                    <small className="mt-1 block text-muted-foreground">Jeder einzelne Slice benötigt eine eigene Freigabe.</small>
                  </span>
                </label>
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3">
                  <input
                    aria-label="Bis zu den Human- und Merge-Gates automatisch arbeiten"
                    checked={planDraft.activationPolicy === "autopilot"}
                    className="mt-1"
                    disabled={mutationBusy}
                    name="seed-activation-policy"
                    onChange={() => setPlanDraft({ ...planDraft, activationPolicy: "autopilot" })}
                    type="radio"
                  />
                  <span>
                    <strong className="block text-sm">Bis zu Human- und Merge-Gates automatisch</strong>
                    <small className="mt-1 block text-muted-foreground">Anti-Gravity arbeitet weiter, irreversible Freigaben bleiben menschlich.</small>
                  </span>
                </label>
              </fieldset>

              <details className="rounded-lg border border-border p-3">
                <summary className="cursor-pointer text-sm font-medium">Planungsumfang anpassen</summary>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <div className="hub-field">
                    <span>Planungstiefe</span>
                    <Select
                      disabled={mutationBusy}
                      onValueChange={(value) => {
                        const planningDepth = value as ControlPlanningDepth;
                        setPlanDraft({
                          ...planDraft,
                          planningDepth,
                          maxCandidates: candidateDefaults[planningDepth],
                        });
                      }}
                      value={planDraft.planningDepth}
                    >
                      <SelectTrigger aria-label="Planungstiefe"><SelectValue /></SelectTrigger>
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
                      disabled={mutationBusy}
                      max={100}
                      min={1}
                      onChange={(event) => setPlanDraft({ ...planDraft, maxCandidates: Number(event.target.value) })}
                      type="number"
                      value={planDraft.maxCandidates}
                    />
                  </label>
                  <label className="hub-field sm:col-span-2">
                    <span>Feste Grenzen (optional, eine pro Zeile)</span>
                    <Textarea
                      disabled={mutationBusy}
                      onChange={(event) => setPlanDraft({ ...planDraft, constraints: event.target.value })}
                      rows={3}
                      value={planDraft.constraints}
                    />
                  </label>
                </div>
              </details>

              {modalError ? <p className="composer-error" role="alert">{modalError}</p> : null}
              <DialogFooter>
                <Button disabled={mutationBusy} onClick={() => setPlanDraft(null)} type="button" variant="secondary">
                  Abbrechen
                </Button>
                <Button
                  disabled={
                    mutationBusy
                    || !Number.isInteger(planDraft.maxCandidates)
                    || planDraft.maxCandidates < 1
                    || planDraft.maxCandidates > 100
                  }
                  type="submit"
                >
                  {busy.startsWith("plan:") ? <LoaderCircle className="motion-safe:animate-spin" /> : <Sparkles />}
                  KI-Planung starten
                </Button>
              </DialogFooter>
            </form>
          ) : null}
        </DialogContent>
      </Dialog>
    </section>
  );
}
