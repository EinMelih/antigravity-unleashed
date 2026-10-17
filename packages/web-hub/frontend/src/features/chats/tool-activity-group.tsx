import { animate } from "animejs";
import {
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  FilePenLine,
  Files,
  ListChecks,
  LoaderCircle,
  Monitor,
  Terminal,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { ChatHistoryEntry } from "@/api/contracts";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  buildToolSections,
  type ToolActivity,
  type ToolActivityKind,
  type ToolActivitySection,
} from "@/features/chats/model";
import { cn } from "@/lib/utils";

const kindMeta: Record<ToolActivityKind, {
  Icon: typeof Terminal;
  itemVerb: string;
  label: (count: number) => string;
}> = {
  browser: { Icon: Monitor, itemVerb: "Opened", label: (count) => `Used browser · ${count} ${count === 1 ? "action" : "actions"}` },
  commands: { Icon: Terminal, itemVerb: "Run", label: (count) => `Ran ${count} ${count === 1 ? "command" : "commands"}` },
  edits: { Icon: FilePenLine, itemVerb: "Edited", label: (count) => `Edited ${count} ${count === 1 ? "file" : "files"}` },
  exploration: { Icon: Files, itemVerb: "Checked", label: (count) => `Explored ${count} ${count === 1 ? "item" : "items"}` },
  other: { Icon: CheckCircle2, itemVerb: "Used", label: (count) => `Completed ${count} ${count === 1 ? "action" : "actions"}` },
  tasks: { Icon: ListChecks, itemVerb: "Checked", label: (count) => `Explored ${count} ${count === 1 ? "task" : "tasks"}` },
};

function ToolActivityRow({ activity, kind }: { activity: ToolActivity; kind: ToolActivityKind }) {
  const [open, setOpen] = useState(false);
  const StatusIcon = activity.running ? LoaderCircle : activity.failed ? CircleAlert : CheckCircle2;
  const row = (
    <div className="tool-timeline-row-content">
      <span className="tool-timeline-verb">{kindMeta[kind].itemVerb}</span>
      <span className={cn("tool-timeline-label", kind === "commands" && "font-mono")}>{activity.label}</span>
      <StatusIcon
        aria-label={activity.running ? "Läuft" : activity.failed ? "Fehlgeschlagen" : "Abgeschlossen"}
        className={cn(
          "tool-timeline-status",
          activity.running && "motion-safe:animate-spin",
          activity.failed && "is-failed",
        )}
      />
      {activity.detail ? <ChevronRight className={cn("tool-timeline-chevron", open && "rotate-90")} /> : null}
    </div>
  );

  if (!activity.detail) return <div className="tool-timeline-row">{row}</div>;
  return (
    <Collapsible onOpenChange={setOpen} open={open}>
      <CollapsibleTrigger className="tool-timeline-row">{row}</CollapsibleTrigger>
      <CollapsibleContent className="tool-timeline-output">
        <pre>{activity.detail}</pre>
      </CollapsibleContent>
    </Collapsible>
  );
}

function ToolSection({ section }: { section: ToolActivitySection }) {
  const running = section.activities.some((activity) => activity.running);
  const [requestedOpen, setRequestedOpen] = useState(running);
  const open = running || requestedOpen;
  const { Icon, label } = kindMeta[section.kind];

  return (
    <Collapsible
      className="tool-timeline-section"
      onOpenChange={setRequestedOpen}
      open={open}
    >
      <CollapsibleTrigger className="tool-timeline-section-trigger">
        <Icon className="size-3.5 shrink-0" />
        <span>{label(section.activities.length)}</span>
        {running ? <LoaderCircle className="ml-0.5 size-3.5 motion-safe:animate-spin" /> : null}
        <ChevronRight className={cn("tool-timeline-chevron ml-0.5", open && "rotate-90")} />
      </CollapsibleTrigger>
      <CollapsibleContent className="tool-timeline-items">
        {section.activities.map((activity) => (
          <ToolActivityRow activity={activity} key={activity.key} kind={section.kind} />
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}

export function ToolActivityGroup({ entries }: { entries: ChatHistoryEntry[] }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const sections = buildToolSections(entries);

  useEffect(() => {
    const reducedMotion = typeof window.matchMedia !== "function"
      || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reducedMotion || !rootRef.current) return;
    const elements = Array.from(rootRef.current.querySelectorAll<HTMLElement>(".tool-timeline-section"));
    const animations = elements.map((element, index) => animate(element, {
      delay: index * 24,
      duration: 180,
      ease: "out(3)",
      opacity: { from: 0 },
      y: { from: 3 },
    }));
    return () => animations.forEach((animation) => animation.cancel());
  }, [entries.length]);

  if (!sections.length) return null;
  return (
    <div className="tool-timeline" ref={rootRef}>
      {sections.map((section) => <ToolSection key={section.key} section={section} />)}
    </div>
  );
}
