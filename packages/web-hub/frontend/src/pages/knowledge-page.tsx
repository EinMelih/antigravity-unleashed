import { useQuery } from "@tanstack/react-query";
import { Lightbulb, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getKnowledgeChains } from "@/features/knowledge/api";
import { KnowledgeChainList } from "@/features/knowledge/knowledge-chain-list";
import { getLessons } from "@/features/more/api";
import { getProjects } from "@/features/studio/api";

export function KnowledgePage() {
  const [chainSearch, setChainSearch] = useState("");
  const [lessonSearch, setLessonSearch] = useState("");
  const [projectId, setProjectId] = useState<number | null>(null);
  const knowledge = useQuery({
    queryKey: ["control-center", "knowledge-chains", projectId ?? "all"],
    queryFn: () => getKnowledgeChains(projectId ?? undefined),
    staleTime: 30_000,
  });
  const lessons = useQuery({ queryKey: ["lessons"], queryFn: getLessons });
  const projects = useQuery({ queryKey: ["projects"], queryFn: getProjects });

  const projectOptions = useMemo(() => {
    const available = new Map<number, string>();
    for (const project of projects.data?.projects ?? []) {
      available.set(project.id, project.github_repo || project.name);
    }
    for (const chain of knowledge.data?.chains ?? []) {
      if (!available.has(chain.project.id)) available.set(chain.project.id, chain.project.name);
    }
    return [...available.entries()].sort((left, right) => left[1].localeCompare(right[1], "de"));
  }, [knowledge.data, projects.data]);

  const names = useMemo(() => new Map(projectOptions), [projectOptions]);
  const visibleLessons = useMemo(() => {
    const needle = lessonSearch.trim().toLocaleLowerCase("de");
    return (lessons.data?.lessons ?? []).filter((lesson) => {
      if (projectId !== null && lesson.project_id !== projectId) return false;
      const projectName = names.get(lesson.project_id ?? -1) ?? "";
      return !needle || `${lesson.technique} ${lesson.solution} ${projectName}`.toLocaleLowerCase("de").includes(needle);
    });
  }, [lessonSearch, lessons.data, names, projectId]);

  return (
    <section className="more-detail-page">
      <header className="more-page-header">
        <div><p className="eyebrow">Wissen</p><h1>Wissenskette &amp; Erfahrungen</h1><p>Von der ursprünglichen Idee über Entscheidungen und PRs bis zu Prüfnachweisen und aufgezeichneten Auslieferungen.</p></div>
      </header>
      <div className="knowledge-controls">
        <label className="knowledge-project-filter">
          <span>Projekt</span>
          <select
            aria-label="Projekt für Wissen"
            onChange={(event) => setProjectId(event.target.value ? Number(event.target.value) : null)}
            value={projectId ?? ""}
          >
            <option value="">Alle Projekte</option>
            {projectOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
      </div>
      <Tabs className="knowledge-tabs" defaultValue="chain">
        <TabsList aria-label="Wissensansicht" className="knowledge-tabs-list">
          <TabsTrigger value="chain">Wissenskette</TabsTrigger>
          <TabsTrigger value="lessons">Erfahrungen</TabsTrigger>
        </TabsList>

        <TabsContent className="knowledge-tab-content" value="chain">
          <div className="knowledge-controls">
            <label className="compact-search">
              <Search aria-hidden="true" className="size-4" />
              <span className="sr-only">Wissensketten durchsuchen</span>
              <Input className="h-auto border-0 bg-transparent px-0 shadow-none focus-visible:ring-0" onChange={(event) => setChainSearch(event.target.value)} placeholder="Idee, Artefakt, Campaign oder PR suchen" type="search" value={chainSearch} />
            </label>
          </div>
          {knowledge.isPending ? <LoadingState description="Wissensketten werden geladen." /> : null}
          {knowledge.isError ? <ErrorState description={knowledge.error.message} onRetry={() => void knowledge.refetch()} title="Wissenskette nicht verfügbar" /> : null}
          {knowledge.data ? <KnowledgeChainList data={knowledge.data} search={chainSearch} /> : null}
        </TabsContent>

        <TabsContent className="knowledge-tab-content" value="lessons">
          <label className="compact-search">
            <Search aria-hidden="true" className="size-4" />
            <span className="sr-only">Lessons durchsuchen</span>
            <Input className="h-auto border-0 bg-transparent px-0 shadow-none focus-visible:ring-0" onChange={(event) => setLessonSearch(event.target.value)} placeholder="Technik, Lösung oder Projekt suchen" type="search" value={lessonSearch} />
          </label>
           {lessons.isPending ? <LoadingState description="Erfahrungen werden geladen." /> : null}
           {lessons.isError ? <ErrorState description={lessons.error.message} onRetry={() => void lessons.refetch()} title="Erfahrungen nicht verfügbar" /> : null}
          {!lessons.isPending && !lessons.isError && visibleLessons.length ? (
            <div className="lesson-grid">
              {visibleLessons.map((lesson) => (
                <article key={lesson.id}>
                  <header><Lightbulb className="size-4" /><span>{names.get(lesson.project_id ?? -1) ?? "Projektübergreifend"}</span><time>{new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(lesson.created_at))}</time></header>
                  <h2>{lesson.technique}</h2>
                  <p>{lesson.solution}</p>
                  {lesson.issue_id ? <small>Issue #{lesson.issue_id}</small> : null}
                </article>
              ))}
            </div>
          ) : null}
           {!lessons.isPending && !lessons.isError && !visibleLessons.length ? <EmptyState description={lessonSearch || projectId !== null ? "Passe Suche oder Projektfilter an." : "Abgeschlossene Arbeiten können hier künftig wiederverwendbares Wissen hinterlassen."} title={lessonSearch || projectId !== null ? "Keine passenden Erfahrungen" : "Noch keine Erfahrungen"} /> : null}
        </TabsContent>
      </Tabs>
    </section>
  );
}
