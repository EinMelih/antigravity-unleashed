import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAutomationData } from "@/features/automation/use-automation-data";

const mocks = vi.hoisted(() => ({
  getControlOverview: vi.fn(),
  getProjects: vi.fn(),
  getWorkers: vi.fn(),
  listIdeaSeeds: vi.fn(),
  useHubHealth: vi.fn(),
}));

vi.mock("@/features/studio/api", () => ({
  getControlOverview: mocks.getControlOverview,
  getProjects: mocks.getProjects,
  getWorkers: mocks.getWorkers,
}));

vi.mock("@/features/automation/api", () => ({
  listIdeaSeeds: mocks.listIdeaSeeds,
}));

vi.mock("@/hooks/use-hub-health", () => ({
  useHubHealth: mocks.useHubHealth,
}));

describe("useAutomationData", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getControlOverview.mockResolvedValue({ campaigns: [] });
    mocks.getProjects.mockResolvedValue({ projects: [] });
    mocks.getWorkers.mockResolvedValue({ workers: [] });
    mocks.listIdeaSeeds.mockResolvedValue([
      {
        id: "IDEA-1",
        project_id: 52,
        title: "Accessible search",
        note: "Build an accessible project search with tests.",
        source: "human",
        status: "inbox",
        provenance: {},
        created_at: "2026-08-26 10:00:00",
        updated_at: "2026-08-26 10:00:00",
      },
    ]);
    mocks.useHubHealth.mockReturnValue({ data: { status: "ok" } });
  });

  it("loads idea seeds as an independent automation query", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    function Wrapper({ children }: PropsWithChildren) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    const { result } = renderHook(() => useAutomationData(), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.ideaSeeds.isSuccess).toBe(true));
    expect(mocks.listIdeaSeeds).toHaveBeenCalledTimes(1);
    expect(result.current.ideaSeeds.data?.[0]?.id).toBe("IDEA-1");
  });
});
