import { AlertTriangle, ChevronRight, GitPullRequest, ListChecks } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { AutomationWorkItem } from "@/features/automation/model";
import {
  riskLabel,
  workItemStatusLabels,
  workItemStatusTone,
} from "@/features/automation/presentation";

interface WorkItemListProps {
  items: AutomationWorkItem[];
  onSelect: (item: AutomationWorkItem) => void;
  selectedId?: string;
}

export function WorkItemList({ items, onSelect, selectedId }: WorkItemListProps) {
  return (
    <ul className="automation-work-list">
      {items.map((item) => {
        const task = item.candidate.task;
        const evidence = item.candidate.evidence_pack;
        const missing = evidence?.test_pack.missing?.length ?? 0;
        return (
          <li key={item.id}>
            <button
              aria-current={selectedId === item.id ? "true" : undefined}
              className="automation-work-row"
              onClick={() => onSelect(item)}
              type="button"
            >
              <span className="automation-work-icon">
                {item.attention.length > 0 || task?.last_error ? (
                  <AlertTriangle className="size-4 text-warning" />
                ) : task?.pr_number ? (
                  <GitPullRequest className="size-4 text-primary" />
                ) : (
                  <ListChecks className="size-4 text-muted-foreground" />
                )}
              </span>
              <span className="min-w-0 flex-1 text-left">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-semibold">{item.title}</span>
                  <Badge variant={workItemStatusTone(item.status)}>
                    {workItemStatusLabels[item.status] || item.status}
                  </Badge>
                </span>
                <span className="mt-1 block truncate text-xs text-muted-foreground">
                  {item.projectName} · {item.nextStep}
                </span>
              </span>
              <span className="hidden shrink-0 text-right md:block">
                <span className="block text-xs text-muted-foreground">{riskLabel(item.risk)}</span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {missing > 0 ? `${missing} Gates offen` : "Evidence aktuell"}
                </span>
              </span>
              <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
            </button>
          </li>
        );
      })}
    </ul>
  );
}
