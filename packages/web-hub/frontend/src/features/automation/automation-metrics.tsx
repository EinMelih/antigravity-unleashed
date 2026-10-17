import { Activity, ChevronDown } from "lucide-react";

import type { ControlFlowMetric } from "@/api/contracts";


interface AutomationMetricsProps {
  metrics: ControlFlowMetric[];
}

const numberFormatter = new Intl.NumberFormat("de-DE", {
  maximumFractionDigits: 1,
});

const outcomeLabels: Record<string, string> = {
  completed: "abgeschlossen",
  failed: "fehlgeschlagen",
  cancelled: "abgebrochen",
  open: "offen",
  active: "aktiv",
  other: "sonstige",
};

function formatBreakdown(metric: ControlFlowMetric) {
  const entries = Object.entries(metric.breakdown)
    .filter(([key, value]) => Boolean(outcomeLabels[key]) && value > 0)
    .map(([key, value]) => `${numberFormatter.format(value)} ${outcomeLabels[key]}`);
  return entries.join(" · ");
}

function formatValue(metric: ControlFlowMetric) {
  if (metric.value === null) return "Keine Stichprobe";
  const value = numberFormatter.format(metric.value);
  return metric.unit === "percent" ? `${value} %` : `Anzahl ${value}`;
}

export function AutomationMetrics({ metrics }: AutomationMetricsProps) {
  const hasSamples = metrics.some(
    (metric) => metric.value !== null && metric.sample_size > 0,
  );

  return (
    <details className="automation-metrics">
      <summary className="automation-metrics-summary">
        <Activity aria-hidden="true" className="size-4" />
        <span>
          <span className="automation-metrics-title">Ablaufqualität</span>
          <span className="automation-metrics-subtitle">
            {hasSamples ? "Aus dem gespeicherten Projektverlauf" : "Noch keine Datenbasis"}
          </span>
        </span>
        <ChevronDown aria-hidden="true" className="automation-metrics-chevron size-4" />
      </summary>

      <div className="automation-metrics-content">
        {hasSamples ? (
          <>
            <p className="automation-metrics-intro">
              Nur aus gespeicherten Planungs-, Arbeits- und Auditdaten berechnet. Die
              Stichprobe zeigt jeweils die zugrunde liegende Menge.
            </p>
            <div className="automation-metrics-grid">
              {metrics.map((metric) => {
                const breakdown = formatBreakdown(metric);
                return (
                  <article className="automation-metric" key={metric.key}>
                    <span className="automation-metric-label">{metric.label}</span>
                    <strong>{formatValue(metric)}</strong>
                    <span className="automation-metric-sample">
                      Stichprobe: {numberFormatter.format(metric.sample_size)}
                    </span>
                    {breakdown ? (
                      <span className="automation-metric-breakdown">{breakdown}</span>
                    ) : null}
                    <p>{metric.description}</p>
                  </article>
                );
              })}
            </div>
          </>
        ) : (
          <div className="automation-metrics-empty">
            <strong>Noch keine belastbare Stichprobe</strong>
            <p>
              Sobald Planungen, Kampagnen oder Tasks einen Verlauf haben, erscheinen hier
              abgeleitete Qualitätswerte.
            </p>
          </div>
        )}
      </div>
    </details>
  );
}
