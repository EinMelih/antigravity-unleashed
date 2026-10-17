import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface StatePanelProps {
  title: string;
  description: string;
  icon: ReactNode;
  action?: ReactNode;
  className?: string;
  role?: "status" | "alert";
}

export function StatePanel({
  action,
  className,
  description,
  icon,
  role = "status",
  title,
}: StatePanelProps) {
  return (
    <section
      className={cn(
        "flex min-h-48 flex-col items-start justify-center rounded-xl border border-border bg-card p-6 shadow-panel",
        className,
      )}
      role={role}
    >
      <div
        aria-hidden="true"
        className="mb-4 flex size-10 items-center justify-center rounded-lg border border-border bg-muted text-muted-foreground"
      >
        {icon}
      </div>
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
        {description}
      </p>
      {action ? <div className="mt-5">{action}</div> : null}
    </section>
  );
}
