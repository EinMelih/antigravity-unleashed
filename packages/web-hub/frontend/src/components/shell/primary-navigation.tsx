import { ChevronDown, Menu, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { routeHref, type AppRoute, type HubRoute, useHubRoute } from "@/lib/routing";

const primaryItems: ReadonlyArray<{ label: string; to: HubRoute }> = [
  { label: "Studio", to: "/studio" },
  { label: "Chats", to: "/chats" },
  { label: "Automation", to: "/automation" },
];

const moreItems: ReadonlyArray<{ label: string; to: HubRoute }> = [
  { label: "Scheduled Tasks", to: "/scheduled-tasks" },
  { label: "Hilfe & Dokumentation", to: "/help" },
  { label: "Systemstatus & Diagnose", to: "/system" },
  { label: "Einstellungen", to: "/settings" },
  { label: "Wissen & Lessons Learned", to: "/knowledge" },
];

function NavigationLink({
  currentRoute,
  label,
  onNavigate,
  to,
}: {
  currentRoute: AppRoute;
  label: string;
  onNavigate: () => void;
  to: HubRoute;
}) {
  return (
    <a
      aria-current={currentRoute === to ? "page" : undefined}
      className={cn(
        "rounded-md px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none",
        currentRoute === to
          ? "bg-primary/15 text-primary-foreground"
          : "text-muted-foreground hover:bg-accent hover:text-foreground",
      )}
      href={routeHref(to)}
      onClick={onNavigate}
    >
      {label}
    </a>
  );
}

export function PrimaryNavigation() {
  const currentRoute = useHubRoute();
  const menuRef = useRef<HTMLDivElement>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);

  function closeNavigation() {
    setMobileOpen(false);
    setMoreOpen(false);
  }

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMobileOpen(false);
        setMoreOpen(false);
      }
    }

    function closeOutside(event: PointerEvent) {
      if (
        moreOpen &&
        menuRef.current &&
        !menuRef.current.contains(event.target as Node)
      ) {
        setMoreOpen(false);
      }
    }

    document.addEventListener("keydown", closeOnEscape);
    document.addEventListener("pointerdown", closeOutside);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.removeEventListener("pointerdown", closeOutside);
    };
  }, [moreOpen]);

  return (
    <>
      <nav aria-label="Hauptnavigation" className="hidden items-center gap-1 md:flex">
        {primaryItems.map((item) => (
          <NavigationLink
            currentRoute={currentRoute}
            key={item.to}
            onNavigate={closeNavigation}
            {...item}
          />
        ))}
        <div className="relative" ref={menuRef}>
          <Button
            aria-controls="more-navigation"
            aria-expanded={moreOpen}
            onClick={() => setMoreOpen((open) => !open)}
            size="sm"
            variant="ghost"
          >
            Mehr
            <ChevronDown className="size-4" />
          </Button>
          {moreOpen ? (
            <div
              className="absolute right-0 top-11 z-50 grid min-w-64 gap-1 rounded-xl border border-border bg-popover p-2 shadow-elevated"
              id="more-navigation"
            >
              {moreItems.map((item) => (
                <NavigationLink
                  currentRoute={currentRoute}
                  key={item.to}
                  onNavigate={closeNavigation}
                  {...item}
                />
              ))}
            </div>
          ) : null}
        </div>
      </nav>

      <Button
        aria-controls="mobile-navigation"
        aria-expanded={mobileOpen}
        aria-label={mobileOpen ? "Navigation schließen" : "Navigation öffnen"}
        className="md:hidden"
        onClick={() => setMobileOpen((open) => !open)}
        size="icon"
        variant="secondary"
      >
        {mobileOpen ? <X className="size-5" /> : <Menu className="size-5" />}
      </Button>

      {mobileOpen ? (
        <nav
          aria-label="Mobile Navigation"
          className="absolute inset-x-4 top-20 z-50 grid gap-1 rounded-xl border border-border bg-popover p-3 shadow-elevated md:hidden"
          id="mobile-navigation"
        >
          {[...primaryItems, ...moreItems].map((item) => (
            <NavigationLink
              currentRoute={currentRoute}
              key={item.to}
              onNavigate={closeNavigation}
              {...item}
            />
          ))}
        </nav>
      ) : null}
    </>
  );
}
