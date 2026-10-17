import { Button } from "@/components/ui/button";

export type NextActionStatus = "complete" | "current" | "pending";

export interface NextActionItem {
  title: string;
  description: string;
  status: NextActionStatus;
  actionLabel?: string;
  href?: string;
}

interface NextActionsProps {
  items: NextActionItem[];
}

function ActionLink({
  item,
  primary = false,
}: {
  item: NextActionItem;
  primary?: boolean;
}) {
  if (!item.href || !item.actionLabel) return null;
  return (
    <Button
      asChild
      className={primary ? "mt-5 w-full sm:w-auto" : "shrink-0"}
      size="sm"
      variant={primary ? "default" : "secondary"}
    >
      <a href={item.href}>{item.actionLabel}</a>
    </Button>
  );
}

export function NextActions({ items }: NextActionsProps) {
  const openItems = items.filter((item) => item.status !== "complete");
  const currentIndex = openItems.findIndex((item) => item.status === "current");
  const primaryIndex = currentIndex >= 0 ? currentIndex : 0;
  const primary = openItems[primaryIndex];
  if (!primary) return null;

  const following = openItems.filter((_, index) => index !== primaryIndex);

  return (
    <section aria-labelledby="next-actions-title">
      <h2 id="next-actions-title" className="mb-4 text-xl font-semibold">
        Als Nächstes
      </h2>
      <div
        className={
          following.length > 0
            ? "grid gap-3 xl:grid-cols-[minmax(0,1.35fr)_minmax(20rem,1fr)]"
            : undefined
        }
      >
        <article
          aria-label={primary.title}
          className="rounded-xl border border-primary/30 bg-card p-5 shadow-panel"
        >
          <h3 className="text-lg font-semibold text-foreground">{primary.title}</h3>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            {primary.description}
          </p>
          <ActionLink item={primary} primary />
        </article>

        {following.length > 0 ? (
          <div className="min-w-0">
            <h3 id="following-actions-title" className="mb-2 text-sm font-semibold">
              Danach
            </h3>
            <ol
              aria-labelledby="following-actions-title"
              className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card"
            >
              {following.map((item) => (
                <li
                  className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
                  key={item.title}
                >
                  <div className="min-w-0">
                    <h4 className="text-sm font-medium text-foreground">{item.title}</h4>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
                      {item.description}
                    </p>
                  </div>
                  <ActionLink item={item} />
                </li>
              ))}
            </ol>
          </div>
        ) : null}
      </div>
    </section>
  );
}
