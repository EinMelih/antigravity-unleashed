import { FolderGit2, LoaderCircle, MessageSquare } from "lucide-react";
import { useState } from "react";

import type { HubProject, ModelCatalogItem } from "@/api/contracts";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { ComposerPayload } from "@/features/chats/chat-composer";
import { modelSelectionId } from "@/features/chats/model";
import { useNewChatModels } from "@/features/chats/use-chats-data";

interface NewChatDialogProps {
  onClose: () => void;
  onCreate: (input: ComposerPayload & { conversationType: "normal" | "project"; model?: ModelCatalogItem; projectId?: number }) => Promise<void>;
  open: boolean;
  projects: HubProject[];
}

export function NewChatDialog({ onClose, onCreate, open, projects }: NewChatDialogProps) {
  const modelCatalog = useNewChatModels(open);
  const models = modelCatalog.data?.models ?? [];
  const currentModel = modelCatalog.data?.current;
  const [type, setType] = useState<"normal" | "project">("normal");
  const [projectId, setProjectId] = useState<number | undefined>();
  const [message, setMessage] = useState("");
  const [selectedModelId, setSelectedModelId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const linkedProjects = projects.filter((project) => project.antigravity_linked);

  async function submit() {
    if (!message.trim()) return;
    if (type === "project" && !projectId) {
      setError("Wähle ein mit Anti-Gravity verknüpftes Projekt.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const model = models.find((item) => modelSelectionId(item) === selectedModelId)
        ?? models.find((item) => item.label === currentModel);
      await onCreate({ attachments: [], conversationType: type, model, message: message.trim(), projectId });
      setMessage("");
      onClose();
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : String(createError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !nextOpen && !busy && onClose()}>
      <DialogContent
        className="max-h-[90svh] overflow-y-auto sm:max-w-xl"
        onEscapeKeyDown={(event) => busy && event.preventDefault()}
        onPointerDownOutside={(event) => busy && event.preventDefault()}
      >
        <DialogHeader>
          <p className="eyebrow">Anti-Gravity</p>
          <DialogTitle>Neuer Chat</DialogTitle>
          <DialogDescription>
            Starte eine freie Conversation oder arbeite direkt in einem verknüpften Projekt.
          </DialogDescription>
        </DialogHeader>

        <ToggleGroup
          aria-label="Chattyp"
          className="grid grid-cols-1 gap-2 sm:grid-cols-2"
          onValueChange={(value) => value && setType(value as "normal" | "project")}
          type="single"
          value={type}
          variant="outline"
        >
          <ToggleGroupItem className="h-auto min-h-24 items-start justify-start gap-3 whitespace-normal p-4 text-left" value="normal">
            <MessageSquare className="mt-0.5 size-5 shrink-0" />
            <span><strong className="block text-sm">Conversation</strong><span className="mt-1 block text-xs text-muted-foreground">Ohne Projektkontext</span></span>
          </ToggleGroupItem>
          <ToggleGroupItem className="h-auto min-h-24 items-start justify-start gap-3 whitespace-normal p-4 text-left" value="project">
            <FolderGit2 className="mt-0.5 size-5 shrink-0" />
            <span><strong className="block text-sm">Projektchat</strong><span className="mt-1 block text-xs text-muted-foreground">Im verknüpften Workspace</span></span>
          </ToggleGroupItem>
        </ToggleGroup>

        {type === "project" ? (
          <div className="grid gap-2">
            <label className="text-sm font-medium" htmlFor="new-chat-project">Projekt</label>
            <Select onValueChange={(value) => setProjectId(Number(value) || undefined)} value={projectId ? String(projectId) : undefined}>
              <SelectTrigger id="new-chat-project"><SelectValue placeholder="Projekt auswählen" /></SelectTrigger>
              <SelectContent>
                {linkedProjects.map((project) => (
                  <SelectItem key={project.id} value={String(project.id)}>{project.github_repo || project.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {!linkedProjects.length ? <p className="text-xs text-amber-400">Es ist noch kein Projekt mit Anti-Gravity verknüpft.</p> : null}
          </div>
        ) : null}

        <div className="grid gap-2">
          <label className="text-sm font-medium" htmlFor="new-chat-model">Modell</label>
          <Select
            disabled={modelCatalog.isPending}
            onValueChange={setSelectedModelId}
            value={selectedModelId || (models.find((item) => item.label === currentModel) ? modelSelectionId(models.find((item) => item.label === currentModel)!) : undefined)}
          >
            <SelectTrigger id="new-chat-model"><SelectValue placeholder={modelCatalog.isPending ? "Modelle werden geladen …" : "Standardmodell verwenden"} /></SelectTrigger>
            <SelectContent>
              {models.map((model) => (
                <SelectItem key={modelSelectionId(model)} value={modelSelectionId(model)}>
                  {model.label}{model.badge ? ` · ${model.badge}` : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {modelCatalog.isError ? <p className="composer-error" role="alert">Die Modellliste konnte nicht geladen werden. Der Chat kann mit dem Standardmodell starten.</p> : null}
          <p className="text-xs text-muted-foreground">Codex und Custom API laufen lokal im Hub; Anti-Gravity-Modelle nutzen ein App-Fenster.</p>
        </div>

        <div className="grid gap-2">
          <label className="text-sm font-medium" htmlFor="new-chat-message">Erste Nachricht</label>
          <Textarea
            autoFocus
            id="new-chat-message"
            onChange={(event) => setMessage(event.target.value)}
            placeholder="Womit soll Anti-Gravity beginnen?"
            rows={6}
            value={message}
          />
        </div>

        {busy ? (
          <div className="dialog-progress rounded-md border border-border bg-muted/40 p-3" role="status"><LoaderCircle className="size-4 motion-safe:animate-spin" /><div><strong>Chat wird gestartet</strong><p>Projekt, Modell und erste Antwort werden geprüft.</p></div></div>
        ) : null}
        {error ? <p className="composer-error" role="alert">{error}</p> : null}

        <DialogFooter>
          <Button disabled={busy} onClick={onClose} variant="secondary">Abbrechen</Button>
          <Button disabled={busy || !message.trim() || (type === "project" && !projectId)} onClick={() => void submit()}>
            {busy ? <LoaderCircle className="size-4 motion-safe:animate-spin" /> : null} Chat starten
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
