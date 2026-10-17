import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/errors";
import { StudioPage } from "@/pages/studio-page";

const mocks = vi.hoisted(() => ({
  useStudioData: vi.fn(),
}));

vi.mock("@/features/studio/use-studio-data", () => ({
  useStudioData: mocks.useStudioData,
}));

function renderStudio() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <StudioPage />
    </QueryClientProvider>,
  );
}

function query(options: {
  data?: unknown;
  error?: unknown;
  pending?: boolean;
  success?: boolean;
} = {}) {
  return {
    data: options.data,
    error: options.error ?? null,
    isPending: options.pending ?? false,
    isError: Boolean(options.error),
    isSuccess: options.success ?? Boolean(options.data),
    refetch: vi.fn().mockResolvedValue(undefined),
  };
}

function fullStudioData() {
  return {
    control: query({
      data: {
        policy: { mode: "guided", paused: false },
        summary: { tasks_active: 0 },
        attention: [],
        tasks: [],
      },
    }),
    conversations: query({
      data: {
        conversations: [],
        counts: { running: 1, complete: 2, archived: 0 },
        active_agents: [],
        filters: {},
      },
    }),
    projects: query({
      data: {
        projects: [
          {
            id: 1,
            name: "Hub",
            path: "D:\\Hub",
            github_url: "https://github.com/example/hub",
            github_owner: "example",
            github_repo: "antigravity-web",
            default_branch: "main",
            git_branch: "main",
            source_kind: "github",
            github_bootstrap_required: false,
            github_bootstrap_status: "ready",
            antigravity_linked: true,
            antigravity_project_name: "Hub",
          },
        ],
      },
    }),
  };
}

describe("StudioPage states", () => {
  it("renders live data", () => {
    mocks.useStudioData.mockReturnValue(fullStudioData());
    renderStudio();
    expect(screen.getByRole("heading", { name: "Studio" })).toBeVisible();
    expect(screen.getByText("antigravity-web")).toBeVisible();
    expect(screen.queryByText("Arbeitsmodus")).not.toBeInTheDocument();
    expect(screen.queryByText("guided", { exact: false })).not.toBeInTheDocument();
  });

  it("keeps projects and active work ahead of secondary next actions", () => {
    mocks.useStudioData.mockReturnValue(fullStudioData());
    renderStudio();
    const projects = screen.getByRole("heading", { name: "Projekte" });
    const activeWork = screen.getByRole("heading", { name: "Aktive Aufgaben" });
    const nextActions = screen.getByRole("heading", { name: "Als Nächstes" });
    expect(projects.compareDocumentPosition(activeWork)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(activeWork.compareDocumentPosition(nextActions)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(screen.queryByText("maximal drei", { exact: false })).not.toBeInTheDocument();
  });

  it("renders the initial loading state", () => {
    const pending = query({ pending: true });
    mocks.useStudioData.mockReturnValue({
      control: pending,
      conversations: pending,
      projects: pending,
    });
    renderStudio();
    expect(screen.getByRole("heading", { name: "Einen Moment bitte" })).toBeVisible();
  });

  it("keeps successful data visible during a partial failure", () => {
    const data = fullStudioData();
    data.conversations = query({ error: new Error("CDP unavailable") });
    mocks.useStudioData.mockReturnValue(data);
    renderStudio();
    expect(screen.getByText(/1 von 3 Datenquellen/)).toBeVisible();
    expect(screen.getByText("antigravity-web")).toBeVisible();
  });

  it("renders an empty project state", () => {
    const data = fullStudioData();
    data.projects = query({ data: { projects: [] }, success: true });
    mocks.useStudioData.mockReturnValue(data);
    renderStudio();
    expect(screen.getByRole("heading", { name: "Noch keine Projekte" })).toBeVisible();
  });

  it("renders offline only when every source is unavailable", () => {
    const unavailable = query({
      error: new ApiError("Offline", { offline: true }),
    });
    mocks.useStudioData.mockReturnValue({
      control: unavailable,
      conversations: unavailable,
      projects: unavailable,
    });
    renderStudio();
    expect(screen.getByRole("heading", { name: "Hub nicht erreichbar" })).toBeVisible();
  });
});
