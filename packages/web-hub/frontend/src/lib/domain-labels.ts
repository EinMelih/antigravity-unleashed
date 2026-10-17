function normalized(value: string | null | undefined) {
  return String(value || "").trim().toLowerCase().replaceAll("-", "_");
}

const statusLabels: Record<string, string> = {
  accepted: "Akzeptiert",
  active: "Aktiv",
  approved: "Freigegeben",
  cancelled: "Beendet",
  complete: "Vollständig",
  completed: "Abgeschlossen",
  deprecated: "Veraltet",
  draft: "Entwurf",
  failed: "Fehlgeschlagen",
  healthy: "Fehlerfrei",
  inbox: "Im Eingang",
  materialized: "Als Datei gespeichert",
  merged: "Zusammengeführt",
  not_requested: "Nicht angefordert",
  obsolete: "Aus dem Plan genommen",
  paused: "Pausiert",
  pending: "Ausstehend",
  planned: "Geplant",
  proposed: "Vorgeschlagen",
  ready: "Bereit",
  ready_for_human: "Bereit zur Prüfung",
  recorded: "Aufgezeichnet",
  rejected: "Abgelehnt",
  retired: "Aus dem Plan genommen",
  review: "Prüfung offen",
  running: "In Arbeit",
  superseded: "Ersetzt",
  waiting_human: "Entscheidung nötig",
  waiting_review: "Prüfung offen",
};

const artifactTypeLabels: Record<string, string> = {
  adr: "Architekturentscheidung",
  decision_ledger: "Entscheidungsprotokoll",
  design: "Technisches Konzept",
  design_document: "Technisches Konzept",
  idea_group: "Ideen-Dokument",
  implementation_plan: "Umsetzungsplan",
  repository_map: "Projektübersicht",
};

const relationLabels: Record<string, string> = {
  contains: "enthält",
  decided_by: "entschieden durch",
  developed_into: "weiterentwickelt zu",
  documents: "dokumentiert",
  follows_decision: "folgt der Entscheidung",
  implements: "setzt um",
  implements_design: "setzt das Konzept um",
  informs: "liefert die Grundlage für",
  informed_by: "berücksichtigt",
  references: "verweist auf",
  supersedes: "ersetzt",
};

const sourceLabels: Record<string, string> = {
  agent: "Von Anti-Gravity",
  antigravity: "Von Anti-Gravity",
  chat: "Aus einem Chat",
  human: "Von dir",
  planner: "Aus der Planung",
  telegram: "Über Telegram",
};

const environmentLabels: Record<string, string> = {
  development: "Entwicklung",
  local: "Lokal",
  preview: "Vorschau",
  production: "Produktion",
  staging: "Testumgebung",
};

const planFieldLabels: Record<string, string> = {
  acceptance_matrix: "Abnahmekriterien",
  activation_policy: "Startregeln",
  assumptions: "Annahmen",
  base_sha: "Codebasis",
  constraints: "Vorgaben",
  goal: "Ziel",
  non_goals: "Nicht-Ziele",
  pivotal_fork: "Zentrale Entscheidung",
  planning_depth: "Planungstiefe",
  requested_max_candidates: "Maximale geplante PRs",
  risk_level: "Risiko",
  rollback_plan: "Rückkehrplan",
  rollout_plan: "Auslieferungsplan",
  success_metrics: "Erfolgskriterien",
  title: "Titel",
};

export function domainStatusLabel(value: string | null | undefined, fallback = "Unbekannter Zustand") {
  return statusLabels[normalized(value)] || fallback;
}

export function artifactTypeLabel(value: string | null | undefined) {
  return artifactTypeLabels[normalized(value)] || "Weiteres Dokument";
}

export function knowledgeRelationLabel(value: string | null | undefined) {
  return relationLabels[normalized(value)] || "inhaltlich verknüpft mit";
}

export function knowledgeSourceLabel(value: string | null | undefined) {
  return sourceLabels[normalized(value)] || "Quelle aufgezeichnet";
}

export function deploymentEnvironmentLabel(value: string | null | undefined) {
  return environmentLabels[normalized(value)] || "Weitere Umgebung";
}

export function planFieldLabel(value: string | null | undefined) {
  return planFieldLabels[normalized(value)] || "Weitere Planeinstellung";
}
