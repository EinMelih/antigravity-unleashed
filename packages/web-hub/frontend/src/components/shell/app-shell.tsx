import { type ReactNode, useEffect } from "react";

import { CommandPalette } from "@/components/shell/command-palette";
import { PrimaryNavigation } from "@/components/shell/primary-navigation";
import { SystemConnection } from "@/components/shell/system-connection";
import { applyHubI18nToDom, useHubLanguage } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { useHubRoute } from "@/lib/routing";

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const route = useHubRoute();
  const [lang] = useHubLanguage();
  const immersive = route === "/chats";

  useEffect(() => {
    applyHubI18nToDom(document.body, lang);
  }, [route, lang]);

  return (
    <div className={cn("min-h-svh bg-background text-foreground", immersive && "h-svh overflow-hidden")}>
      <a
        className="sr-only z-[100] rounded-md bg-primary px-4 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
        href="#main-content"
      >
        {lang === "en" ? "Skip to main content" : "Zum Inhalt springen"}
      </a>
      <header className="sticky top-0 z-40 border-b border-border/80 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/85">
        <div className="app-shell-frame relative flex min-h-16 items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <div
              aria-hidden="true"
              className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-primary/25 bg-primary/10 text-sm font-bold text-primary-foreground"
            >
              AG
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">Anti-Gravity Hub</p>
              <div className="mt-0.5 hidden sm:block">
                <SystemConnection />
              </div>
            </div>
          </div>
          <PrimaryNavigation />
        </div>
      </header>
      <main
        className={cn(
          immersive
            ? "h-[calc(100svh-4rem)] w-full min-w-0 overflow-hidden"
            : "app-shell-frame px-4 py-8 sm:px-6 lg:px-8 lg:py-10",
        )}
        id="main-content"
      >
        {children}
      </main>
      <CommandPalette />
    </div>
  );
}
