import { Construction } from "lucide-react";

import { Badge } from "@/components/ui/badge";

interface PlaceholderPageProps {
  title: string;
  description: string;
  phase: string;
}

export function PlaceholderPage({
  description,
  phase,
  title,
}: PlaceholderPageProps) {
  return (
    <section className="max-w-3xl rounded-xl border border-border bg-card p-6 shadow-panel sm:p-8">
      <div className="flex size-10 items-center justify-center rounded-lg border border-border bg-muted text-muted-foreground">
        <Construction className="size-5" />
      </div>
      <Badge className="mt-5" variant="neutral">
        {phase}
      </Badge>
      <h1 className="mt-4 text-2xl font-semibold">{title}</h1>
      <p className="mt-3 max-w-2xl leading-7 text-muted-foreground">
        {description}
      </p>
      <p className="mt-5 text-sm text-muted-foreground">
        Bis dahin bleibt diese Funktion vollständig im Legacy-Hub verfügbar.
      </p>
    </section>
  );
}
