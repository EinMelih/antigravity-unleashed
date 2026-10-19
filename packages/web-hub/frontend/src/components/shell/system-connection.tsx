import { Bot, ChevronDown, CircleDot } from "lucide-react";

import type { AntigravityInstance } from "@/api/contracts";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { instanceActivityLabel } from "@/features/chats/instance-model";
import { useAntigravityInstances } from "@/hooks/use-antigravity-instances";
import { useHubHealth } from "@/hooks/use-hub-health";

const BUSY_ACTIVITIES = new Set(["preparing", "sending", "working"]);

function displayInstances(instances: readonly AntigravityInstance[]) {
  return instances.filter((instance) => instance.role !== "dictation");
}

export function SystemConnection() {
  const health = useHubHealth();
  const isHeadless = health.data?.runtime_mode === "headless_linux";
  const fleet = useAntigravityInstances({ enabled: !isHeadless });

  if (health.isPending) return <Badge>Verbindung wird geprüft</Badge>;
  if (health.isError) return <Badge variant="blocked">Hub nicht erreichbar</Badge>;
  if (health.data.runtime_mode === "headless_linux") {
    return health.data.antigravity_backend.connected ? (
      <Badge variant="healthy">
        <CircleDot className="mr-1 size-3" />Headless Linux · Direct RPC
      </Badge>
    ) : (
      <Badge variant="attention">Headless Linux · API startet</Badge>
    );
  }
  if (!health.data.antigravity_backend.connected) {
    return <Badge variant="attention">Hub online · Anti-Gravity wartet</Badge>;
  }
  if (fleet.isPending) return <Badge variant="attention">Instanzen werden geprüft</Badge>;
  if (fleet.isError || !fleet.data) return <Badge variant="attention">Instanzstatus nicht verfügbar</Badge>;
  if (!["online", "degraded", "offline"].includes(fleet.data.connection)) {
    return <Badge variant="attention">Instanzstatus nicht verfügbar</Badge>;
  }
  if (fleet.data.connection === "offline") {
    return <Badge variant="blocked">Anti-Gravity offline</Badge>;
  }

  const instances = displayInstances(fleet.data.instances ?? []);
  const busy = instances.filter((instance) => (
    instance.availability === "online" && BUSY_ACTIVITIES.has(instance.activity)
  )).length;
  const errors = instances.filter((instance) => instance.activity === "error").length;
  const unreachable = instances.filter((instance) => instance.availability === "unreachable").length;
  const mismatched = instances.filter((instance) => instance.binding_status === "mismatch").length;
  const waitingHuman = instances.filter((instance) => instance.activity === "waiting_human").length;
  const unknown = instances.filter((instance) => (
    instance.availability === "online" && instance.activity === "unknown"
  )).length;
  const stateSummary = errors
    ? `${errors} Fehler`
    : unreachable
      ? `${unreachable} nicht erreichbar`
      : mismatched
        ? "Zuordnung prüfen"
        : unknown
          ? "Status unklar"
          : waitingHuman
            ? "Freigabe nötig"
            : busy
              ? `${busy} aktiv`
              : "bereit";
  const summary = instances.length
    ? `${instances.length} ${instances.length === 1 ? "Instanz" : "Instanzen"} · ${stateSummary}`
    : "Anti-Gravity verbunden";
  const variant = fleet.data.connection === "online" && !errors && !unreachable && !mismatched && !unknown && !waitingHuman
    ? "healthy"
    : "attention";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button aria-label={summary} className="system-instance-trigger" type="button">
          <Badge variant={variant}>
            <CircleDot className="mr-1 size-3" />{summary}<ChevronDown className="ml-1 size-3" />
          </Badge>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-80 p-2">
        <DropdownMenuLabel className="flex items-center justify-between px-2 py-1.5">
          <span>Anti-Gravity Instanzen</span>
          <span className="text-[0.68rem] font-medium text-muted-foreground">
            {fleet.data.connection === "degraded" ? "Teilweise erreichbar" : "Live"}
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <div className="grid gap-1" role="list">
          {instances.map((instance) => (
            <div className="system-instance-row" key={instance.instance_ref} role="listitem">
              <span className="system-instance-icon"><Bot className="size-3.5" /></span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center justify-between gap-2">
                  <strong>{instance.instance_id || (instance.role === "primary" ? "MAIN" : "AG")}</strong>
                  <span className="system-instance-activity" data-activity={instance.activity}>
                    {instance.availability === "unreachable" ? "Nicht erreichbar" : instanceActivityLabel(instance.activity)}
                  </span>
                </span>
                <span className="mt-0.5 block truncate text-[0.7rem] text-muted-foreground">
                  {instance.conversation?.title || (instance.role === "primary" ? "Dein Hauptfenster" : "Kein Chat zugeordnet")}
                </span>
              </span>
            </div>
          ))}
          {!instances.length ? <p className="px-2 py-3 text-xs text-muted-foreground">Noch keine native Instanz erkannt.</p> : null}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
