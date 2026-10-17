import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowLeft, ArrowUpRight, Bot, ChevronRight, CircleAlert, Code2, GitPullRequest, Link2Off, ListChecks, MessageSquare, RefreshCw, Settings2, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import type { ProjectRuntimeProfile } from "@/api/contracts";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
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
import type { AutomationWorkItem } from "@/features/automation/model";
import { WorkItemDetail } from "@/features/automation/work-item-detail";
import { WorkItemList } from "@/features/automation/work-item-list";
import { AntiGravityProjectLinker } from "@/features/projects/antigravity-project-linker";
import { getAvailableAntiGravityProjects } from "@/features/projects/onboarding-api";
import {
  captureProjectScreenshot,
  openProjectIde,
  saveProjectRuntime,
  setupProjectRuntime,
  startProjectRuntime,
  stopProjectRuntime,
  unlinkAntiGravityProject,
} from "@/features/projects/api";
import {
  projectMetrics,
  projectAntiGravityLinkState,
  projectNextActions,
  projectWorkItems,
  tasksForProject,
} from "@/features/projects/model";
import { ProjectRuntimeCockpit } from "@/features/projects/project-runtime-cockpit";
import { ProjectStackPanel } from "@/features/projects/project-stack-panel";
import { RuntimeSettings } from "@/features/projects/runtime-settings";
import { useProjectData } from "@/features/projects/use-project-data";
import { friendlySchedule } from "@/features/scheduled-tasks/model";
import { ProjectRemovalDialog } from "@/features/studio/project-removal-dialog";

