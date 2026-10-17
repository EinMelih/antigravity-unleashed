export const workItemStatusLabels: Record<string, string> = {
  waiting_human: "Entscheidung nötig",
  waiting_review: "Review offen",
  failed: "Fehlgeschlagen",
  repair: "Reparatur",
  paused: "Pausiert",
  waiting_ci: "Checks laufen",
  running: "In Arbeit",
  leased: "Vorbereitung",
  queued: "Eingeplant",
  approved: "Freigegeben",
  ready: "Bereit",
  review: "Review",
  completed: "Abgeschlossen",
  merged: "Gemergt",
  cancelled: "Beendet",
};

export function workItemStatusTone(status: string) {
  if (["failed"].includes(status)) return "blocked" as const;
  if (["waiting_human", "waiting_review", "repair", "paused"].includes(status)) {
    return "attention" as const;
  }
  if (["running", "waiting_ci", "leased"].includes(status)) return "accent" as const;
  if (["completed", "merged"].includes(status)) return "healthy" as const;
  return "neutral" as const;
}

export function riskLabel(risk: string) {
  const labels: Record<string, string> = {
    low: "Niedriges Risiko",
    medium: "Mittleres Risiko",
    high: "Hohes Risiko",
    critical: "Kritisches Risiko",
  };
  return labels[risk] || risk;
}
