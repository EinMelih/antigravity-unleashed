import { ImagePlus, LoaderCircle, Mic, Send, Square, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import type { ChatAttachment, ModelCatalogItem } from "@/api/contracts";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { appendImageFiles } from "@/features/chats/attachments";
import { modelSelectionId } from "@/features/chats/model";
import { useNativeDictation } from "@/features/chats/use-native-dictation";
import { cn } from "@/lib/utils";

export interface ComposerPayload {
  attachments: ChatAttachment[];
  message: string;
}

interface ChatComposerProps {
  activeModel: string;
  archived: boolean;
  busy: boolean;
  disabledReason?: string;
  initialDraft?: ComposerPayload | null;
  models: ModelCatalogItem[];
  modelError?: string;
  modelSwitching: boolean;
  onClearInitialDraft?: () => void;
  onModelChange: (model: string) => Promise<void>;
  onSend: (payload: ComposerPayload) => Promise<void>;
}

export function ChatComposer({
  activeModel,
  archived,
  busy,
  disabledReason,
  initialDraft,
  models,
  modelError,
  modelSwitching,
  onClearInitialDraft,
  onModelChange,
  onSend,
}: ChatComposerProps) {
  const [attachments, setAttachments] = useState<ChatAttachment[]>(() => initialDraft?.attachments ?? []);
  const [draft, setDraft] = useState(() => initialDraft?.message ?? "");
  const [error, setError] = useState("");
  const [previousInitialDraft, setPreviousInitialDraft] = useState(initialDraft);
  const fileRef = useRef<HTMLInputElement>(null);
  const locked = archived || busy || modelSwitching || Boolean(disabledReason);

  if (initialDraft !== previousInitialDraft) {
    setPreviousInitialDraft(initialDraft);
    if (initialDraft) {
      setDraft(initialDraft.message);
      setAttachments(initialDraft.attachments ?? []);
    }
  }

  useEffect(() => {
    if (initialDraft) {
      onClearInitialDraft?.();
    }
  }, [initialDraft, onClearInitialDraft]);
  const dictation = useNativeDictation({
    disabled: locked,
    onError: setError,
    onText: setDraft,
    text: draft,
  });
  const recording = dictation.phase === "recording";

  async function submit() {
    const message = draft.trim();
    if ((!message && !attachments.length) || locked) return;
    const payload = { message, attachments: [...attachments] };
    setDraft("");
    setAttachments([]);
    setError("");
    try {
      await onSend(payload);
    } catch (submitError) {
      setDraft(payload.message);
      setAttachments(payload.attachments);
      setError(submitError instanceof Error ? submitError.message : String(submitError));
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  }

  async function addFiles(files: FileList | File[] | null) {
    if (!files || !files.length) return;
    try {
      setAttachments(await appendImageFiles(attachments, Array.from(files)));
      setError("");
    } catch (fileError) {
      setError(fileError instanceof Error ? fileError.message : String(fileError));
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function onPaste(event: React.ClipboardEvent<HTMLTextAreaElement>) {
    if (locked) return;
    const clipboardData = event.clipboardData;
    if (!clipboardData) return;

    const files: File[] = [];
    if (clipboardData.items) {
      for (const item of Array.from(clipboardData.items)) {
        if (item.kind === "file" && item.type.startsWith("image/")) {
          const file = item.getAsFile();
          if (file) files.push(file);
        }
      }
    } else if (clipboardData.files) {
      for (const file of Array.from(clipboardData.files)) {
        if (file.type.startsWith("image/")) {
          files.push(file);
        }
      }
    }

    if (files.length > 0) {
      event.preventDefault();
      void addFiles(files);
    }
  }

  const effectiveModels = useMemo(() => {
    const list = (models || []).filter((m) => Boolean(m && m.label && m.label.trim()));
    if (activeModel && activeModel.trim() && !list.some((m) => modelSelectionId(m) === activeModel)) {
      list.unshift({ label: activeModel.replace(/^[^:]+:/, ""), selection_id: activeModel, source: "active" });
    }
    return list;
  }, [models, activeModel]);

  return (
    <div className="chat-composer-shell">
      {attachments.length ? (
        <div className="chat-attachment-preview">
          {attachments.map((attachment, index) => (
            <div className="chat-attachment-thumb" key={`${attachment.name}-${index}`}>
              <img alt={attachment.name || "Anhang"} src={attachment.data} />
              <Button
                aria-label={`${attachment.name || "Bild"} entfernen`}
                className="absolute -right-1 -top-1 size-5 rounded-full p-0"
                onClick={() => setAttachments((items) => items.filter((_, itemIndex) => itemIndex !== index))}
                size="icon"
                type="button"
                variant="destructive"
              >
                <X className="size-3" />
              </Button>
            </div>
          ))}
        </div>
      ) : null}

      {archived ? <p className="composer-lock">Dieser Chat ist archiviert. Stelle ihn zuerst wieder her.</p> : null}
      {disabledReason && !archived ? <p className="composer-lock">{disabledReason}</p> : null}
      {modelSwitching ? (
        <p className="composer-model-lock" role="status">
          <LoaderCircle className="size-4 motion-safe:animate-spin" /> Modell wird gewechselt …
        </p>
      ) : null}
      {modelError ? <p className="composer-error" role="alert">{modelError}</p> : null}
      {error ? <p className="composer-error" role="alert">{error}</p> : null}
      {dictation.phase !== "idle" ? (
        <div className="composer-dictation-status" data-phase={dictation.phase} role="status">
          <span className="composer-dictation-dot" aria-hidden="true" />
          <strong>
            {dictation.phase === "starting" ? "Diktatfenster wird gestartet …" : null}
            {dictation.phase === "recording" ? `${dictation.windowId} · Aufnahme läuft` : null}
            {dictation.phase === "stopping" ? "Aufnahme wird beendet …" : null}
          </strong>
          {dictation.phase === "recording" ? (
            <time>{Math.floor(dictation.elapsedSeconds / 60)}:{String(dictation.elapsedSeconds % 60).padStart(2, "0")}</time>
          ) : null}
        </div>
      ) : null}

      <TooltipProvider delayDuration={350}>
      <div className="chat-composer-row">
        <input
          accept="image/*"
          className="sr-only"
          disabled={locked}
          multiple
          onChange={(event) => void addFiles(event.target.files)}
          ref={fileRef}
          type="file"
        />
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              aria-label="Bilder anhängen"
              disabled={locked || attachments.length >= 5}
              onClick={() => fileRef.current?.click()}
              size="icon"
              type="button"
              variant="ghost"
            >
              <ImagePlus className="size-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Bilder anhängen</TooltipContent>
        </Tooltip>
        <Textarea
          aria-label="Nachricht an Anti-Gravity"
          className="min-h-10 max-h-40 flex-1 resize-none border-0 bg-transparent px-2 py-2.5 shadow-none focus-visible:ring-0"
          disabled={locked}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          placeholder="Nachricht schreiben …"
          rows={1}
          value={draft}
        />
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              aria-label={dictation.phase === "idle" ? "Spracheingabe starten" : "Aufnahme beenden"}
              className={cn(dictation.phase !== "idle" && "is-recording")}
              disabled={locked && dictation.phase === "idle" || dictation.phase === "starting" || dictation.phase === "stopping"}
              onClick={() => void dictation.toggle()}
              size="icon"
              type="button"
              variant="ghost"
            >
              {recording ? <Square className="size-3 fill-current" /> : dictation.phase === "idle" ? <Mic className="size-4" /> : <LoaderCircle className="size-4 motion-safe:animate-spin" />}
            </Button>
          </TooltipTrigger>
          <TooltipContent>{dictation.phase === "idle" ? "Spracheingabe starten" : "Aufnahme beenden"}</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              aria-label="Nachricht senden"
              disabled={locked || dictation.phase !== "idle" || (!draft.trim() && !attachments.length)}
              onClick={() => void submit()}
              size="icon"
              type="button"
            >
              {busy ? <LoaderCircle className="size-4 motion-safe:animate-spin" /> : <Send className="size-4" />}
            </Button>
          </TooltipTrigger>
          <TooltipContent>Nachricht senden</TooltipContent>
        </Tooltip>
      </div>
      </TooltipProvider>
      <div className="chat-composer-footer">
        <Select
          disabled={archived || busy || modelSwitching || !effectiveModels.length}
          onValueChange={(value) => void onModelChange(value)}
          value={activeModel && effectiveModels.some((m) => modelSelectionId(m) === activeModel) ? activeModel : undefined}
        >
          <SelectTrigger aria-label="Modell auswählen" className="h-8 w-auto max-w-[20rem] border-0 bg-transparent px-2 text-xs shadow-none">
            <SelectValue placeholder="Modell wird erkannt …" />
          </SelectTrigger>
          <SelectContent>
            {effectiveModels.map((model, idx) => (
              <SelectItem key={`${model.source}-${model.label}-${idx}`} value={modelSelectionId(model)}>
                {model.label}{model.badge ? ` · ${model.badge}` : ""}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span>Enter senden · Shift+Enter Zeilenumbruch · {attachments.length}/5 Bilder</span>
      </div>
    </div>
  );
}
