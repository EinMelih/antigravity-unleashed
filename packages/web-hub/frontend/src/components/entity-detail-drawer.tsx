import { X } from "lucide-react";
import {
  type ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/button";

export interface EntityDetailTab {
  id: string;
  label: string;
  content: ReactNode;
}

interface EntityDetailDrawerProps {
  action?: ReactNode;
  description?: string;
  entityKey: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  status?: ReactNode;
  tabs: EntityDetailTab[];
  title: string;
}

export function EntityDetailDrawer({
  action,
  description,
  entityKey,
  onOpenChange,
  open,
  status,
  tabs,
  title,
}: EntityDetailDrawerProps) {
  const [tabSelection, setTabSelection] = useState({
    entityKey,
    tabId: tabs[0]?.id ?? "overview",
  });
  const drawerRef = useRef<HTMLElement>(null);
  const onOpenChangeRef = useRef(onOpenChange);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    onOpenChangeRef.current = onOpenChange;
  }, [onOpenChange]);

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    drawerRef.current
      ?.querySelector<HTMLButtonElement>('[aria-label="Details schließen"]')
      ?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onOpenChangeRef.current(false);
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;
      const focusable = Array.from(
        drawerRef.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus();
    };
  }, [open]);

  if (!open || tabs.length === 0) return null;
  const activeTab =
    tabSelection.entityKey === entityKey ? tabSelection.tabId : "overview";
  const selectedTab = tabs.find((tab) => tab.id === activeTab) ?? tabs[0];
  if (!selectedTab) return null;

  return createPortal(
    <div
      className="entity-drawer-root"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onOpenChange(false);
      }}
    >
      <section
        aria-describedby={description ? descriptionId : undefined}
        aria-labelledby={titleId}
        aria-modal="true"
        className="entity-drawer"
        ref={drawerRef}
        role="dialog"
      >
        <header className="entity-drawer-header">
          <div className="min-w-0 flex-1">
            <div className="mb-2 flex flex-wrap items-center gap-2">{status}</div>
            <h2 className="text-xl font-semibold leading-7" id={titleId}>
              {title}
            </h2>
            {description ? (
              <p className="mt-1 text-sm text-muted-foreground" id={descriptionId}>
                {description}
              </p>
            ) : null}
          </div>
          <Button
            aria-label="Details schließen"
            onClick={() => onOpenChange(false)}
            size="icon"
            variant="ghost"
          >
            <X className="size-5" />
          </Button>
        </header>

        {action ? <div className="entity-drawer-action">{action}</div> : null}

        <div aria-label="Detailbereiche" className="entity-drawer-tabs" role="tablist">
          {tabs.map((tab) => (
            <button
              aria-controls={`entity-panel-${tab.id}`}
              aria-selected={selectedTab.id === tab.id}
              className="entity-drawer-tab"
              id={`entity-tab-${tab.id}`}
              key={tab.id}
              onClick={() => setTabSelection({ entityKey, tabId: tab.id })}
              role="tab"
              type="button"
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div
          aria-labelledby={`entity-tab-${selectedTab.id}`}
          className="entity-drawer-content"
          id={`entity-panel-${selectedTab.id}`}
          role="tabpanel"
        >
          {selectedTab.content}
        </div>
      </section>
    </div>,
    document.body,
  );
}
