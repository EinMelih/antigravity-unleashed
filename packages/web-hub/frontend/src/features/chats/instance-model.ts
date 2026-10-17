import type {
  AntigravityBindingStatus,
  AntigravityInstance,
  AntigravityInstanceActivity,
  AntigravityInstanceAvailability,
  AntigravityInstanceRole,
} from "@/api/contracts";

const AVAILABILITY_PRIORITY: Record<AntigravityInstanceAvailability, number> = {
  online: 1,
  unreachable: 0,
};

const ROLE_PRIORITY: Record<AntigravityInstanceRole, number> = {
  worker: 3,
  primary: 2,
  dictation: 1,
};

const ACTIVITY_PRIORITY: Record<AntigravityInstanceActivity, number> = {
  waiting_human: 8,
  error: 7,
  working: 6,
  sending: 5,
  preparing: 4,
  idle: 3,
  manual: 2,
  unknown: 1,
};

const BINDING_PRIORITY: Record<AntigravityBindingStatus, number> = {
  confirmed: 3,
  mismatch: 2,
  none: 1,
};

export type InstanceIndicatorTone = "healthy" | "attention" | "blocked";

export interface InstanceIndicator {
  label: string;
  tone: InstanceIndicatorTone;
}

function finiteTimestamp(value: number | null | undefined): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function compareInstancePriority(
  left: AntigravityInstance,
  right: AntigravityInstance,
): number {
  const leftPriority = [
    AVAILABILITY_PRIORITY[left.availability],
    ROLE_PRIORITY[left.role],
    ACTIVITY_PRIORITY[left.activity],
    BINDING_PRIORITY[left.binding_status],
    Number(left.focused),
    finiteTimestamp(left.updated_at),
  ];
  const rightPriority = [
    AVAILABILITY_PRIORITY[right.availability],
    ROLE_PRIORITY[right.role],
    ACTIVITY_PRIORITY[right.activity],
    BINDING_PRIORITY[right.binding_status],
    Number(right.focused),
    finiteTimestamp(right.updated_at),
  ];
  for (let index = 0; index < leftPriority.length; index += 1) {
    const difference = (leftPriority[index] ?? 0) - (rightPriority[index] ?? 0);
    if (difference) return difference;
  }
  const leftStableId = `${left.instance_id}\u0000${left.instance_ref}`;
  const rightStableId = `${right.instance_id}\u0000${right.instance_ref}`;
  if (leftStableId === rightStableId) return 0;
  return leftStableId < rightStableId ? 1 : -1;
}

export function instanceActivityLabel(activity: AntigravityInstanceActivity): string {
  const labels: Record<AntigravityInstanceActivity, string> = {
    manual: "Hauptfenster",
    idle: "Bereit",
    preparing: "Wird vorbereitet",
    sending: "Sendet",
    working: "Arbeitet",
    waiting_human: "Freigabe nötig",
    error: "Fehler",
    unknown: "Unbekannt",
  };
  return labels[activity];
}

export function instanceLabel(instance: AntigravityInstance): string {
  const id = instance.instance_id || (instance.role === "primary" ? "MAIN" : "AG");
  const activity = instance.availability === "unreachable"
    ? "Nicht erreichbar"
    : instanceActivityLabel(instance.activity);
  return `${id} · ${activity}`;
}

export function instanceIndicator(instance: AntigravityInstance): InstanceIndicator {
  let tone: InstanceIndicatorTone = "healthy";
  if (instance.availability === "unreachable" || instance.activity === "error") {
    tone = "blocked";
  } else if (
    instance.activity === "unknown"
    || instance.activity === "waiting_human"
    || instance.binding_status === "mismatch"
  ) {
    tone = "attention";
  }
  return { label: instanceLabel(instance), tone };
}

export function instancesByConversation(instances: readonly AntigravityInstance[]) {
  const result = new Map<string, AntigravityInstance>();
  for (const instance of instances) {
    const conversationId = instance.conversation?.conversation_id;
    if (!conversationId) continue;
    const selected = result.get(conversationId);
    if (!selected || compareInstancePriority(instance, selected) > 0) {
      result.set(conversationId, instance);
    }
  }
  return result;
}
