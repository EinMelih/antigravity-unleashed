import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useChatContextData,
  useNewChatModels,
} from "@/features/chats/use-chats-data";

const mocks = vi.hoisted(() => ({
  getActiveModel: vi.fn(),
  getChatHistory: vi.fn(),
  getConversationCatalog: vi.fn(),
  getModelCatalog: vi.fn(),
  getProjects: vi.fn(),
  getWorkers: vi.fn(),
}));

vi.mock("@/features/chats/api", () => ({
  getActiveModel: mocks.getActiveModel,
  getChatHistory: mocks.getChatHistory,
  getConversationCatalog: mocks.getConversationCatalog,
  getModelCatalog: mocks.getModelCatalog,
}));

vi.mock("@/features/studio/api", () => ({
  getProjects: mocks.getProjects,
  getWorkers: mocks.getWorkers,
}));

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("chat data query ownership", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getProjects.mockResolvedValue({ projects: [] });
    mocks.getWorkers.mockResolvedValue({ workers: [] });
    mocks.getModelCatalog.mockResolvedValue({ current: "Gemini", models: [] });
  });

  it("loads only workers and projects for page-level chat context", async () => {
    const { result } = renderHook(() => useChatContextData(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.projects.isSuccess).toBe(true);
      expect(result.current.workers.isSuccess).toBe(true);
    });

    expect(mocks.getProjects).toHaveBeenCalledTimes(1);
    expect(mocks.getWorkers).toHaveBeenCalledTimes(1);
    expect(mocks.getChatHistory).not.toHaveBeenCalled();
    expect(mocks.getActiveModel).not.toHaveBeenCalled();
    expect(mocks.getModelCatalog).not.toHaveBeenCalled();
  });

  it("loads creation models only while the new-chat dialog is open", async () => {
    const { result, rerender } = renderHook(
      ({ open }: { open: boolean }) => useNewChatModels(open),
      { initialProps: { open: false }, wrapper: createWrapper() },
    );

    expect(result.current.fetchStatus).toBe("idle");
    expect(mocks.getModelCatalog).not.toHaveBeenCalled();

    rerender({ open: true });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mocks.getModelCatalog).toHaveBeenCalledTimes(1);
  });
});
