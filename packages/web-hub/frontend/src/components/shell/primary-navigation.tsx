import { ChevronDown, Menu, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { useHubLanguage } from "@/lib/i18n";
import { routeHref, type AppRoute, type HubRoute, useHubRoute } from "@/lib/routing";
import { cn } from "@/lib/utils";

const primaryItems: ReadonlyArray<{
  labelDe: string;
  labelEn: string;
  to: HubRoute;
}> = [
  { labelDe: "Studio", labelEn: "Studio", to: "/studio" },
  { labelDe: "Chats", labelEn: "Chats", to: "/chats" },
  { labelDe: "Automation", labelEn: "Automation", to: "/automation" },
  { labelDe: "API-Logs", labelEn: "API-Logs", to: "/api-logs" },
];

const moreItems: ReadonlyArray<{
  labelDe: string;
  labelEn: string;
  to: HubRoute;
}> = [
  {
    labelDe: "API & Audit-Logs",
    labelEn: "API & Audit Logs",
    to: "/api-logs",
  },
  {
    labelDe: "Scheduled Tasks",
    labelEn: "Scheduled Tasks",
    to: "/scheduled-tasks",
  },
  {
    labelDe: "Hilfe & Dokumentation",
    labelEn: "Help & Documentation",
    to: "/help",
  },
  {
    labelDe: "Systemstatus & Diagnose",
    labelEn: "System Status & Diagnostics",
    to: "/system",
  },
  { labelDe: "Einstellungen", labelEn: "Settings", to: "/settings" },
  {
    labelDe: "Wissen & Lessons Learned",
    labelEn: "Knowledge & Lessons Learned",
    to: "/knowledge",
  },
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

export function LanguageSwitch() {
  const [lang, setLang] = useHubLanguage();
  return (
    <div
      aria-label={lang === "de" ? "Sprache wechseln" : "Switch language"}
      className="inline-flex items-center rounded-lg border border-border bg-muted/60 p-0.5 text-xs font-semibold"
      role="group"
    >
      <button
        aria-pressed={lang === "de"}
        className={cn(
          "rounded-md px-2 py-1 transition-colors",
          lang === "de"
            ? "bg-primary text-primary-foreground"
            : "text-muted-foreground hover:text-foreground",
        )}
        onClick={() => setLang("de")}
        type="button"
      >
        DE
      </button>
      <button
        aria-pressed={lang === "en"}
        className={cn(
          "rounded-md px-2 py-1 transition-colors",
          lang === "en"
            ? "bg-primary text-primary-foreground"
            : "text-muted-foreground hover:text-foreground",
        )}
        onClick={() => setLang("en")}
        type="button"
      >
        EN
      </button>
    </div>
  );
}

export function PrimaryNavigation() {
  const currentRoute = useHubRoute();
  const [lang] = useHubLanguage();
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
      <nav
        aria-label="Hauptnavigation"
        className="hidden items-center gap-1 md:flex"
      >
        {primaryItems.map((item) => (
          <NavigationLink
            currentRoute={currentRoute}
            key={item.to}
            label={lang === "en" ? item.labelEn : item.labelDe}
            onNavigate={closeNavigation}
            to={item.to}
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
            {lang === "en" ? "More" : "Mehr"}
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
                  label={lang === "en" ? item.labelEn : item.labelDe}
                  onNavigate={closeNavigation}
                  to={item.to}
                />
              ))}
            </div>
          ) : null}
        </div>
        <div className="ml-2">
          <LanguageSwitch />
        </div>
      </nav>

      <div className="flex items-center gap-2 md:hidden">
        <LanguageSwitch />
        <Button
          aria-controls="mobile-navigation"
          aria-expanded={mobileOpen}
          aria-label={
            mobileOpen ? "Navigation schließen" : "Navigation öffnen"
          }
          onClick={() => setMobileOpen((open) => !open)}
          size="icon"
          variant="secondary"
        >
          {mobileOpen ? <X className="size-5" /> : <Menu className="size-5" />}
        </Button>
      </div>

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
              label={lang === "en" ? item.labelEn : item.labelDe}
              onNavigate={closeNavigation}
              to={item.to}
            />
          ))}
        </nav>
      ) : null}
    </>
  );
}
