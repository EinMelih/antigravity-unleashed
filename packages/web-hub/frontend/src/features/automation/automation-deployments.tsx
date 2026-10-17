import { ChevronDown, Server } from "lucide-react";
import { useState } from "react";

import type { ControlDeployment } from "@/api/contracts";


interface AutomationDeploymentsProps {
  deployments: ControlDeployment[];
}

const environmentLabels: Record<string, string> = {
  preview: "Preview",
  staging: "Staging",
  production: "Production",
};

const statusLabels: Record<string, { label: string; tone: string }> = {
  planned: { label: "Geplant (aufgezeichnet)", tone: "planned" },
  running: { label: "Läuft (aufgezeichnet)", tone: "running" },
  healthy: { label: "Gesund gemeldet", tone: "healthy" },
  failed: { label: "Fehlgeschlagen", tone: "failed" },
  rolled_back: { label: "Zurückgerollt", tone: "rolled-back" },
  cancelled: { label: "Abgebrochen", tone: "cancelled" },
};

const dateFormatter = new Intl.DateTimeFormat("de-DE", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const sensitiveKey = /(?:api[_-]?key|authorization|password|secret|token)/i;
const sensitiveAssignment =
  /\b([A-Za-z0-9_-]*(?:api[_-]?key|authorization|password|secret|token)[A-Za-z0-9_-]*)\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s,;]+)/gi;
const tokenShape = /\b(?:(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{10,}|sk-[A-Za-z0-9_-]{16,})\b/gi;

function redactText(value: string) {
  return value
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer [ausgeblendet]")
    .replace(sensitiveAssignment, (_match, key: string) => `${key}=[ausgeblendet]`)
    .replace(tokenShape, "[ausgeblendet]");
}

function truncate(value: string, limit = 160) {
  return value.length > limit ? `${value.slice(0, limit - 1)}…` : value;
}

function sanitizeValue(value: unknown, depth = 0): unknown {
  if (depth > 2) return "[gekürzt]";
  if (typeof value === "string") return truncate(redactText(value), 240);
  if (Array.isArray(value)) {
    return value.slice(0, 10).map((item) => sanitizeValue(item, depth + 1));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .slice(0, 20)
        .map(([key, item]) => [
          key,
          sensitiveKey.test(key) ? "[ausgeblendet]" : sanitizeValue(item, depth + 1),
        ]),
    );
  }
  return value;
}

function logPreview(value: unknown) {
  if (typeof value === "string") return truncate(redactText(value), 240);
  try {
    return truncate(JSON.stringify(sanitizeValue(value)), 240);
  } catch {
    return "[Logeintrag nicht darstellbar]";
  }
}

function safeReference(value: string | undefined) {
  const normalized = String(value || "").trim();
  if (!normalized) return "Nicht aufgezeichnet";
  try {
    const url = new URL(normalized);
    if (url.protocol === "http:" || url.protocol === "https:") {
      return truncate(`${url.origin}${url.pathname}`);
    }
  } catch {
    // Artifact references are not required to be URLs.
  }
  return truncate(redactText(normalized));
}

function formatDate(value: string | null | undefined) {
  if (!value) return "Noch offen";
  const parsed = new Date(value.includes("T") ? value : value.replace(" ", "T"));
  return Number.isNaN(parsed.getTime()) ? "Ungültiger Zeitwert" : dateFormatter.format(parsed);
}

function safeSha(value: string | null | undefined) {
  const normalized = String(value || "").trim();
  if (!normalized) return "Nicht aufgezeichnet";
  return /^[a-f0-9]{7,64}$/i.test(normalized) ? normalized : "Ungültiger SHA-Wert";
}

function healthLabel(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return "Nicht aufgezeichnet";
  }
  const health = value as Record<string, unknown>;
  if (health.ok === true || health.healthy === true) return "Gesund gemeldet";
  if (health.ok === false || health.healthy === false) return "Fehlerhaft gemeldet";
  if (typeof health.status === "string" && health.status.trim()) {
    return truncate(redactText(health.status.trim()), 80);
  }
  return "Ohne eindeutiges Ergebnis";
}

function displayStatus(status: string) {
  return statusLabels[status] ?? { label: "Unbekannter Zustand", tone: "unknown" };
}

