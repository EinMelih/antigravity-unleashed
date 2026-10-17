import { ArrowUpRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { AttentionQueueEntry } from "@/features/automation/model";

function urgencyLabel(urgency: string) {
  if (urgency === "critical") return "Sofort";
  if (urgency === "high") return "Wichtig";
  if (urgency === "low") return "Niedrig";
  return "Normal";
}

function urgencyTone(urgency: string) {
  if (urgency === "critical") return "blocked" as const;
  if (urgency === "high") return "attention" as const;
  return "neutral" as const;
}

export function AttentionQueue({
  entries,
  onOpenPlanning,
  onOpenWorkItem,
}: {
  entries: AttentionQueueEntry[];
  onOpenPlanning: (campaignId: string, planningJobId?: string) => void;
  onOpenWorkItem: (workItemId: string) => void;
}) {
  return (
    <section aria-labelledby="attention-queue-title" className="attention-queue">
      <div className="attention-queue-heading">
        <div>
          <p className="eyebrow">Offene Entscheidungen</p>
          <h2 id="attention-queue-title">Braucht deine Entscheidung</h2>
        </div>
        <span>{entries.length} offen</span>
      </div>

      {entries.length === 0 ? (
        <p className="attention-queue-empty">Aktuell braucht nichts deine Entscheidung.</p>
      ) : (
        <ul className="attention-queue-list">
          {entries.map((entry) => {
            const target = entry.target;
            return (
              <li key={entry.id}>
                <article className="attention-queue-item">
                  <div className="attention-queue-copy">
                    <div className="attention-queue-context">
                      <Badge variant={urgencyTone(entry.urgency)}>
                        {urgencyLabel(entry.urgency)}
                      </Badge>
                      <span>{entry.categoryLabel}</span>
                      <span aria-hidden="true">·</span>
                      <span>{entry.projectName}</span>
                    </div>
                    <h3>{entry.title}</h3>
                    <p>
                      <strong>Folge:</strong>{" "}
                      {entry.consequence || "Die Arbeit wartet auf eine Entscheidung."}
                    </p>
                    <p>
                      <strong>Empfehlung:</strong>{" "}
                      {entry.recommendation || "Den aktuellen Stand prüfen."}
                    </p>
                  </div>

                  {target.kind === "planning" ? (
                    <Button
                      aria-label={`Plan öffnen: ${entry.title}`}
                      onClick={() => onOpenPlanning(target.campaignId, target.planningJobId)}
                      size="sm"
                      type="button"
                      variant="secondary"
                    >
                      Plan öffnen
                      <ArrowUpRight />
                    </Button>
                  ) : target.kind === "work_item" ? (
                    <Button
                      aria-label={`Arbeit öffnen: ${entry.title}`}
                      onClick={() => onOpenWorkItem(target.workItemId)}
                      size="sm"
                      type="button"
                      variant="secondary"
                    >
                      Arbeit öffnen
                      <ArrowUpRight />
                    </Button>
                  ) : (
                    <span className="attention-queue-information">
                      Keine direkte Aktion verfügbar.
                    </span>
                  )}
                </article>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
