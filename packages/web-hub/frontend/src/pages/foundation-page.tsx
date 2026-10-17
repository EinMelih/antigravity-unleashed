import { ArrowUpRight, CheckCircle2, Layers3, ShieldCheck } from "lucide-react";

import {
  type NextActionItem,
  NextActions,
} from "@/components/next-actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useHubHealth } from "@/hooks/use-hub-health";

export function FoundationPage() {
  const health = useHubHealth();
  const connectionStatus: NextActionItem["status"] = health.isSuccess
    ? "complete"
    : "current";

  const nextActions: NextActionItem[] = [
    {
      title: "React-Grundlage isolieren",
      description:
        "Die neue Anwendung läuft parallel und verändert die bestehende Oberfläche nicht.",
      status: "complete",
    },
    {
      title: "Python-Verbindung prüfen",
      description: health.isSuccess
        ? "Der gemeinsame Health-Vertrag ist erreichbar und typisiert."
        : "Starte den lokalen Hub, damit React den vorhandenen Health-Vertrag erreicht.",
      status: connectionStatus,
    },
    {
      title: "Studio zur Migration freigeben",
      description:
        "Nach der gemeinsamen Prüfung beginnt Phase 2 mit echten Studio-Daten.",
      status: "pending",
    },
  ];

  return (
    <div className="space-y-10">
      <section className="flex flex-col gap-5 border-b border-border pb-8 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl">
          <Badge variant="accent">Phase 1 · React-Grundlage</Badge>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight sm:text-4xl">
            Ein ruhiges Fundament für den neuen Hub
          </h1>
          <p className="mt-3 max-w-2xl text-base leading-7 text-muted-foreground">
            React, TypeScript und das Designsystem sind bewusst vom Legacy-Hub
            getrennt. Daten werden noch nicht vorgetäuscht oder doppelt
            verwaltet.
          </p>
        </div>
        <Button asChild variant="secondary">
          <a href="/dashboard/legacy">
            Legacy-Hub öffnen
            <ArrowUpRight className="size-4" />
          </a>
        </Button>
      </section>

      <NextActions items={nextActions} />

      <section aria-labelledby="foundation-title">
        <div className="mb-4">
          <p className="eyebrow">Architektur</p>
          <h2 id="foundation-title" className="mt-1 text-xl font-semibold">
            Was jetzt bereits getrennt ist
          </h2>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          <article className="foundation-card">
            <Layers3 className="size-5 text-primary" />
            <h3>Komponenten</h3>
            <p>Shell, Navigation und Datenzustände besitzen klare Grenzen.</p>
          </article>
          <article className="foundation-card">
            <ShieldCheck className="size-5 text-success" />
            <h3>Typisierte Verträge</h3>
            <p>Der erste Python-Vertrag wird zentral und ohne `any` verwendet.</p>
          </article>
          <article className="foundation-card">
            <CheckCircle2 className="size-5 text-success" />
            <h3>Rückrollbar</h3>
            <p>Der bestehende Hub bleibt bis zur Funktionsparität unverändert.</p>
          </article>
        </div>
      </section>
    </div>
  );
}
