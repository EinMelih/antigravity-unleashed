import {
  ArrowUpRight,
  Check,
  Circle,
  GitBranch,
  GitCommitHorizontal,
  History,
  LoaderCircle,
  Play,
  Undo2,
} from "lucide-react";
import { useState, type ReactNode } from "react";

import type { ControlPolicy, ControlPrCandidate } from "@/api/contracts";
import { EntityDetailDrawer, type EntityDetailTab } from "@/components/entity-detail-drawer";
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
  activateCandidate,
  cancelWorkOrder,
  runControlExecutorOnce,
} from "@/features/automation/api";
import type { AutomationWorkItem } from "@/features/automation/model";
import {
  riskLabel,
  workItemStatusLabels,
  workItemStatusTone,
} from "@/features/automation/presentation";
import { WorkItemDelivery } from "@/features/automation/work-item-delivery";

interface WorkItemDetailProps {
  item?: AutomationWorkItem;
  onChanged: () => Promise<void> | void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  policy: ControlPolicy;
}

interface ActiveWorkItemDetailProps extends Omit<WorkItemDetailProps, "item"> {
  item: AutomationWorkItem;
}

function DetailSection({ children, title }: { children: ReactNode; title: string }) {
  return (
    <section className="detail-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function DetailValue({ label, value }: { label: string; value?: ReactNode }) {
  return (
    <div className="detail-value">
      <dt>{label}</dt>
      <dd>{value || "–"}</dd>
    </div>
  );
}

function CodeValue({ children }: { children?: string | null }) {
  return <code className="detail-code">{children || "–"}</code>;
}

function Checklist({
  items,
  missing = [],
}: {
  items: Array<{ key: string; text: string }>;
  missing?: string[];
}) {
  if (items.length === 0) return <p className="detail-muted">Noch keine Einträge.</p>;
  const missingSet = new Set(missing);
  return (
    <ul className="detail-checklist">
      {items.map((item) => {
        const open = missingSet.has(item.key);
        return (
          <li key={item.key}>
            {open ? (
              <Circle className="mt-0.5 size-4 shrink-0 text-warning" />
            ) : (
              <Check className="mt-0.5 size-4 shrink-0 text-success" />
            )}
            <span>{item.text}</span>
          </li>
        );
      })}
    </ul>
  );
}

function formatActivityDate(value: string) {
  if (!value) return "Unbekannter Zeitpunkt";
  const normalized = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("de-DE", {
        dateStyle: "short",
        timeStyle: "short",
      }).format(date);
}

function isVisiblyUnstarted(candidate: ControlPrCandidate) {
  const task = candidate.task;
  const pack = candidate.evidence_pack;
  return Boolean(
    candidate.status === "approved" &&
      candidate.work_order?.status === "approved" &&
      task?.status === "queued" &&
      task.attempt === 0 &&
      !task.started_at &&
      !task.current_sha &&
      !task.merged_sha &&
      !task.worktree_path &&
      !task.antigravity_chat_id &&
      task.issue_number == null &&
      !task.issue_url &&
      task.pr_number == null &&
      !task.pr_url &&
      !task.last_error &&
      pack?.status === "collecting" &&
      !pack.sha &&
      !pack.summary &&
      !pack.preview_url &&
      Object.keys(pack.risk ?? {}).length === 0 &&
      Object.keys(pack.test_pack ?? {}).length === 0,
  );
}

export function WorkItemDetail({
  item,
  ...props
}: WorkItemDetailProps) {
  if (!item) return null;
  return <ActiveWorkItemDetail {...props} item={item} key={item.id} />;
}

function ActiveWorkItemDetail({
  item,
  onChanged,
  onOpenChange,
  open,
  policy,
}: ActiveWorkItemDetailProps) {
  const [confirmation, setConfirmation] = useState<"activate" | "cancel" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { campaign, candidate } = item;
  const task = candidate.task;
  const pack = candidate.evidence_pack;
  const contract = candidate.contract;
  const missing = pack?.test_pack.missing ?? [];
  const acceptanceItems = (pack?.test_pack.acceptance_criteria ?? []).length
    ? pack?.test_pack.acceptance_criteria ?? []
    : candidate.acceptance_criteria.map((text, index) => ({
        key: `acceptance:${index + 1}`,
        text,
      }));
  const requiredChecks = pack?.test_pack.required_checks ??
    (contract?.required_checks ?? []).map((text) => ({ key: `check:${text}`, text }));
  const manualTests = pack?.test_pack.manual_tests ??
    (contract?.manual_tests ?? []).map((text, index) => ({
      key: `manual:${index + 1}`,
      text,
    }));

  const tabs: EntityDetailTab[] = [
    {
      id: "overview",
      label: "Übersicht",
      content: (
        <div className="space-y-6">
          {item.attention.length > 0 ? (
            <div className="detail-attention">
              <strong>{item.attention[0]?.title || "Entscheidung erforderlich"}</strong>
              <p>{item.attention[0]?.recommendation || item.attention[0]?.consequence}</p>
            </div>
          ) : null}
          <DetailSection title="Nächster sinnvoller Schritt">
            <p className="detail-copy">{item.nextStep}</p>
          </DetailSection>
          <DetailSection title="Aufgabe">
            <p className="detail-copy">{candidate.scope}</p>
          </DetailSection>
          <dl className="detail-grid">
            <DetailValue label="Projekt" value={item.projectName} />
            <DetailValue label="Campaign" value={campaign.title} />
            <DetailValue label="Risiko" value={riskLabel(item.risk)} />
            <DetailValue label="Rolle" value={task?.role || "Planung"} />
          </dl>
          {task?.last_error ? (
            <DetailSection title="Letzter Fehler">
              <p className="detail-error">{task.last_error}</p>
            </DetailSection>
          ) : null}
        </div>
      ),
    },
    {
      id: "plan",
      label: "Plan",
      content: (
        <div className="space-y-6">
          <DetailSection title="Ziel der Campaign">
            <p className="detail-copy">{campaign.goal}</p>
          </DetailSection>
          {candidate.non_goals || campaign.non_goals ? (
            <DetailSection title="Bewusste Nicht-Ziele">
              <p className="detail-copy">{candidate.non_goals || campaign.non_goals}</p>
            </DetailSection>
          ) : null}
          <DetailSection title="Akzeptanzkriterien">
            <Checklist items={acceptanceItems} missing={missing} />
          </DetailSection>
          <dl className="detail-grid">
            <DetailValue label="Planversion" value={`v${campaign.version}`} />
            <DetailValue label="Priorität" value={String(candidate.priority)} />
            <DetailValue
              label="Abhängigkeiten"
              value={candidate.depends_on.length ? candidate.depends_on.join(", ") : "Keine"}
            />
            <DetailValue label="Umfang" value={contract?.estimated_size || "Nicht geschätzt"} />
          </dl>
          {contract?.definition_of_done ? (
            <DetailSection title="Definition of Done">
              <p className="detail-copy">{contract.definition_of_done}</p>
            </DetailSection>
          ) : null}
        </div>
      ),
    },
    {
      id: "changes",
      label: "Änderungen",
      content: (
        <div className="space-y-6">
          <dl className="detail-stack">
            <DetailValue label="Branch" value={<CodeValue>{task?.branch_name}</CodeValue>} />
            <DetailValue label="Worktree" value={<CodeValue>{task?.worktree_path}</CodeValue>} />
            <DetailValue label="Basis-SHA" value={<CodeValue>{task?.base_sha || candidate.base_sha}</CodeValue>} />
            <DetailValue label="Aktueller SHA" value={<CodeValue>{task?.current_sha}</CodeValue>} />
          </dl>
          <DetailSection title="Geplanter Dateiumfang">
            {contract?.components.length ? (
              <ul className="detail-chip-list">
                {contract.components.map((component) => (
                  <li key={component}>{component}</li>
                ))}
              </ul>
            ) : (
              <p className="detail-muted">Kein Komponentenvertrag hinterlegt.</p>
            )}
          </DetailSection>
          {contract?.reversibility ? (
            <DetailSection title="Rückrollbarkeit">
              <p className="detail-copy">{contract.reversibility}</p>
            </DetailSection>
          ) : null}
        </div>
      ),
    },
    {
      id: "evidence",
      label: "Tests & Evidence",
      content: (
        <div className="space-y-6">
          <div className="detail-evidence-summary">
            <span>
              <strong>{pack?.status || "Noch kein Evidence Pack"}</strong>
              <small>{pack?.summary || "Nachweise werden nach Task-Aktivierung gesammelt."}</small>
            </span>
            <Badge variant={missing.length ? "attention" : "healthy"}>
              {missing.length ? `${missing.length} offen` : "Vollständig"}
            </Badge>
          </div>
          <DetailSection title="Automatische Checks">
            <Checklist items={requiredChecks} missing={missing} />
          </DetailSection>
          <DetailSection title="Manuelle Tests">
            <Checklist items={manualTests} missing={missing} />
          </DetailSection>
          <DetailSection title="Findings">
            {candidate.findings.length ? (
              <ul className="detail-findings">
                {candidate.findings.map((finding) => (
                  <li key={finding.id}>
                    <Badge variant={finding.status === "open" ? "attention" : "healthy"}>
                      {finding.classification} · {finding.status === "open" ? "Offen" : "Gelöst"}
                    </Badge>
                    <p>{finding.body}</p>
                    {finding.status !== "open" && finding.resolution ? (
                      <p className="detail-muted">Gelöst: {finding.resolution}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="detail-muted">Keine Findings erfasst.</p>
            )}
          </DetailSection>
          {pack?.rollback_plan ? (
            <DetailSection title="Rollback-Plan">
              <p className="detail-copy">{pack.rollback_plan}</p>
            </DetailSection>
          ) : null}
        </div>
      ),
    },
    {
      id: "github",
      label: "GitHub",
      content: (
        <div className="space-y-6">
          <dl className="detail-stack">
            <DetailValue
              label="Issue"
              value={
                task?.issue_url ? (
                  <a className="detail-link" href={task.issue_url} rel="noreferrer" target="_blank">
                    Issue #{task.issue_number} <ArrowUpRight className="size-3.5" />
                  </a>
                ) : (
                  "Noch nicht erstellt"
                )
              }
            />
            <DetailValue
              label="Pull Request"
              value={
                task?.pr_url ? (
                  <a className="detail-link" href={task.pr_url} rel="noreferrer" target="_blank">
                    PR #{task.pr_number} <ArrowUpRight className="size-3.5" />
                  </a>
                ) : (
                  "Noch nicht erstellt"
                )
              }
            />
            <DetailValue label="Branch" value={<CodeValue>{task?.branch_name}</CodeValue>} />
            <DetailValue label="Freigabe-SHA" value={<CodeValue>{candidate.work_order?.approval_sha}</CodeValue>} />
            <DetailValue label="Aktueller SHA" value={<CodeValue>{task?.current_sha}</CodeValue>} />
            <DetailValue label="Merge-SHA" value={<CodeValue>{task?.merged_sha}</CodeValue>} />
          </dl>
          {task ? (
            <WorkItemDelivery candidate={candidate} key={task.id} onChanged={onChanged} />
          ) : null}
        </div>
      ),
    },
    {
      id: "activity",
      label: "Aktivität",
      content: (
        <div>
          {item.activity.length ? (
            <ol className="detail-timeline">
              {item.activity.map((activity, index) => (
                <li key={`${activity.kind}-${activity.item.id}-${index}`}>
                  <span className="detail-timeline-icon">
                    {activity.kind === "checkpoint" ? (
                      <GitCommitHorizontal className="size-4" />
                    ) : (
                      <History className="size-4" />
                    )}
                  </span>
                  <div>
                    <strong>
                      {activity.kind === "checkpoint"
                        ? activity.item.summary
                        : activity.item.action.replaceAll("_", " ").replaceAll(".", " · ")}
                    </strong>
                    <p>
                      {activity.kind === "checkpoint"
                        ? activity.item.actor
                        : activity.item.reason || `${activity.item.from_state || "–"} → ${activity.item.to_state || "–"}`}
                    </p>
                    <time>{formatActivityDate(activity.createdAt)}</time>
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p className="detail-muted">Für dieses Work Item gibt es noch keine Aktivität.</p>
          )}
        </div>
      ),
    },
  ];

  const legacyUrl = task
    ? `/dashboard/legacy?review=${encodeURIComponent(task.id)}&project_id=${encodeURIComponent(item.projectId)}`
    : "/dashboard/legacy";
  const canActivate =
    campaign.status === "approved" &&
    candidate.status === "ready" &&
    Boolean(candidate.base_sha) &&
    (!candidate.work_order || candidate.work_order.status === "cancelled") &&
    policy.mode === "guided" &&
    !policy.paused;
  const canCancel = isVisiblyUnstarted(candidate);

  async function runAction(action: "activate" | "cancel") {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      if (action === "activate") {
        await activateCandidate(
          candidate.id,
          candidate.base_sha,
          "PR-Slice im Anti-Gravity Hub nach Scope- und SHA-Prüfung freigegeben.",
        );
        try {
          await runControlExecutorOnce();
        } catch (tickError) {
          setError(
            `Der Arbeitsauftrag ist eingeplant, aber der Executor konnte gerade nicht gestartet werden: ${
              tickError instanceof Error ? tickError.message : String(tickError)
            }`,
          );
        }
      } else if (candidate.work_order) {
        await cancelWorkOrder(
          candidate.work_order.id,
          "Freigabe vor Beginn der Ausführung im Anti-Gravity Hub zurückgenommen.",
        );
      }
      await onChanged();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : String(actionError));
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <EntityDetailDrawer
      action={
        <div className="grid gap-2">
          <div className="flex flex-wrap gap-2">
          {canActivate ? (
            <Button disabled={busy} onClick={() => setConfirmation("activate")} size="sm">
              {busy ? <LoaderCircle className="size-3.5 motion-safe:animate-spin" /> : <Play className="size-3.5" />}
              PR-Slice freigeben
            </Button>
          ) : null}
          {canCancel ? (
            <Button disabled={busy} onClick={() => setConfirmation("cancel")} size="sm" variant="secondary">
              <Undo2 className="size-3.5" />
              Freigabe zurücknehmen
            </Button>
          ) : null}
          <Button asChild size="sm" variant={canActivate || canCancel ? "secondary" : "default"}>
            <a href={legacyUrl}>Im Control Center öffnen</a>
          </Button>
          {task?.pr_url ? (
            <Button asChild size="sm" variant="secondary">
              <a href={task.pr_url} rel="noreferrer" target="_blank">
                Pull Request <ArrowUpRight className="size-3.5" />
              </a>
            </Button>
          ) : null}
          </div>
          {campaign.status === "approved" && candidate.status === "ready" && policy.paused ? (
            <p className="text-xs text-muted-foreground">Automation ist pausiert. Nach dem Fortsetzen kann dieser Slice freigegeben werden.</p>
          ) : null}
          {campaign.status === "approved" && candidate.status === "ready" && policy.mode !== "guided" ? (
            <p className="text-xs text-muted-foreground">Dieser Slice wird durch den gewählten automatischen Campaign-Modus eingeplant.</p>
          ) : null}
          {error ? <p className="detail-error" role="alert">{error}</p> : null}
        </div>
      }
      description={`${item.projectName} · ${campaign.title}`}
      entityKey={item.id}
      onOpenChange={onOpenChange}
      open={open}
      status={
        <>
          <Badge variant={workItemStatusTone(item.status)}>
            {workItemStatusLabels[item.status] || item.status}
          </Badge>
          <Badge variant="neutral">{riskLabel(item.risk)}</Badge>
          {task?.branch_name ? (
            <span className="flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
              <GitBranch className="size-3.5" />
              <span className="max-w-52 truncate">{task.branch_name}</span>
            </span>
          ) : null}
        </>
      }
      tabs={tabs}
      title={item.title}
      />

      <AlertDialog
        onOpenChange={(nextOpen) => { if (!nextOpen) setConfirmation(null); }}
        open={confirmation === "activate"}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>PR-Slice wirklich freigeben?</AlertDialogTitle>
            <AlertDialogDescription>
              Anti-Gravity erstellt den Arbeitsauftrag ausschließlich für Basis-SHA {candidate.base_sha.slice(0, 12)}.
              Abhängigkeiten und sichere Wave-Reihenfolge werden serverseitig nochmals geprüft.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Abbrechen</AlertDialogCancel>
            <AlertDialogAction onClick={() => void runAction("activate")}>Jetzt freigeben</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        onOpenChange={(nextOpen) => { if (!nextOpen) setConfirmation(null); }}
        open={confirmation === "cancel"}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Arbeitsauftrag wirklich zurücknehmen?</AlertDialogTitle>
            <AlertDialogDescription>
              Nur dieser laut aktuellem Stand noch nicht gestartete Arbeitsauftrag wird storniert. Plan und PR-Slice bleiben erhalten und können später erneut freigegeben werden.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Abbrechen</AlertDialogCancel>
            <AlertDialogAction onClick={() => void runAction("cancel")}>Zurücknehmen</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