export function AutomationDeployments({ deployments }: AutomationDeploymentsProps) {
  const [visibleLogs, setVisibleLogs] = useState<Set<string>>(() => new Set());
  const payloadReadable = Array.isArray(deployments);
  const rows = payloadReadable ? deployments : [];

  function toggleLogs(id: string) {
    setVisibleLogs((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <details className="automation-deployments">
      <summary className="automation-deployments-summary">
        <Server aria-hidden="true" className="size-4" />
        <span>
          <span className="automation-deployments-title">Delivery &amp; Deployments</span>
          <span className="automation-deployments-subtitle">
            {!payloadReadable
              ? "Delivery-Daten nicht lesbar"
              : rows.length === 1
                ? "1 aufgezeichneter Eintrag"
                : `${rows.length} aufgezeichnete Einträge`}
          </span>
        </span>
        <ChevronDown aria-hidden="true" className="automation-deployments-chevron size-4" />
      </summary>

      <div className="automation-deployments-content">
        <p className="automation-deployments-notice">
          Vom Control Center aufgezeichneter Zustand – kein Nachweis eines externen
          Provider-Deployments.
        </p>
        {!payloadReadable ? (
          <div className="automation-deployments-empty" role="status">
            <strong>Die aufgezeichneten Delivery-Daten konnten nicht dargestellt werden.</strong>
            <p>Aktualisiere die Ansicht. Andere Automation-Daten bleiben davon unberührt.</p>
          </div>
        ) : rows.length ? (
          <div className="automation-deployment-list">
            {rows.map((deployment) => {
            const status = displayStatus(deployment.status);
            const logs = Array.isArray(deployment.logs) ? deployment.logs : [];
            const logsVisible = visibleLogs.has(deployment.id);
            return (
              <article className="automation-deployment" key={deployment.id}>
                <header className="automation-deployment-header">
                  <div>
                    <span className="automation-deployment-environment">
                      {environmentLabels[deployment.environment] || "Unbekannte Umgebung"}
                    </span>
                    {deployment.rollback_of ? (
                      <span className="automation-deployment-lineage">
                        Rollback von {truncate(redactText(deployment.rollback_of), 48)}
                      </span>
                    ) : null}
                  </div>
                  <span className={`automation-deployment-status is-${status.tone}`}>
                    {status.label}
                  </span>
                </header>

                <dl className="automation-deployment-details">
                  <div>
                    <dt>SHA</dt>
                    <dd className="automation-deployment-sha">{safeSha(deployment.sha)}</dd>
                  </div>
                  {deployment.previous_stable_sha ? (
                    <div>
                      <dt>Vorheriger stabiler SHA</dt>
                      <dd className="automation-deployment-sha">{safeSha(deployment.previous_stable_sha)}</dd>
                    </div>
                  ) : null}
                  <div>
                    <dt>Artifact</dt>
                    <dd>{safeReference(deployment.artifact_ref)}</dd>
                  </div>
                  <div>
                    <dt>Vorschau-URL</dt>
                    <dd>{safeReference(deployment.preview_url)}</dd>
                  </div>
                  <div>
                    <dt>Health</dt>
                    <dd>{healthLabel(deployment.health)}</dd>
                  </div>
                  <div>
                    <dt>Erfasst</dt>
                    <dd>{formatDate(deployment.created_at)}</dd>
                  </div>
                  <div>
                    <dt>Gestartet</dt>
                    <dd>{formatDate(deployment.started_at)}</dd>
                  </div>
                  <div>
                    <dt>Beendet</dt>
                    <dd>{formatDate(deployment.finished_at)}</dd>
                  </div>
                  <div>
                    <dt>Aktualisiert</dt>
                    <dd>{formatDate(deployment.updated_at)}</dd>
                  </div>
                </dl>

                <div className="automation-deployment-logs">
                  <span>
                    {logs.length === 1 ? "1 Logeintrag verborgen" : `${logs.length} Logeinträge verborgen`}
                  </span>
                  {logs.length ? (
                    <button onClick={() => toggleLogs(deployment.id)} type="button">
                      {logsVisible ? "Logvorschau ausblenden" : "Gekürzte Logs anzeigen"}
                    </button>
                  ) : null}
                  {logsVisible ? (
                    <div className="automation-deployment-log-preview">
                      {logs.slice(0, 3).map((log, index) => (
                        <code key={`${deployment.id}-log-${index}`}>{logPreview(log)}</code>
                      ))}
                      {logs.length > 3 ? (
                        <span>Weitere {logs.length - 3} Logzeile ausgeblendet.</span>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </article>
            );
            })}
          </div>
        ) : (
          <div className="automation-deployments-empty">
            <strong>Noch keine Delivery-Aktivität aufgezeichnet</strong>
            <p>
              Hier erscheinen ausschließlich Zustände, die das Control Center selbst
              gespeichert hat.
            </p>
          </div>
        )}
      </div>
    </details>
  );
}
