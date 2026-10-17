import { AlertTriangle, ArrowRight, CheckCircle2, FileText, GitBranch, Link2, LoaderCircle } from "lucide-react";
import { useState } from "react";

import type { ControlCampaign, ControlPlanAmendment } from "@/api/contracts";
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
import { domainStatusLabel, planFieldLabel } from "@/lib/domain-labels";

function shortHash(value?: string) {
  return value?.slice(0, 12) || "nicht verfügbar";
}

function changeTitle(
  change: { id: string; title?: string } | string,
  campaign: ControlCampaign,
) {
  const candidateId = typeof change === "string" ? change : change.id;
  return (typeof change === "string" ? "" : change.title)
    || campaign.pr_candidates.find((candidate) => candidate.id === candidateId)?.title
    || "Geplanter PR";
}

export function PlanAmendmentReview({
  amendment,
  busy,
  canCancel,
  campaign,
  detailVerified,
  error,
  loading,
  notice,
  onApprove,
  onCancel,
  onClose,
  onReject,
  open,
}: {
  amendment?: ControlPlanAmendment;
  busy: boolean;
  canCancel: boolean;
  campaign: ControlCampaign;
  detailVerified: boolean;
  error?: string;
  loading: boolean;
  notice?: string;
  onApprove: () => Promise<void> | void;
  onCancel: () => Promise<void> | void;
  onClose: () => void;
  onReject: () => Promise<void> | void;
  open: boolean;
}) {
  const [pendingDecision, setPendingDecision] = useState<"approved" | "rejected" | "cancelled">();
  const patch = amendment?.patch;
  const candidates = patch?.candidates;
  const artifacts = [
    ...(patch?.artifacts?.add ?? []),
    ...(patch?.artifacts?.supersede ?? []),
  ];
  const relationCount =
    (patch?.knowledge_relations?.add?.length ?? 0) +
    (patch?.knowledge_relations?.remove?.length ?? 0);
  const changedFieldKeys = [
    ...Object.keys(patch?.campaign?.set ?? {}),
    ...Object.keys(patch?.profile?.set ?? {}),
  ];
  const immutableCount = amendment?.validation?.immutable_candidate_ids?.length ?? 0;
  const previousStatusLabel = domainStatusLabel(
    amendment?.prior_campaign_status,
    "Vorheriger sicherer Zustand",
  );
  const exactTargetAvailable = Boolean(
    amendment?.before_plan_sha256 &&
    amendment.target_plan_sha256 &&
    amendment.patch_sha256 &&
    amendment.target_plan &&
    amendment.patch,
  );
  const targetReady = Boolean(
    detailVerified &&
    exactTargetAvailable &&
    amendment?.validation?.ready === true,
  );

  return (
    <>
    <Dialog open={open} onOpenChange={(nextOpen) => { if (!nextOpen && !busy) onClose(); }}>
      <DialogContent className="max-h-[92svh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Planänderung prüfen: {campaign.title}</DialogTitle>
          <DialogDescription>
            {amendment?.reason || "Anti-Gravity bereitet den überprüfbaren Zielplan vor."}
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <LoaderCircle className="size-4 motion-safe:animate-spin" />
            Exakte Planänderung wird geladen …
          </p>
        ) : (
          <div className="grid gap-4">
            <section className="rounded-xl border border-border bg-muted/25 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="neutral">Plan v{amendment?.from_version ?? campaign.version}</Badge>
                <ArrowRight className="size-4 text-muted-foreground" />
                <Badge variant={targetReady ? "healthy" : "attention"}>
                  Plan v{amendment?.proposed_version ?? campaign.version + 1}
                </Badge>
                {!targetReady ? (
                  <span className="flex items-center gap-1 text-xs text-warning">
                    <AlertTriangle className="size-3.5" />
                    {detailVerified ? "Prüfung offen" : "Exakte Prüfung fehlt"}
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-xs text-success">
                    <CheckCircle2 className="size-3.5" /> Zielplan geprüft
                  </span>
                )}
              </div>
              <p className="mt-2 text-sm font-medium">
                Plan v{amendment?.from_version ?? campaign.version} → v{amendment?.proposed_version ?? campaign.version + 1}
              </p>
              <details className="mt-3 text-xs text-muted-foreground">
                <summary className="cursor-pointer">Technische Planreferenzen</summary>
                <p className="mt-2 font-mono">
                  Codebasis {shortHash(amendment?.from_base_sha || campaign.base_sha)} → {shortHash(amendment?.planning_base_sha)}
                </p>
                <p className="mt-2 break-all">Vorher: {amendment?.before_plan_sha256 || "fehlt"}</p>
                <p className="mt-1 break-all">Nachher: {amendment?.target_plan_sha256 || "fehlt"}</p>
                <p className="mt-1 break-all">Änderung: {amendment?.patch_sha256 || "fehlt"}</p>
              </details>
            </section>

            {detailVerified ? <section className="grid gap-3">
              <div>
                <h3 className="text-sm font-semibold">Was ändert sich?</h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  Nur zukünftige, noch nicht gestartete geplante PRs und ihre Planbeziehungen sind änderbar.
                </p>
              </div>

              {changedFieldKeys.length ? (
                <article className="rounded-lg border border-border p-3">
                  <strong className="text-sm">Plan-Grundlagen</strong>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {changedFieldKeys.map(planFieldLabel).join(", ")}
                  </p>
                  <details className="mt-2 text-xs text-muted-foreground">
                    <summary className="cursor-pointer">Technische Feldnamen</summary>
                    <code className="mt-1 block break-all">{changedFieldKeys.join(", ")}</code>
                  </details>
                </article>
              ) : null}

              <div className="grid gap-3 sm:grid-cols-3">
                <article className="rounded-lg border border-success/30 p-3">
                  <strong className="text-sm">Hinzugefügt</strong>
                  {(candidates?.add ?? []).length ? (
                    <ul className="mt-2 grid gap-1 text-xs text-muted-foreground">
                      {candidates?.add?.map((change) => <li key={change.id}>{changeTitle(change, campaign)}</li>)}
                    </ul>
                  ) : <p className="mt-2 text-xs text-muted-foreground">Keine geplanten PRs</p>}
                </article>
                <article className="rounded-lg border border-warning/30 p-3">
                  <strong className="text-sm">Geändert</strong>
                  {(candidates?.update ?? []).length ? (
                    <ul className="mt-2 grid gap-1 text-xs text-muted-foreground">
                      {candidates?.update?.map((change) => <li key={change.id}>{changeTitle(change, campaign)}</li>)}
                    </ul>
                  ) : <p className="mt-2 text-xs text-muted-foreground">Keine geplanten PRs</p>}
                </article>
                <article className="rounded-lg border border-border p-3">
                  <strong className="text-sm">Aus Plan genommen</strong>
                  {(candidates?.retire ?? []).length ? (
                    <ul className="mt-2 grid gap-1 text-xs text-muted-foreground">
                      {candidates?.retire?.map((change) => (
                        <li key={typeof change === "string" ? change : change.id}>{changeTitle(change, campaign)}</li>
                      ))}
                    </ul>
                  ) : <p className="mt-2 text-xs text-muted-foreground">Keine geplanten PRs</p>}
                </article>
              </div>

              {artifacts.length ? (
                <article className="rounded-lg border border-border p-3">
                  <strong className="flex items-center gap-2 text-sm"><FileText className="size-4" /> Dokumente</strong>
                  <ul className="mt-2 grid gap-1 text-xs text-muted-foreground">
                    {artifacts.map((artifact) => <li key={artifact.id}>{artifact.title || "Dokument"}</li>)}
                  </ul>
                </article>
              ) : null}

              <div className="grid gap-3 sm:grid-cols-2">
                <article className="rounded-lg border border-border p-3">
                  <strong className="flex items-center gap-2 text-sm"><GitBranch className="size-4" /> Reihenfolge</strong>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {(patch?.dependencies?.replace_for_mutable?.length ?? 0)} Abhängigkeitsregeln und {(patch?.conflicts?.replace_for_mutable?.length ?? 0)} Konfliktregeln werden neu geprüft.
                  </p>
                </article>
                <article className="rounded-lg border border-border p-3">
                  <strong className="flex items-center gap-2 text-sm"><Link2 className="size-4" /> Wissenskette</strong>
                  <p className="mt-2 text-xs text-muted-foreground">{relationCount} Wissensverknüpfungen</p>
                </article>
              </div>
            </section> : (
              <p className="rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm text-warning">
                Der genaue Zielplan konnte nicht bestätigt werden. Lade die Planänderung neu;
                ohne vollständigen Detailvertrag ist keine Freigabe möglich.
              </p>
            )}

            <p className="rounded-lg border border-border bg-muted/30 p-3 text-sm">
              Laufende oder bereits gestartete geplante PRs werden nicht verändert
              {immutableCount ? ` (${immutableCount} geschützt)` : ""}. Prüfnachweise, GitHub-Daten und Auslieferungen bleiben unverändert.
            </p>
            <p className="rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm">
              Danach ist die normale Planfreigabe weiterhin nötig. Die Übernahme erstellt zuerst Plan v{amendment?.proposed_version ?? campaign.version + 1} als neuen Entwurf.
            </p>
            {notice ? (
              <p className="rounded-lg border border-success/30 bg-success/5 p-3 text-sm text-success" role="status">
                {notice}
              </p>
            ) : null}
            {error ? <p className="composer-error" role="alert">{error}</p> : null}
          </div>
        )}

        {!canCancel ? (
          <p className="rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm text-warning" role="status">
            Abbrechen ist erst möglich, wenn der zugehörige Planungsauftrag geladen ist. Aktualisiere die Ansicht.
          </p>
        ) : null}
        <DialogFooter className="gap-2 sm:justify-between">
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={busy || Boolean(notice) || !canCancel}
              onClick={() => setPendingDecision("cancelled")}
              variant="ghost"
            >
              Planänderung abbrechen
            </Button>
            <Button
              disabled={busy || loading || Boolean(notice)}
              onClick={() => setPendingDecision("rejected")}
              variant="secondary"
            >
              Änderung ablehnen
            </Button>
          </div>
          <Button
            disabled={busy || loading || Boolean(notice) || !targetReady}
            onClick={() => setPendingDecision("approved")}
          >
            Änderung übernehmen
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    <AlertDialog
      open={Boolean(pendingDecision)}
      onOpenChange={(nextOpen) => { if (!nextOpen && !busy) setPendingDecision(undefined); }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {pendingDecision === "approved"
              ? "Planänderung übernehmen?"
              : pendingDecision === "rejected"
                ? "Planänderung ablehnen?"
                : "Planänderung abbrechen?"}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {pendingDecision === "approved"
              ? "Der geprüfte Zielplan wird als neuer Entwurf gespeichert. Danach prüfst und genehmigst du den neuen Plan separat. Es startet noch keine Arbeit."
              : pendingDecision === "rejected"
                ? `Der aktuelle Plan bleibt unverändert. Der Plan kehrt zu „${previousStatusLabel}“ zurück.`
                : `Der vorgeschlagene Zielplan wird nicht angewendet und die fokussierte Neuplanung beendet. Der Plan kehrt zu „${previousStatusLabel}“ zurück.`}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Zurück</AlertDialogCancel>
          <AlertDialogAction
            disabled={busy}
            onClick={(event) => {
              event.preventDefault();
              const action = pendingDecision === "approved"
                ? onApprove
                : pendingDecision === "rejected"
                  ? onReject
                  : onCancel;
              void Promise.resolve(action()).finally(() => setPendingDecision(undefined));
            }}
          >
            {pendingDecision === "approved"
              ? "Änderung übernehmen"
              : pendingDecision === "rejected"
                ? "Änderung ablehnen"
                : "Planänderung abbrechen"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    </>
  );
}
