import { Check, LoaderCircle, Pencil, PlugZap, Plus, Save, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import type { CustomModel, CustomModelInput } from "@/api/contracts";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

const emptyModel: CustomModelInput = {
  name: "",
  base_url: "",
  model_id: "",
  api_key: "",
  api_key_header: "Authorization",
  api_key_prefix: "Bearer",
  extra_headers: "{}",
  system_prompt: "",
  temperature: 0.7,
  verify_tls: true,
  timeout_seconds: 60,
};

function editInput(model: CustomModel): CustomModelInput {
  return { ...model, api_key: "", extra_headers: JSON.stringify(model.extra_headers, null, 2) };
}

export function CustomModelSettings({ models, onDelete, onSave, onTest }: {
  models: CustomModel[];
  onDelete: (id: number) => Promise<void>;
  onSave: (input: CustomModelInput) => Promise<void>;
  onTest: (id: number) => Promise<{ model_count?: number }>;
}) {
  const [draft, setDraft] = useState<CustomModelInput>();
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const update = <Key extends keyof CustomModelInput>(key: Key, value: CustomModelInput[Key]) => {
    setDraft((current) => current ? { ...current, [key]: value } : current);
  };

  async function perform(label: string, operation: () => Promise<void>) {
    setBusy(label);
    setError("");
    setMessage("");
    try {
      await operation();
    } catch (operationError) {
      setError(operationError instanceof Error ? operationError.message : String(operationError));
    } finally {
      setBusy("");
    }
  }

  async function saveDraft(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    await perform("save", async () => {
      await onSave(draft);
      setDraft(undefined);
      setMessage("Modell sicher gespeichert.");
    });
  }

  return (
    <section className="settings-section">
      <div className="settings-section-heading">
        <div><p className="eyebrow">Modelle</p><h2>Custom API</h2><p>OpenAI-kompatible Provider. Schlüssel bleiben verschlüsselt auf diesem Windows-PC.</p></div>
        <Button onClick={() => { setDraft({ ...emptyModel }); setMessage(""); setError(""); }} size="sm"><Plus className="size-4" /> Modell hinzufügen</Button>
      </div>
      <div className="custom-model-list">
        {models.map((model) => (
          <article key={model.id}>
            <div className="custom-model-icon"><PlugZap className="size-4" /></div>
            <div className="min-w-0"><strong>{model.name}</strong><p>{model.model_id} · {model.base_url}</p></div>
            <Badge variant={model.has_api_key ? "healthy" : "attention"}>{model.has_api_key ? "Key geschützt" : "Ohne Key"}</Badge>
            <div className="custom-model-actions">
              <Button aria-label={`${model.name} testen`} disabled={Boolean(busy)} onClick={() => void perform(`test-${model.id}`, async () => { const result = await onTest(model.id); setMessage(`Verbindung zu ${model.name} erfolgreich${Number.isInteger(result.model_count) ? ` · ${result.model_count} Modelle` : ""}.`); })} size="sm" variant="secondary">{busy === `test-${model.id}` ? <LoaderCircle className="size-4 motion-safe:animate-spin" /> : <Check className="size-4" />} Testen</Button>
              <Button aria-label={`${model.name} bearbeiten`} disabled={Boolean(busy)} onClick={() => { setDraft(editInput(model)); setError(""); setMessage(""); }} size="icon" variant="ghost"><Pencil className="size-4" /></Button>
              <AlertDialog>
                <AlertDialogTrigger asChild><Button aria-label={`${model.name} löschen`} disabled={Boolean(busy)} size="icon" variant="ghost"><Trash2 className="size-4" /></Button></AlertDialogTrigger>
                <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Custom Model löschen?</AlertDialogTitle><AlertDialogDescription>„{model.name}“ und seine lokale API-Konfiguration werden entfernt. Aktive Proxy-Chats können die Löschung blockieren.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Abbrechen</AlertDialogCancel><AlertDialogAction className="bg-destructive text-destructive-foreground hover:bg-destructive/90" onClick={() => void perform(`delete-${model.id}`, async () => { await onDelete(model.id); setMessage(`${model.name} wurde gelöscht.`); })}>Löschen</AlertDialogAction></AlertDialogFooter></AlertDialogContent>
              </AlertDialog>
            </div>
          </article>
        ))}
        {!models.length ? <p className="settings-empty">Noch kein eigener Provider. Anti-Gravity-Modelle bleiben unabhängig davon verfügbar.</p> : null}
      </div>
      {message ? <p className="settings-message" role="status">{message}</p> : null}
      {error ? <p className="composer-error" role="alert">{error}</p> : null}

      <Dialog onOpenChange={(open) => !open && !busy && setDraft(undefined)} open={Boolean(draft)}>
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
          <DialogHeader><DialogTitle>{draft?.id ? "Modell bearbeiten" : "Eigenes Modell hinzufügen"}</DialogTitle><DialogDescription>Die Base URL muss absolut sein; eingebettete Zugangsdaten werden abgelehnt.</DialogDescription></DialogHeader>
          {draft ? (
            <form className="custom-model-form border-0 p-0" onSubmit={(event) => void saveDraft(event)}>
              <div className="settings-form-grid">
                <label className="hub-field"><span>Anzeigename</span><Input autoFocus maxLength={80} onChange={(event) => update("name", event.target.value)} required value={draft.name} /></label>
                <label className="hub-field"><span>Modell-ID</span><Input maxLength={200} onChange={(event) => update("model_id", event.target.value)} required value={draft.model_id} /></label>
                <label className="hub-field settings-field-wide"><span>API Base URL</span><Input onChange={(event) => update("base_url", event.target.value)} placeholder="https://api.example.com/v1" required type="url" value={draft.base_url} /></label>
                <label className="hub-field"><span>API-Key {draft.id ? "(leer = beibehalten)" : ""}</span><Input autoComplete="new-password" onChange={(event) => update("api_key", event.target.value)} type="password" value={draft.api_key ?? ""} /></label>
                <label className="hub-field"><span>Header</span><Input onChange={(event) => update("api_key_header", event.target.value)} value={draft.api_key_header} /></label>
                <label className="hub-field"><span>Prefix</span><Input onChange={(event) => update("api_key_prefix", event.target.value)} value={draft.api_key_prefix} /></label>
                <label className="hub-field"><span>Timeout (Sekunden)</span><Input max={300} min={5} onChange={(event) => update("timeout_seconds", Number(event.target.value))} type="number" value={draft.timeout_seconds} /></label>
                <label className="hub-field"><span>Temperatur</span><Input max={2} min={0} onChange={(event) => update("temperature", Number(event.target.value))} step="0.1" type="number" value={draft.temperature} /></label>
                <label className="scheduled-check"><Checkbox checked={draft.verify_tls} onChange={(event) => update("verify_tls", event.target.checked)} /><span>TLS-Zertifikat prüfen</span></label>
                <label className="hub-field settings-field-wide"><span>Zusätzliche Header (JSON)</span><Textarea onChange={(event) => update("extra_headers", event.target.value)} rows={3} value={draft.extra_headers} /><small>Gespeicherte Werte erscheinen als null. null behält den Wert; entferne den Schlüssel zum Löschen.</small></label>
                <label className="hub-field settings-field-wide"><span>System-Prompt (optional)</span><Textarea onChange={(event) => update("system_prompt", event.target.value)} rows={4} value={draft.system_prompt} /></label>
              </div>
              <DialogFooter><Button onClick={() => setDraft(undefined)} type="button" variant="secondary">Abbrechen</Button><Button disabled={Boolean(busy)} type="submit">{busy === "save" ? <LoaderCircle className="size-4 motion-safe:animate-spin" /> : <Save className="size-4" />} Speichern</Button></DialogFooter>
            </form>
          ) : null}
        </DialogContent>
      </Dialog>
    </section>
  );
}
