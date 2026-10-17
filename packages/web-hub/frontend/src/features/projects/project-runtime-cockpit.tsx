import { Camera, ChevronRight, Download, ExternalLink, LoaderCircle, Play, RefreshCw, Square, Terminal } from "lucide-react";
import { useState } from "react";

import type { ProjectRuntimeServiceStatus, ProjectRuntimeSnapshot, ProjectScreenshotResponse } from "@/api/contracts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

interface ProjectRuntimeCockpitProps {
  busyService: string;
  onCapture: () => Promise<ProjectScreenshotResponse>;
  onSetup: (service: "frontend" | "backend") => Promise<void>;
  onStart: (service: "frontend" | "backend") => Promise<void>;
  onStop: (service: "frontend" | "backend") => Promise<void>;
  runtime: ProjectRuntimeSnapshot;
}

function RuntimeServiceCard({ busy, onSetup, onStart, onStop, status }: {
  busy: boolean;
  onSetup: () => Promise<void>;
  onStart: () => Promise<void>;
  onStop: () => Promise<void>;
  status: ProjectRuntimeServiceStatus;
}) {
  const [logsOpen, setLogsOpen] = useState(false);
  const stateLabel = busy ? (status.setup?.required ? "Einrichtung läuft" : "Wird aktualisiert") : status.status === "running" ? "Läuft" : status.status === "starting" ? "Startet" : status.status === "external" ? "Extern aktiv" : "Gestoppt";
  const tone = status.status === "running" ? "healthy" : status.status === "starting" || status.status === "external" ? "attention" : "neutral";
  return (
    <article className="runtime-service-card" id={`runtime-${status.service}`}>
      <header><div><p className="eyebrow">{status.service}</p><h3>{status.config.name}</h3></div><Badge variant={tone}>{busy || status.status === "starting" ? <LoaderCircle className="mr-1 size-3 motion-safe:animate-spin" /> : null}{stateLabel}</Badge></header>
      <p className="runtime-service-reason">{status.config.reason}</p>
      {status.setup?.required ? <div className="runtime-setup-hint"><strong>Einrichtung erforderlich</strong><span>{status.setup.reason}</span><code>{status.setup.command}</code></div> : null}
      <dl><div><dt>Adresse</dt><dd><code>{status.url}</code></dd></div><div><dt>Arbeitsordner</dt><dd><code>{status.config.cwd}</code></dd></div><div><dt>Prozess</dt><dd>{status.managed ? `Vom Hub · PID ${status.pid}` : status.status === "external" ? "Externer Prozess" : "Nicht gestartet"}</dd></div></dl>
      <div className="runtime-service-actions">
        {status.active ? (
          <><Button asChild size="sm"><a href={status.url} rel="noreferrer" target="_blank">Öffnen <ExternalLink className="size-3.5" /></a></Button><Button disabled={busy || !status.managed} onClick={() => void onStop()} size="sm" variant="secondary"><Square className="size-3.5" /> Stoppen</Button></>
        ) : status.setup?.required ? (
          <Button disabled={busy} onClick={() => void onSetup()} size="sm">{busy ? <LoaderCircle className="size-3.5 motion-safe:animate-spin" /> : <Download className="size-3.5" />} {busy ? "Einrichtung läuft" : "Abhängigkeiten einrichten"}</Button>
        ) : (
          <Button disabled={busy || !status.config.enabled} onClick={() => void onStart()} size="sm"><Play className="size-3.5" /> {status.config.name} starten</Button>
        )}
      </div>
      {status.log ? <Collapsible className="runtime-log" onOpenChange={setLogsOpen} open={logsOpen}><CollapsibleTrigger><Terminal className="size-3.5" /> Letzte Logs <ChevronRight className={logsOpen ? "ml-auto size-3.5 rotate-90 transition-transform" : "ml-auto size-3.5 transition-transform"} /></CollapsibleTrigger><CollapsibleContent><pre>{status.log}</pre></CollapsibleContent></Collapsible> : null}
    </article>
  );
}

export function ProjectRuntimeCockpit({ busyService, onCapture, onSetup, onStart, onStop, runtime }: ProjectRuntimeCockpitProps) {
  const [previewKey, setPreviewKey] = useState(0);
  const [screenshot, setScreenshot] = useState<ProjectScreenshotResponse | null>(null);
  const [captureBusy, setCaptureBusy] = useState(false);
  const [captureError, setCaptureError] = useState("");
  const frontend = runtime.services.frontend;

  async function capture() {
    setCaptureBusy(true);
    setCaptureError("");
    try {
      setScreenshot(await onCapture());
    } catch (error) {
      setCaptureError(error instanceof Error ? error.message : String(error));
    } finally {
      setCaptureBusy(false);
    }
  }

  return (
    <section aria-labelledby="runtime-title" className="project-runtime-section">
      <div className="project-section-heading"><div><p className="eyebrow">Lokale Umgebung</p><h2 id="runtime-title">Frontend & Backend</h2></div><span>{runtime.configured ? "Konfiguriert" : "Automatisch erkannt"}</span></div>
      <div className="runtime-service-grid">
        <RuntimeServiceCard busy={busyService.includes("frontend")} onSetup={() => onSetup("frontend")} onStart={() => onStart("frontend")} onStop={() => onStop("frontend")} status={frontend} />
        <RuntimeServiceCard busy={busyService.includes("backend")} onSetup={() => onSetup("backend")} onStart={() => onStart("backend")} onStop={() => onStop("backend")} status={runtime.services.backend} />
      </div>
      <div className="runtime-preview">
        <header>
          <div><strong>Frontend-Vorschau</strong><p>{frontend.active ? frontend.url : "Starte das Frontend, um die Vorschau hier zu sehen."}</p></div>
          <div className="flex flex-wrap gap-2">
            <Button disabled={!frontend.active} onClick={() => setPreviewKey((value) => value + 1)} size="sm" variant="secondary"><RefreshCw className="size-3.5" /> Neu laden</Button>
            <Button disabled={!frontend.active || captureBusy} onClick={() => void capture()} size="sm" variant="secondary">{captureBusy ? <LoaderCircle className="size-3.5 motion-safe:animate-spin" /> : <Camera className="size-3.5" />} Screenshot</Button>
            {frontend.active ? <Button asChild size="sm"><a href={frontend.url} rel="noreferrer" target="_blank">Im Browser öffnen <ExternalLink className="size-3.5" /></a></Button> : null}
          </div>
        </header>
        {captureError ? <p className="composer-error" role="alert">{captureError}</p> : null}
        {frontend.active ? (
          <div className="runtime-preview-frame"><iframe key={`${frontend.url}-${previewKey}`} loading="lazy" sandbox="allow-forms allow-modals allow-popups allow-same-origin allow-scripts" src={frontend.url} title={`${frontend.config.name} Vorschau`} /></div>
        ) : <div className="runtime-preview-empty"><Play className="size-5" /> Frontend noch nicht gestartet</div>}
        {screenshot ? <figure className="runtime-screenshot"><img alt="Automatisch erfasste Projektvorschau" src={`${screenshot.url}?t=${screenshot.captured_at}`} /><figcaption>Screenshot vom {new Intl.DateTimeFormat("de-DE", { dateStyle: "short", timeStyle: "short" }).format(new Date(screenshot.captured_at * 1000))}</figcaption></figure> : null}
        <p className="runtime-preview-help">Falls ein Framework Einbettung blockiert, nutze „Im Browser öffnen“ oder den serverseitigen Screenshot.</p>
      </div>
    </section>
  );
}
