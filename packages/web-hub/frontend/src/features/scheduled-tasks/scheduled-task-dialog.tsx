import { LoaderCircle } from "lucide-react";
import { useState } from "react";

import type { AntiGravityProject, ScheduledTask, ScheduledTaskInput } from "@/api/contracts";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  buildSchedule,
  parseSchedule,
  slugifyTaskName,
  type ScheduleKind,
} from "@/features/scheduled-tasks/model";

interface ScheduledTaskDialogProps {
  onClose: () => void;
  onSave: (input: ScheduledTaskInput) => Promise<void>;
  projects: AntiGravityProject[];
  task?: ScheduledTask;
}

export function ScheduledTaskDialog({ onClose, onSave, projects, task }: ScheduledTaskDialogProps) {
  const initial = parseSchedule(task?.schedule ?? "0 9 * * *");
  const [allProjects, setAllProjects] = useState(task?.all_projects ?? false);
  const [busy, setBusy] = useState(false);
  const [cron, setCron] = useState(initial.cron);
  const [enabled, setEnabled] = useState(task?.enabled ?? false);
  const [error, setError] = useState("");
  const [kind, setKind] = useState<ScheduleKind>(initial.kind);
  const [name, setName] = useState(task?.name ?? "");
  const [projectId, setProjectId] = useState(task?.project_id ?? "");
  const [prompt, setPrompt] = useState(task?.prompt ?? "");
  const [time, setTime] = useState(initial.time);
  const [weekday, setWeekday] = useState(initial.weekday);
  const taskId = task?.id || slugifyTaskName(name);

  async function submit() {
    if (!name.trim() || !prompt.trim() || (!allProjects && !projectId)) return;
    setBusy(true);
    setError("");
    try {
      await onSave({
        all_projects: allProjects,
        enabled,
        name: name.trim(),
        project_id: allProjects ? "" : projectId,
        prompt: prompt.trim(),
        schedule: buildSchedule(kind, time, weekday, cron),
      });
      onClose();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : String(saveError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog onOpenChange={(open) => !open && !busy && onClose()} open>
      <DialogContent
        className="hub-dialog scheduled-dialog max-w-3xl gap-0 p-0"
        onEscapeKeyDown={(event) => busy && event.preventDefault()}
        onInteractOutside={(event) => busy && event.preventDefault()}
      >
        <DialogHeader className="border-b border-border p-5 pr-12">
          <p className="eyebrow">Automation</p>
          <DialogTitle>{task ? "Scheduled Task bearbeiten" : "Neuer Scheduled Task"}</DialogTitle>
          <DialogDescription>Name, Zeitplan, Projekt und Prompt vollständig im Hub steuern.</DialogDescription>
        </DialogHeader>
        <div className="scheduled-form-grid">
          <label className="hub-field scheduled-field-wide"><span>Name</span><Input autoFocus maxLength={160} onChange={(event) => setName(event.target.value)} placeholder="Zum Beispiel: Täglicher Projektcheck" value={name} /></label>
          <p className="scheduled-id-help scheduled-field-wide">{task ? `Stabile ID: ${task.id} · bleibt beim Umbenennen erhalten` : taskId ? `Automatische ID: ${taskId}` : "Die stabile ID wird aus dem Namen erzeugt."}</p>
          <div className="hub-field"><span>Häufigkeit</span><Select onValueChange={(value) => setKind(value as ScheduleKind)} value={kind}><SelectTrigger aria-label="Häufigkeit"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="daily">Täglich</SelectItem><SelectItem value="weekly">Wöchentlich</SelectItem><SelectItem value="custom">Benutzerdefiniert (Cron)</SelectItem></SelectContent></Select></div>
          {kind === "custom" ? (
            <label className="hub-field"><span>Cron-Ausdruck</span><Input onChange={(event) => setCron(event.target.value)} placeholder="0 9 * * *" value={cron} /></label>
          ) : (
            <label className="hub-field"><span>Uhrzeit</span><Input onChange={(event) => setTime(event.target.value)} type="time" value={time} /></label>
          )}
          {kind === "weekly" ? (
            <div className="hub-field"><span>Wochentag</span><Select onValueChange={setWeekday} value={weekday}><SelectTrigger aria-label="Wochentag"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="1">Montag</SelectItem><SelectItem value="2">Dienstag</SelectItem><SelectItem value="3">Mittwoch</SelectItem><SelectItem value="4">Donnerstag</SelectItem><SelectItem value="5">Freitag</SelectItem><SelectItem value="6">Samstag</SelectItem><SelectItem value="0">Sonntag</SelectItem></SelectContent></Select></div>
          ) : null}
          <div className="hub-field"><span>Projekt</span><Select disabled={allProjects} onValueChange={setProjectId} value={projectId || undefined}><SelectTrigger aria-label="Projekt"><SelectValue placeholder="Projekt auswählen" /></SelectTrigger><SelectContent>{projects.map((project) => <SelectItem key={project.id} value={project.id}>{project.display_name}</SelectItem>)}</SelectContent></Select></div>
          <label className="scheduled-check"><Checkbox checked={allProjects} onChange={(event) => setAllProjects(event.target.checked)} /><span>Für alle Projekte</span></label>
          <label className="scheduled-check"><Checkbox checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /><span>Nach dem Speichern aktiv</span></label>
          <label className="hub-field scheduled-field-wide"><span>Prompt</span><Textarea maxLength={100000} onChange={(event) => setPrompt(event.target.value)} placeholder="Was soll der Agent zum geplanten Zeitpunkt tun?" rows={7} value={prompt} /></label>
        </div>
        {error ? <p className="composer-error mx-5" role="alert">{error}</p> : null}
        <footer><Button disabled={busy} onClick={onClose} variant="secondary">Abbrechen</Button><Button disabled={busy || !name.trim() || !prompt.trim() || (!allProjects && !projectId)} onClick={() => void submit()}>{busy ? <LoaderCircle className="size-4 motion-safe:animate-spin" /> : null} Task speichern</Button></footer>
      </DialogContent>
    </Dialog>
  );
}
