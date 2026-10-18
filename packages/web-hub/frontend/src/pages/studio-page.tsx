import { AlertTriangle, Lock, Plus, RefreshCw } from "lucide-react";

import { ApiError } from "@/api/errors";
import { NextActions } from "@/components/next-actions";
import { EmptyState, LoadingState, OfflineState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { ActiveWorkItems } from "@/features/studio/active-work-items";
import { activeTasks, buildNextActions } from "@/features/studio/model";
import { ProjectCard } from "@/features/studio/project-card";
import { useStudioData } from "@/features/studio/use-studio-data";
import { useHubLanguage } from "@/lib/i18n";

function isOfflineError(error: unknown) {
  return error instanceof ApiError && error.offline;
}

function StudioLockedNotice() {
  const [lang] = useHubLanguage();
  return (
    <section
      aria-label={lang === "en" ? "Section temporarily locked" : "Bereich vorübergehend gesperrt"}
      className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-dashed border-border bg-muted/40 p-5 text-sm shadow-panel"
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg border border-border bg-muted text-muted-foreground">
          <Lock aria-hidden="true" className="size-4" />
        </span>
        <div>
          <div className="flex items-center gap-2">
            <strong className="font-semibold text-foreground">
              {lang === "en"
                ? "Studio temporarily locked (Bugfixes pending)"
                : "Studio vorübergehend gesperrt (Bugfixes ausstehend)"}
            </strong>
            <span className="rounded bg-muted px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {lang === "en" ? "Paused" : "Pausiert"}
            </span>
          </div>
          <p className="mt-1 max-w-2xl text-muted-foreground">
            {lang === "en"
              ? "This view is currently affected by recent updates and is paused because it is not actively used right now."
              : "Dieser Bereich ist durch neue Updates aktuell noch fehlerhaft und vorübergehend ausgegraut, da er momentan nicht aktiv genutzt wird."}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button asChild size="sm" variant="secondary">
          <a href="#/chats">{lang === "en" ? "Open Chats" : "Zu den Chats"}</a>
        </Button>
        <Button asChild size="sm">
          <a href="#/api-logs">{lang === "en" ? "Open API-Logs" : "API-Logs öffnen"}</a>
        </Button>
      </div>
    </section>
  );
}

export function StudioPage() {
  const studio = useStudioData();
  const queries = Object.values(studio);
  const initialLoading = queries.every((query) => query.isPending);
  const errors = queries.filter((query) => query.isError);
  const allUnavailable = errors.length === queries.length;
  const offline = allUnavailable && errors.every((query) => isOfflineError(query.error));
  const projects = studio.projects.data?.projects ?? [];
  const tasks = activeTasks(studio.control.data?.tasks);
  const actions = buildNextActions({
    control: studio.control.data,
    conversations: studio.conversations.data,
    projects: studio.projects.data?.projects,
  });

  function refreshAll() {
    void Promise.all(queries.map((query) => query.refetch()));
  }

  if (initialLoading) {
    return (
      <div className="space-y-6">
        <StudioLockedNotice />
        <div aria-disabled="true" className="pointer-events-none select-none opacity-40 saturate-0">
          <LoadingState description="Studio-Daten werden aus den bestehenden Hub-APIs geladen." />
        </div>
      </div>
    );
  }

  if (offline) {
    return (
      <div className="space-y-6">
        <StudioLockedNotice />
        <div aria-disabled="true" className="pointer-events-none select-none opacity-40 saturate-0">
          <OfflineState onRetry={refreshAll} />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <StudioLockedNotice />
      <div
        aria-disabled="true"
        className="pointer-events-none select-none space-y-8 opacity-40 saturate-0"
      >
        <header className="studio-page-header">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">Studio</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              Projekte und laufende Arbeit auf einen Blick.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild size="sm"><a href="#/projects/new"><Plus className="size-4" />Projekt hinzufügen</a></Button>
            <Button onClick={refreshAll} size="sm" variant="secondary">
              <RefreshCw className="size-4" />
              Aktualisieren
            </Button>
          </div>
        </header>

        {errors.length > 0 ? (
          <div className="partial-error" role="status">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
            <p>
              {errors.length} von {queries.length} Datenquellen sind gerade nicht erreichbar.
              Vorhandene Bereiche bleiben nutzbar.
            </p>
            <Button className="ml-auto shrink-0" onClick={refreshAll} size="sm" variant="ghost">
              Erneut laden
            </Button>
          </div>
        ) : null}

        <section aria-labelledby="projects-title">
          <div className="mb-4 flex items-end justify-between gap-4">
            <div>
              <p className="eyebrow">Arbeitsbereiche</p>
              <h2 className="mt-1 text-xl font-semibold" id="projects-title">
                Projekte
              </h2>
            </div>
            <span className="text-xs text-muted-foreground">{projects.length} Projekte</span>
          </div>
          {projects.length === 0 && studio.projects.isSuccess ? (
            <EmptyState
              action={
                <Button asChild size="sm">
                  <a href="#/projects/new">Projekt hinzufügen</a>
                </Button>
              }
              description="Importiere ein bestehendes GitHub-Repository oder erstelle Projekt, Repository und lokalen Ordner gemeinsam."
              title="Noch keine Projekte"
            />
          ) : (
            <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-3">
              {projects.map((project) => (
                <ProjectCard key={project.id} onRemoved={async () => { await studio.projects.refetch(); await studio.control.refetch(); }} project={project} />
              ))}
            </div>
          )}
        </section>

        <ActiveWorkItems projects={projects} tasks={tasks} />

        <NextActions items={actions} />
      </div>
    </div>
  );
}
