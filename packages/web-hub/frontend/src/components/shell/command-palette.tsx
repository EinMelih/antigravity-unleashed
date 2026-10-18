import { useQuery } from "@tanstack/react-query";
import { Bot, CalendarClock, FolderGit2, Gauge, MessageSquare, Search, Settings2, Workflow } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { getProjects } from "@/features/studio/api";

const destinations = [
  { label: "Studio", detail: "Pausiert – Bugfixes nach Updates ausstehend", href: "#/studio", icon: Gauge, locked: true },
  { label: "Chats", detail: "Conversations und aktive Agenten", href: "#/chats", icon: MessageSquare, locked: false },
  { label: "Automation", detail: "Pausiert – Bugfixes nach Updates ausstehend", href: "#/automation", icon: Workflow, locked: true },
  { label: "Scheduled Tasks", detail: "Geplante Agentenaufgaben", href: "#/scheduled-tasks", icon: CalendarClock, locked: false },
  { label: "Einstellungen", detail: "GitHub und Custom API", href: "#/settings", icon: Settings2, locked: false },
  { label: "Systemstatus", detail: "Verbindungen und Diagnose", href: "#/system", icon: Bot, locked: false },
] as const;

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const projects = useQuery({ queryKey: ["projects"], queryFn: getProjects, enabled: open });

  useEffect(() => {
    const toggle = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === "k") {
        event.preventDefault();
        setOpen((current) => !current);
      }
    };
    document.addEventListener("keydown", toggle);
    return () => document.removeEventListener("keydown", toggle);
  }, []);

  const items = useMemo(() => {
    const projectItems = (projects.data?.projects ?? []).map((project) => ({
      label: project.github_repo || project.name,
      detail: "Projektübersicht",
      href: `#/projects/${project.id}`,
      icon: FolderGit2,
      locked: false,
    }));
    const needle = search.trim().toLocaleLowerCase("de");
    return [...destinations, ...projectItems].filter((item) => !needle || `${item.label} ${item.detail}`.toLocaleLowerCase("de").includes(needle));
  }, [projects.data, search]);

  function closeAfterNavigation() {
    setOpen(false);
    setSearch("");
  }

  return (
    <Dialog onOpenChange={(nextOpen) => { setOpen(nextOpen); if (!nextOpen) setSearch(""); }} open={open}>
      <DialogContent className="command-palette top-[min(14vh,8rem)] max-w-2xl translate-y-0 gap-0 p-0">
        <DialogTitle className="sr-only">Befehlspalette</DialogTitle>
        <DialogDescription className="sr-only">Ansichten und Projekte im Anti-Gravity Hub öffnen</DialogDescription>
        <header><Search className="size-4" /><Input aria-label="Hub durchsuchen" autoFocus className="border-0 bg-transparent shadow-none focus-visible:ring-0" onChange={(event) => setSearch(event.target.value)} placeholder="Ansicht oder Projekt öffnen …" value={search} /><kbd>Esc</kbd></header>
        <div className="command-palette-list">{items.map(({ detail, href, icon: Icon, label, locked }) => <a aria-disabled={locked ? "true" : undefined} className={locked ? "opacity-50 saturate-0" : undefined} href={href} key={href} onClick={closeAfterNavigation}><Icon className="size-4" /><span><strong>{label}</strong><small>{detail}</small></span><kbd>↵</kbd></a>)}{!items.length ? <p>Keine passende Ansicht oder kein passendes Projekt.</p> : null}</div>
        <footer><span><kbd>Strg</kbd> + <kbd>K</kbd> öffnet diese Palette überall.</span><a href="#/projects/new" onClick={closeAfterNavigation}>Projekt hinzufügen</a></footer>
      </DialogContent>
    </Dialog>
  );
}
