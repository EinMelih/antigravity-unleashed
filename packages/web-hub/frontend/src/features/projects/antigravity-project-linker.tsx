import { useQuery } from "@tanstack/react-query";
import { CircleAlert, Link2, LoaderCircle, Plus, Sparkles } from "lucide-react";
import { useState } from "react";

import type { AntiGravityProjectLinkResponse, HubProject } from "@/api/contracts";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  createAntiGravityProject,
  getAvailableAntiGravityProjects,
  linkAntiGravityProject,
} from "@/features/projects/onboarding-api";

interface AntiGravityProjectLinkerProps {
  onLinked: (result: AntiGravityProjectLinkResponse) => void | Promise<void>;
  project: HubProject;
}

export function AntiGravityProjectLinker({ onLinked, project }: AntiGravityProjectLinkerProps) {
  const [selectedId, setSelectedId] = useState("");
  const [busy, setBusy] = useState<"link" | "native" | "">("");
  const [error, setError] = useState("");
  const catalog = useQuery({
    queryKey: ["antigravity-projects"],
    queryFn: getAvailableAntiGravityProjects,
    retry: false,
  });

  async function finish(kind: "link" | "native") {
    setBusy(kind);
    setError("");
    try {
      const result = kind === "link"
        ? await linkAntiGravityProject(project.id, selectedId)
        : await createAntiGravityProject(project);
      await onLinked(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="onboarding-linker">
      {error ? <div className="onboarding-notice is-error" role="alert"><CircleAlert />{error}</div> : null}
      <div className="onboarding-link-grid">
        <article>
          <Sparkles />
          <h2>In Anti-Gravity erstellen</h2>
          <p>Der lokale Repository-Ordner wird automatisch verwendet. Du musst keinen Workspace-Pfad erneut eingeben.</p>
          <Button disabled={Boolean(busy)} onClick={() => void finish("native")}>
            {busy === "native" ? <LoaderCircle className="motion-safe:animate-spin" /> : <Plus />}
            Projekt anlegen
          </Button>
        </article>
        <article>
          <Link2 />
          <h2>Vorhandenes Projekt verknüpfen</h2>
          <p>Wähle ein Projekt direkt aus der laufenden Anti-Gravity-App.</p>
          {catalog.isPending ? <p className="onboarding-inline-status"><LoaderCircle className="motion-safe:animate-spin" />Projekte werden geladen …</p> : null}
          {catalog.isError ? (
            <div className="onboarding-inline-error">
              <p>Anti-Gravity ist gerade nicht erreichbar. Das Hub-Projekt bleibt sicher gespeichert.</p>
              <Button onClick={() => void catalog.refetch()} size="sm" variant="secondary">Erneut prüfen</Button>
            </div>
          ) : null}
          {catalog.data ? (
            <>
              <div className="hub-field">
                <span>Anti-Gravity-Projekt</span>
                <Select disabled={Boolean(busy)} onValueChange={setSelectedId} value={selectedId}>
                  <SelectTrigger aria-label="Anti-Gravity-Projekt auswählen"><SelectValue placeholder="Projekt auswählen" /></SelectTrigger>
                  <SelectContent>
                    {catalog.data.projects.map((candidate) => (
                      <SelectItem key={candidate.id} value={candidate.id}>{candidate.display_name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button disabled={!selectedId || Boolean(busy)} onClick={() => void finish("link")} variant="secondary">
                {busy === "link" ? <LoaderCircle className="motion-safe:animate-spin" /> : <Link2 />}
                Verknüpfen
              </Button>
            </>
          ) : null}
        </article>
      </div>
    </div>
  );
}
