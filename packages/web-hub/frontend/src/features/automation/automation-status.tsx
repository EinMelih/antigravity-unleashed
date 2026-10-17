import { Bot, Server, ShieldAlert } from "lucide-react";

import type {
  ControlOverviewResponse,
  HubHealthResponse,
  WorkersResponse,
} from "@/api/contracts";

interface AutomationStatusProps {
  control: ControlOverviewResponse;
  health?: HubHealthResponse;
  workers?: WorkersResponse;
  workersError: boolean;
  workersLoading: boolean;
}

export function AutomationStatus({
  control,
  health,
  workers,
  workersError,
  workersLoading,
}: AutomationStatusProps) {
  const workerValue = workers
    ? workers.capacity.active === 0
      ? "Bereit"
      : `${workers.capacity.active} ${workers.capacity.active === 1 ? "Ausführung" : "Ausführungen"} aktiv`
    : workersError
      ? "Nicht erreichbar"
      : workersLoading
        ? "Wird geprüft"
        : "Noch keine Daten";
  const decisionCount = control.summary.human_gates_open;
  const items = [
    {
      icon: ShieldAlert,
      label: "Deine Prüfung",
      value:
        decisionCount === 0
          ? "Nichts offen"
          : `${decisionCount} ${decisionCount === 1 ? "Entscheidung" : "Entscheidungen"} offen`,
      state: decisionCount > 0 ? "attention" : "healthy",
    },
    {
      icon: Bot,
      label: "Ausführung",
      value: control.policy.paused ? "Pausiert" : workerValue,
      state: control.policy.paused || workersError ? "attention" : "neutral",
    },
    {
      icon: Server,
      label: "System",
      value: health?.status === "ok" ? "Verbunden" : "Wird geprüft",
      state: health?.status === "ok" ? "healthy" : "attention",
    },
  ] as const;

  return (
    <section aria-label="Status der Automatisierung" className="automation-status-strip">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <div className="automation-status-item" key={item.label}>
            <Icon className="size-4 text-muted-foreground" />
            <span className="min-w-0">
              <span className="block text-xs text-muted-foreground">{item.label}</span>
              <span className="mt-0.5 block truncate text-sm font-medium">
                {item.value}
              </span>
            </span>
            <span className={`status-dot is-${item.state}`} />
          </div>
        );
      })}
    </section>
  );
}