export function ProjectOverviewPage({ projectId }: { projectId: number }) {
  const queryClient = useQueryClient();
  const data = useProjectData(projectId);
  const antigravityCatalog = useQuery({
    queryKey: ["antigravity-projects"],
    queryFn: getAvailableAntiGravityProjects,
    retry: false,
  });
  const [busyService, setBusyService] = useState("");
  const [operationError, setOperationError] = useState("");
  const [selectedWorkItem, setSelectedWorkItem] = useState<AutomationWorkItem>();
  const [ideBusy, setIdeBusy] = useState(false);
  const [projectMutation, setProjectMutation] = useState<"unlink" | "remove" | "">("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const project = data.projects.data?.projects.find((item) => item.id === projectId);
  const workItems = useMemo(
    () => projectWorkItems(data.control.data, project),
    [data.control.data, project],
  );
  const linkState = project
    ? projectAntiGravityLinkState(
        project,
        antigravityCatalog.data?.projects,
        antigravityCatalog.isPending
          ? "pending"
          : antigravityCatalog.isError
            ? "error"
            : "ready",
      )
    : "unlinked";
  const actionProject = project
    ? {
        ...project,
        antigravity_linked: !["unlinked", "stale"].includes(linkState),
      }
    : undefined;
  const metrics = projectMetrics(data.control.data, data.workers.data);
  const actions = actionProject
    ? projectNextActions(actionProject, data.control.data, data.runtime.data)
    : [];
  const projectTasks = project ? tasksForProject(data.tasks.data?.tasks ?? [], project) : [];
  const conversations = data.conversations.data?.conversations ?? [];

  async function refresh() {
    await Promise.all(Object.values(data).map((query) => query.refetch()));
  }

  async function runtimeOperation(
    service: "frontend" | "backend",
    operation: () => Promise<unknown>,
    busyKey: string = service,
  ) {
    setBusyService(busyKey);
    setOperationError("");
    try {
      await operation();
      await queryClient.invalidateQueries({ queryKey: ["project-runtime", projectId] });
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyService("");
    }
  }

  async function saveRuntime(profile: ProjectRuntimeProfile) {
    await saveProjectRuntime(projectId, profile);
    await queryClient.invalidateQueries({ queryKey: ["project-runtime", projectId] });
  }

  async function launchIde() {
    setIdeBusy(true);
    setOperationError("");
    try {
      const result = await openProjectIde(projectId);
      window.open(result.url, "_blank", "noopener,noreferrer");
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : String(error));
    } finally {
      setIdeBusy(false);
    }
  }

  async function unlinkProject() {
    setProjectMutation("unlink");
    setOperationError("");
    try {
      await unlinkAntiGravityProject(projectId);
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : String(error));
    } finally {
      setProjectMutation("");
    }
  }

  if (data.projects.isPending) return <LoadingState description="Projektübersicht wird aufgebaut." />;
  if (data.projects.isError) return <ErrorState description={data.projects.error instanceof Error ? data.projects.error.message : String(data.projects.error)} onRetry={() => void refresh()} />;
  if (!project) return <ErrorState description={`Projekt ${projectId} ist nicht mehr im Hub registriert.`} title="Projekt nicht gefunden" />;

  const sourceErrors = [data.control, data.conversations, data.runtime, data.stack, data.tasks, data.workers, antigravityCatalog].filter((query) => query.isError);
  const latestActivity = data.control.data?.audit.slice(0, 8) ?? [];
  const linkPresentation = {
    linked: { label: "Verbunden", variant: "healthy" as const },
    stale: { label: "Neu verknüpfen", variant: "blocked" as const },
    unlinked: { label: "Verknüpfung offen", variant: "attention" as const },
    checking: { label: "Verbindung wird geprüft", variant: "neutral" as const },
    unavailable: { label: "Verbindung nicht prüfbar", variant: "attention" as const },
    pending_confirmation: { label: "Bestätigung beim ersten Chat", variant: "neutral" as const },
  }[linkState];

  return (
    <div className="project-page">
      <header className="project-page-header">
        <div className="min-w-0">
          <a className="project-back-link" href="#/studio"><ArrowLeft className="size-3.5" /> Studio</a>
          <div className="mt-3 flex flex-wrap items-center gap-2"><Badge variant={linkPresentation.variant}>{linkPresentation.label}</Badge><span className="text-xs text-muted-foreground">{project.git_branch || project.default_branch}</span></div>
          <h1 className="mt-2 truncate text-3xl font-semibold tracking-tight">{project.github_repo || project.name}</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {project.github_owner && project.github_repo
              ? `${project.github_owner}/${project.github_repo}`
              : "Lokales Projekt · Pfad geschützt"}
          </p>
        </div>
        <div className="project-header-actions">
          <Button aria-label="Projekt aktualisieren" onClick={() => void refresh()} size="icon" variant="secondary"><RefreshCw className="size-4" /></Button>
          <Button disabled={ideBusy} onClick={() => void launchIde()} variant="secondary">{ideBusy ? <RefreshCw className="size-4 motion-safe:animate-spin" /> : <Code2 className="size-4" />} Web-IDE</Button>
          {project.github_url ? <Button asChild><a href={project.github_url} rel="noreferrer" target="_blank">GitHub <ArrowUpRight className="size-3.5" /></a></Button> : null}
        </div>
      </header>

      {sourceErrors.length ? <div className="partial-error" role="status">{sourceErrors.length} ergänzende Datenquelle{sourceErrors.length === 1 ? "" : "n"} momentan nicht erreichbar. Verfügbare Projektbereiche bleiben nutzbar.</div> : null}
      {operationError ? <div className="partial-error" role="alert"><CircleAlert className="size-4 text-destructive" />{operationError}<Button className="ml-auto" onClick={() => setOperationError("")} size="sm" variant="ghost">Schließen</Button></div> : null}

      {["unlinked", "stale"].includes(linkState) ? (
        <section aria-labelledby="project-link-title" className="project-link-section">
          <div className="project-section-heading">
            <div><p className="eyebrow">Verknüpfung</p><h2 id="project-link-title">{linkState === "stale" ? "Verbindung reparieren" : "Mit Anti-Gravity verbinden"}</h2></div>
            <span>Für Projekt-Chats und Agentensteuerung</span>
          </div>
          {linkState === "stale" ? (
            <p className="partial-error" role="status">
              Das gespeicherte Anti-Gravity-Projekt ist in der laufenden App nicht mehr vorhanden.
              Lege es aus diesem Repository neu an oder wähle das richtige vorhandene Projekt.
            </p>
          ) : null}
          <AntiGravityProjectLinker
            onLinked={async () => {
              await Promise.all([
                queryClient.invalidateQueries({ queryKey: ["projects"] }),
                queryClient.invalidateQueries({ queryKey: ["antigravity-projects"] }),
              ]);
            }}
            project={project}
          />
        </section>
      ) : null}

      <section aria-labelledby="project-next-title">
        <div className="project-section-heading"><div><p className="eyebrow">Jetzt wichtig</p><h2 id="project-next-title">Nächste Schritte</h2></div></div>
        <div className="project-next-grid">
          {actions.map((action, index) => <article key={`${action.label}-${index}`}><span>{index + 1}</span><div><strong>{action.label}</strong><p>{action.description}</p></div><Button asChild size="sm" variant={index ? "secondary" : "default"}><a href={action.href}>Öffnen</a></Button></article>)}
        </div>
      </section>

      <section aria-label="Projektstatus" className="project-metrics">
        <div><GitPullRequest className="size-4" /><span><small>Offene PRs</small><strong>{metrics.openPullRequests}</strong></span></div>
        <div><ListChecks className="size-4" /><span><small>Tests offen</small><strong>{metrics.testsOpen}</strong></span></div>
        <div><Bot className="size-4" /><span><small>Aktive Agenten</small><strong>{metrics.activeAgents}</strong></span></div>
        <div><CircleAlert className="size-4" /><span><small>Blockaden</small><strong>{metrics.blockers}</strong></span></div>
      </section>

      {data.runtime.isPending ? <LoadingState description="Projekt-Runtime wird erkannt." /> : data.runtime.data ? (
        <ProjectRuntimeCockpit
          busyService={busyService}
          onCapture={() => captureProjectScreenshot(projectId)}
          onSetup={(service) => runtimeOperation(service, () => setupProjectRuntime(projectId, service), `setup-${service}`)}
          onStart={(service) => runtimeOperation(service, () => startProjectRuntime(projectId, service))}
          onStop={(service) => runtimeOperation(service, () => stopProjectRuntime(projectId, service))}
          runtime={data.runtime.data}
        />
      ) : data.runtime.isError ? <ErrorState description={data.runtime.error instanceof Error ? data.runtime.error.message : String(data.runtime.error)} onRetry={() => void data.runtime.refetch()} title="Projekt-Runtime nicht verfügbar" /> : null}

      <ProjectStackPanel
        data={data.stack.data}
        error={data.stack.isError ? "Die sicheren Stack-Metadaten konnten momentan nicht geladen werden." : undefined}
        loading={data.stack.isPending}
        onRetry={() => void data.stack.refetch()}
      />

      <section aria-labelledby="project-work-title">
        <div className="project-section-heading"><div><p className="eyebrow">Arbeit</p><h2 id="project-work-title">Pull Requests & Work Items</h2></div><a href="#/automation">Automation öffnen</a></div>
        {workItems.length ? <WorkItemList items={workItems} onSelect={setSelectedWorkItem} selectedId={selectedWorkItem?.id} /> : <EmptyState description="Für dieses Projekt gibt es aktuell keine geplanten oder laufenden PR-Slices." title="Keine Work Items" />}
      </section>

      <div className="project-secondary-grid">
        <section><div className="project-section-heading"><div><p className="eyebrow">Kommunikation</p><h2>Chats</h2></div><a href="#/chats">Alle Chats</a></div><div className="project-compact-list">{conversations.slice(0, 5).map((conversation) => <a href="#/chats" key={conversation.convo_id}><MessageSquare className="size-4" /><span><strong>{conversation.title}</strong><small>{conversation.archived ? "Archiviert" : conversation.status === "running" ? "Agent arbeitet" : "Bereit"}</small></span></a>)}{!conversations.length ? <p>Keine projektbezogenen Chats.</p> : null}</div></section>
        <section><div className="project-section-heading"><div><p className="eyebrow">Zeitpläne</p><h2>Scheduled Tasks</h2></div><a href="#/scheduled-tasks">Verwalten</a></div><div className="project-compact-list">{projectTasks.slice(0, 5).map((task) => <a href="#/scheduled-tasks" key={task.id}><Activity className="size-4" /><span><strong>{task.name}</strong><small>{friendlySchedule(task.schedule)} · {task.enabled ? "Aktiv" : "Pausiert"}</small></span></a>)}{!projectTasks.length ? <p>Keine Tasks für dieses Projekt.</p> : null}</div></section>
        <section><div className="project-section-heading"><div><p className="eyebrow">Verlauf</p><h2>Letzte Aktivität</h2></div></div><div className="project-activity-list">{latestActivity.map((event) => <article key={event.id}><span /><div><strong>{event.action}</strong><p>{event.reason || `${event.from_state} → ${event.to_state}`}</p><time>{event.created_at}</time></div></article>)}{!latestActivity.length ? <p>Keine Aktivität protokolliert.</p> : null}</div></section>
      </div>

      <Collapsible className="project-settings" onOpenChange={setSettingsOpen} open={settingsOpen}>
        <CollapsibleTrigger className="project-settings-trigger"><Settings2 className="size-4" /><span><strong>Projekt- und Runtime-Einstellungen</strong><small>Startbefehle, Verknüpfung und Hub-Registrierung</small></span><ChevronRight className={settingsOpen ? "ml-auto size-4 rotate-90 transition-transform" : "ml-auto size-4 transition-transform"} /></CollapsibleTrigger>
        <CollapsibleContent>
        {data.runtime.data ? (
          <RuntimeSettings configured={data.runtime.data.configured} key={`${projectId}-${data.runtime.data.profile.updated_at ?? data.runtime.data.profile.detected_at ?? 0}`} onSave={saveRuntime} profile={data.runtime.data.profile} />
        ) : null}
        <div className="project-danger-zone">
          <div>
            <strong>Projektverwaltung</strong>
            <p>Diese Aktionen löschen weder das GitHub-Repository noch Dateien im lokalen Projektordner.</p>
          </div>
          <div className="project-danger-actions">
            {project.antigravity_linked ? (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button disabled={Boolean(projectMutation)} variant="secondary"><Link2Off className="size-4" />Verknüpfung lösen</Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Anti-Gravity-Verknüpfung lösen?</AlertDialogTitle>
                    <AlertDialogDescription>Projekt-Chats und Automationen verlieren ihre Zuordnung. Das Projekt kann anschließend erneut verknüpft werden.</AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter><AlertDialogCancel>Abbrechen</AlertDialogCancel><AlertDialogAction onClick={() => void unlinkProject()}>Verknüpfung lösen</AlertDialogAction></AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            ) : null}
            <ProjectRemovalDialog
              onRemoved={async () => {
                await queryClient.invalidateQueries({ queryKey: ["projects"] });
                window.location.hash = "#/studio";
              }}
              project={project}
              trigger={<Button disabled={Boolean(projectMutation)} variant="destructive"><Trash2 className="size-4" />Aus Hub entfernen</Button>}
            />
          </div>
        </div>
        </CollapsibleContent>
      </Collapsible>

      {data.control.data ? (
        <WorkItemDetail
          item={selectedWorkItem}
          onChanged={async () => {
            await data.control.refetch();
          }}
          onOpenChange={(open) => !open && setSelectedWorkItem(undefined)}
          open={Boolean(selectedWorkItem)}
          policy={data.control.data.policy}
        />
      ) : null}
    </div>
  );
}
