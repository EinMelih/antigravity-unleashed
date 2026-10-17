import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronRight,
  CircleAlert,
  FolderGit2,
  GitBranch,
  LoaderCircle,
  Plus,
  Search,
} from "lucide-react";
import { FormEvent, useMemo, useState } from "react";

import type { HubProject } from "@/api/contracts";
import { ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { AntiGravityProjectLinker } from "@/features/projects/antigravity-project-linker";
import {
  createHubProject,
  getGitHubRepositories,
  importGitHubProject,
} from "@/features/projects/onboarding-api";

type SourceMode = "import" | "create";

function messageFromError(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

export function ProjectOnboardingPage() {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<SourceMode>("import");
  const [search, setSearch] = useState("");
  const [selectedRepository, setSelectedRepository] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [name, setName] = useState("");
  const [testCommand, setTestCommand] = useState("python -m unittest");
  const [visibility, setVisibility] = useState<"private" | "public">("private");
  const [createdProject, setCreatedProject] = useState<HubProject>();
  const [busy, setBusy] = useState<"hub" | "">("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const repositories = useQuery({
    queryKey: ["github-repositories"],
    queryFn: getGitHubRepositories,
    enabled: !createdProject && mode === "import",
    staleTime: 30_000,
  });
  const selected = repositories.data?.repositories.find(
    (repository) => repository.full_name === selectedRepository,
  );
  const visibleRepositories = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("de");
    const items = repositories.data?.repositories ?? [];
    if (!query) return items;
    return items.filter((repository) =>
      [repository.name, repository.full_name, repository.description]
        .join(" ")
        .toLocaleLowerCase("de")
        .includes(query),
    );
  }, [repositories.data?.repositories, search]);

  function chooseMode(nextMode: SourceMode) {
    setMode(nextMode);
    setError("");
    setNotice("");
  }

  function chooseRepository(fullName: string) {
    const repository = repositories.data?.repositories.find((item) => item.full_name === fullName);
    setSelectedRepository(fullName);
    setLocalPath(repository?.suggested_local_path ?? "");
  }

  async function refreshProjects() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["projects"] }),
      queryClient.invalidateQueries({ queryKey: ["studio-projects"] }),
    ]);
  }

  async function submitHubProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("hub");
    setError("");
    setNotice("");
    try {
      const project = mode === "import"
        ? await importGitHubProject({ full_name: selectedRepository, path: localPath.trim() || undefined })
        : await createHubProject({
            name: name.trim(),
            path: localPath.trim() || undefined,
            test_command: testCommand.trim() || "python -m unittest",
            create_github: true,
            github_visibility: visibility,
          });
      setCreatedProject(project);
      setNotice("Repository und lokaler Projektordner sind bereit.");
      await refreshProjects();
    } catch (caught) {
      setError(messageFromError(caught));
    } finally {
      setBusy("");
    }
  }

  if (createdProject) {
    return (
      <div className="project-onboarding-page">
        <header className="onboarding-header">
          <div>
            <p className="eyebrow">Projekt einrichten</p>
            <h1>{createdProject.github_repo || createdProject.name}</h1>
            <p>Das Repository ist im Hub registriert. Jetzt folgt nur noch die optionale Anti-Gravity-Verknüpfung.</p>
          </div>
          <Badge variant={createdProject.antigravity_linked ? "healthy" : "attention"}>
            {createdProject.antigravity_linked ? "Bereit" : "1 Schritt offen"}
          </Badge>
        </header>

        <ol aria-label="Einrichtungsfortschritt" className="onboarding-steps">
          <li className="is-complete"><Check />Quelle</li>
          <li className="is-complete"><Check />Lokal bereit</li>
          <li className={createdProject.antigravity_linked ? "is-complete" : "is-current"}>
            {createdProject.antigravity_linked ? <Check /> : <span>3</span>}Anti-Gravity
          </li>
        </ol>

        <section className="onboarding-completion-card">
          <div className="onboarding-project-summary">
            <span><FolderGit2 /></span>
            <div>
              <strong>{createdProject.github_owner && createdProject.github_repo ? `${createdProject.github_owner}/${createdProject.github_repo}` : createdProject.name}</strong>
              <p>{createdProject.path}</p>
            </div>
          </div>

          {notice ? <div className="onboarding-notice is-success" role="status"><Check />{notice}</div> : null}
          {error ? <div className="onboarding-notice is-error" role="alert"><CircleAlert />{error}</div> : null}

          {!createdProject.antigravity_linked ? (
            <AntiGravityProjectLinker
              onLinked={async (result) => {
                setCreatedProject({
                  ...createdProject,
                  antigravity_linked: true,
                  antigravity_project_name: result.antigravity_project_name,
                });
                setNotice(`Mit Anti-Gravity-Projekt „${result.antigravity_project_name}“ verknüpft.`);
                await refreshProjects();
              }}
              project={createdProject}
            />
          ) : null}

          <footer className="onboarding-footer">
            {!createdProject.antigravity_linked ? <p>Du kannst diesen Schritt überspringen und später in der Projektübersicht nachholen.</p> : <p>Projekt, Repository und Anti-Gravity-Arbeitsbereich gehören jetzt zusammen.</p>}
            <Button asChild>
              <a href={`#/projects/${createdProject.id}`}>Projekt öffnen<ArrowRight /></a>
            </Button>
          </footer>
        </section>
      </div>
    );
  }

  return (
    <div className="project-onboarding-page">
      <header className="onboarding-header">
        <div>
          <a className="onboarding-back" href="#/studio"><ArrowLeft />Zurück zum Studio</a>
          <p className="eyebrow">Projekt einrichten</p>
          <h1>Woran möchtest du arbeiten?</h1>
          <p>Der Hub legt Repository, lokalen Ordner und Anti-Gravity-Verknüpfung in einer nachvollziehbaren Reihenfolge an.</p>
        </div>
      </header>

      <ol aria-label="Einrichtungsfortschritt" className="onboarding-steps">
        <li className="is-current"><span>1</span>Quelle</li>
        <li><span>2</span>Lokal</li>
        <li><span>3</span>Anti-Gravity</li>
      </ol>

      <div className="onboarding-mode-grid">
        <button aria-pressed={mode === "import"} onClick={() => chooseMode("import")} type="button">
          <GitBranch /><strong>Bestehendes Repository</strong><span>Ein eigenes GitHub-Repository auswählen und lokal klonen.</span>
        </button>
        <button aria-pressed={mode === "create"} onClick={() => chooseMode("create")} type="button">
          <Plus /><strong>Neues Projekt</strong><span>Repository und lokalen Projektordner gemeinsam neu anlegen.</span>
        </button>
      </div>

      <form className="onboarding-form" onSubmit={(event) => void submitHubProject(event)}>
        {mode === "import" ? (
          <>
            <div className="onboarding-section-heading"><div><h2>Repository auswählen</h2><p>Es werden nur Repositories deines verbundenen GitHub-Kontos angezeigt.</p></div></div>
            {repositories.isPending ? <LoadingState description="GitHub-Repositories werden geladen." /> : null}
            {repositories.isError ? <ErrorState description={repositories.error.message} onRetry={() => void repositories.refetch()} title="GitHub-Repositories nicht verfügbar" /> : null}
            {repositories.data ? (
              <>
                <label className="compact-search onboarding-repository-search"><Search /><span className="sr-only">Repositories durchsuchen</span><Input className="h-auto border-0 bg-transparent px-0 shadow-none focus-visible:ring-0" onChange={(event) => setSearch(event.target.value)} placeholder="Repository durchsuchen" type="search" value={search} /></label>
                <div className="onboarding-repository-list">
                  {visibleRepositories.map((repository) => (
                    <article className={selectedRepository === repository.full_name ? "is-selected" : ""} key={repository.id}>
                      <button disabled={repository.imported} onClick={() => chooseRepository(repository.full_name)} type="button">
                        <span className="repository-icon"><FolderGit2 /></span>
                        <span className="repository-copy"><strong>{repository.full_name}</strong><small>{repository.description || "Keine Beschreibung"}</small></span>
                        <Badge variant={repository.imported ? "healthy" : repository.private ? "neutral" : "attention"}>{repository.imported ? "Im Hub" : repository.private ? "Privat" : "Öffentlich"}</Badge>
                      </button>
                      {repository.imported && repository.project_id ? <a href={`#/projects/${repository.project_id}`}>Öffnen<ArrowRight /></a> : null}
                    </article>
                  ))}
                  {!visibleRepositories.length ? <p className="onboarding-empty-row">Kein passendes Repository gefunden.</p> : null}
                </div>
              </>
            ) : null}
          </>
        ) : (
          <>
            <div className="onboarding-section-heading"><div><h2>Neues Projekt</h2><p>Standardmäßig wird ein privates GitHub-Repository erstellt.</p></div></div>
            <div className="onboarding-create-grid">
              <label className="hub-field"><span>Projektname</span><Input autoFocus maxLength={100} onChange={(event) => setName(event.target.value)} placeholder="Zum Beispiel: Katzen-Finder" required value={name} /></label>
              <div className="hub-field"><span>Sichtbarkeit</span><Select onValueChange={(value) => setVisibility(value as "private" | "public")} value={visibility}><SelectTrigger aria-label="Sichtbarkeit"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="private">Privat</SelectItem><SelectItem value="public">Öffentlich</SelectItem></SelectContent></Select></div>
            </div>
          </>
        )}

        {(mode === "create" || selected) ? (
          <section className="onboarding-local-section">
            <div><h2>Lokaler Projektordner</h2><p>{mode === "import" ? "Vorgeschlagen aus deiner zentralen Hub-Konfiguration." : "Leer lassen, um den konfigurierten Projektstamm zu verwenden."}</p></div>
            <label className="hub-field"><span>Windows-Pfad {mode === "create" ? "(optional)" : ""}</span><Input onChange={(event) => setLocalPath(event.target.value)} placeholder="Wird automatisch festgelegt" value={localPath} /></label>
            {mode === "create" ? <Collapsible className="onboarding-advanced" onOpenChange={setAdvancedOpen} open={advancedOpen}><CollapsibleTrigger asChild><Button size="sm" type="button" variant="ghost"><ChevronRight className={advancedOpen ? "rotate-90 transition-transform" : "transition-transform"} />Erweiterte Einstellungen</Button></CollapsibleTrigger><CollapsibleContent><label className="hub-field"><span>Testbefehl</span><Input onChange={(event) => setTestCommand(event.target.value)} value={testCommand} /></label></CollapsibleContent></Collapsible> : null}
          </section>
        ) : null}

        {error ? <div className="onboarding-notice is-error" role="alert"><CircleAlert />{error}</div> : null}
        <footer className="onboarding-submit-row">
          <p>{mode === "import" ? "Beim Import wird das Repository in den gewählten Ordner geklont." : "Repository und lokaler Ordner werden atomar vorbereitet."}</p>
          <Button disabled={busy === "hub" || (mode === "import" ? !selectedRepository : !name.trim())} type="submit">
            {busy === "hub" ? <LoaderCircle className="motion-safe:animate-spin" /> : mode === "import" ? <GitBranch /> : <Plus />}
            {mode === "import" ? "Repository importieren" : "Projekt erstellen"}
          </Button>
        </footer>
      </form>
    </div>
  );
}
