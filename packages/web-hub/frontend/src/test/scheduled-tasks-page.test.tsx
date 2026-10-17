import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/errors";
import { ScheduledTasksPage } from "@/pages/scheduled-tasks-page";

const mocks = vi.hoisted(() => ({ useScheduledTasksData: vi.fn() }));

vi.mock("@/features/scheduled-tasks/use-scheduled-tasks-data", () => ({
  useScheduledTasksData: mocks.useScheduledTasksData,
}));

function query(options: { data?: unknown; error?: unknown; pending?: boolean } = {}) {
  return {
    data: options.data,
    error: options.error ?? null,
    isError: Boolean(options.error),
    isPending: options.pending ?? false,
    refetch: vi.fn().mockResolvedValue(undefined),
  };
}

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

function scheduledData() {
  return {
    tasks: query({ data: {
      connected: true,
      count: 2,
      tasks: [
        {
          all_projects: false,
          command: ["agent", "run"],
          enabled: true,
          id: "daily-check",
          is_bundled: false,
          last_error: "",
          name: "Täglicher Check",
          project_id: "project-1",
          prompt: "Prüfe Pull Requests",
          schedule: "0 9 * * *",
          start_time_ms: "",
          status_code: 0,
        },
        {
          all_projects: true,
          command: ["agent", "run"],
          enabled: false,
          id: "weekly-report",
          is_bundled: false,
          last_error: "Letzter Lauf fehlgeschlagen",
          name: "Wochenbericht",
          project_id: "",
          prompt: "Erstelle den Bericht",
          schedule: "0 10 * * 1",
          start_time_ms: "",
          status_code: 0,
        },
      ],
    } }),
    projects: query({ data: { projects: [{ display_name: "Antigravity Agent", id: "project-1", name: "Antigravity Agent" }] } }),
    events: query({ data: { events: [{ status: "complete", timestampMs: 1785758400000 }], task_id: "daily-check" } }),
  };
}

describe("ScheduledTasksPage", () => {
  it("shows compact task state and filters paused tasks", () => {
    mocks.useScheduledTasksData.mockReturnValue(scheduledData());
    render(<ScheduledTasksPage />, { wrapper });
    expect(screen.getByRole("heading", { name: "Scheduled Tasks" })).toBeVisible();
    expect(screen.getByText("Täglich · 09:00")).toBeVisible();
    expect(screen.getByText("Antigravity Agent")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Pausiert" }));
    expect(screen.queryByText("Täglicher Check")).not.toBeInTheDocument();
    expect(screen.getByText("Wochenbericht")).toBeVisible();
  });

  it("opens details and native events", () => {
    mocks.useScheduledTasksData.mockReturnValue(scheduledData());
    render(<ScheduledTasksPage />, { wrapper });
    fireEvent.click(screen.getByRole("button", { name: /Täglicher Check/ }));
    expect(screen.getByRole("dialog", { name: "Täglicher Check" })).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Events (1)" }));
    expect(screen.getByText(/"status": "complete"/)).toBeVisible();
  });

  it("shows the native offline state with recovery guidance", () => {
    const data = scheduledData();
    data.tasks = query({ error: new ApiError("DevTools nicht gefunden", { offline: true }) });
    mocks.useScheduledTasksData.mockReturnValue(data);
    render(<ScheduledTasksPage />, { wrapper });
    expect(screen.getByRole("heading", { name: "Anti-Gravity Scheduled Tasks nicht bereit" })).toBeVisible();
    expect(screen.getByText(/Starte Anti-Gravity/)).toBeVisible();
  });
});
