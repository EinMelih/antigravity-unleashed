import { BookOpen, CalendarClock, Lightbulb, Settings, ShieldCheck, Stethoscope } from "lucide-react";

import { routeHref, type HubRoute } from "@/lib/routing";

const destinations = [
  { icon: ShieldCheck, label: "API-Logs & Anti-Ban-Schilde", to: "/api-logs" },
  { icon: CalendarClock, label: "Scheduled Tasks", to: "/scheduled-tasks" },
  { icon: BookOpen, label: "Hilfe & Dokumentation", to: "/help" },
  { icon: Stethoscope, label: "Systemstatus & Diagnose", to: "/system" },
  { icon: Settings, label: "Einstellungen", to: "/settings" },
  { icon: Lightbulb, label: "Wissen & Lessons Learned", to: "/knowledge" },
] satisfies Array<{ icon: typeof CalendarClock; label: string; to: HubRoute }>;

export function MorePage() {
  return (
    <section>
      <p className="eyebrow">Weitere Bereiche</p>
      <h1 className="mt-2 text-3xl font-semibold">Mehr</h1>
      <p className="mt-3 max-w-2xl leading-7 text-muted-foreground">
        Seltenere Funktionen bleiben erreichbar, ohne die Hauptnavigation zu
        überladen.
      </p>
      <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {destinations.map(({ icon: Icon, label, to }) => (
          <a
            className="group flex min-h-28 items-start gap-4 rounded-xl border border-border bg-card p-5 shadow-panel transition-colors hover:border-primary/40 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
            href={routeHref(to)}
            key={to}
          >
            <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-border bg-muted text-muted-foreground group-hover:text-foreground">
              <Icon className="size-5" />
            </span>
            <span className="pt-2 text-sm font-semibold">{label}</span>
          </a>
        ))}
      </div>
    </section>
  );
}
