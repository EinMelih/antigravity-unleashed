import { LoaderCircle, Save } from "lucide-react";
import { useState } from "react";

import type { ProjectRuntimeProfile, ProjectRuntimeServiceConfig } from "@/api/contracts";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

interface RuntimeSettingsProps {
  configured: boolean;
  onSave: (profile: ProjectRuntimeProfile) => Promise<void>;
  profile: ProjectRuntimeProfile;
}

function ServiceFields({
  config,
  onChange,
  service,
}: {
  config: ProjectRuntimeServiceConfig;
  onChange: (config: ProjectRuntimeServiceConfig) => void;
  service: "frontend" | "backend";
}) {
  const update = <Key extends keyof ProjectRuntimeServiceConfig>(key: Key, value: ProjectRuntimeServiceConfig[Key]) =>
    onChange({ ...config, [key]: value });
  return (
    <fieldset className="runtime-settings-service">
      <legend>{service === "frontend" ? "Frontend" : "Backend"}</legend>
      <p>{config.reason}</p>
      <label className="scheduled-check"><Checkbox checked={config.enabled} onChange={(event) => update("enabled", event.target.checked)} /><span>Runtime aktiviert</span></label>
      <label className="hub-field runtime-field-wide"><span>Startbefehl</span><Input onChange={(event) => update("command", event.target.value)} placeholder="npm run dev -- --host {host} --port {port}" value={config.command} /></label>
      <label className="hub-field"><span>Arbeitsordner im Projekt</span><Input onChange={(event) => update("cwd", event.target.value)} placeholder="." value={config.cwd} /></label>
      <div className="hub-field"><span>Host</span><Select onValueChange={(value) => update("host", value)} value={config.host}><SelectTrigger aria-label={`${service === "frontend" ? "Frontend" : "Backend"}-Host`}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="127.0.0.1">127.0.0.1</SelectItem><SelectItem value="localhost">localhost</SelectItem><SelectItem value="::1">::1 (IPv6)</SelectItem></SelectContent></Select></div>
      <label className="hub-field"><span>Port</span><Input min={1024} max={65535} onChange={(event) => update("port", Number(event.target.value))} type="number" value={config.port} /></label>
      <label className="hub-field"><span>Health-/Preview-Pfad</span><Input onChange={(event) => update("health_path", event.target.value)} placeholder="/" value={config.health_path} /></label>
    </fieldset>
  );
}

export function RuntimeSettings({ configured, onSave, profile }: RuntimeSettingsProps) {
  const [services, setServices] = useState(profile.services);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setBusy(true);
    setError("");
    try {
      await onSave({ ...profile, services });
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : String(saveError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="runtime-settings">
      <div className="runtime-settings-intro">
        <div><strong>{configured ? "Gespeicherte Runtime-Konfiguration" : "Automatisch erkannter Vorschlag"}</strong><p>Die Platzhalter <code>{"{host}"}</code> und <code>{"{port}"}</code> werden sicher ersetzt. Befehle laufen ohne Shell im Projektordner.</p></div>
        <Button disabled={busy} onClick={() => void save()} size="sm">{busy ? <LoaderCircle className="size-4 motion-safe:animate-spin" /> : <Save className="size-4" />} Konfiguration speichern</Button>
      </div>
      {error ? <p className="composer-error" role="alert">{error}</p> : null}
      <div className="runtime-settings-grid">
        <ServiceFields config={services.frontend} onChange={(frontend) => setServices((current) => ({ ...current, frontend }))} service="frontend" />
        <ServiceFields config={services.backend} onChange={(backend) => setServices((current) => ({ ...current, backend }))} service="backend" />
      </div>
    </div>
  );
}
