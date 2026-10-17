import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ControlIdeaSeed } from "@/api/contracts";
import { IdeaSeedInbox } from "@/features/automation/idea-seed-inbox";
import { automationProject } from "@/test/automation-fixtures";

const mocks = vi.hoisted(() => ({
  dispositionIdeaSeed: vi.fn(),
  planIdeaSeed: vi.fn(),
  runControlExecutorOnce: vi.fn(),
  updateIdeaSeed: vi.fn(),
}));

vi.mock("@/features/automation/api", () => ({
  dispositionIdeaSeed: mocks.dispositionIdeaSeed,
  planIdeaSeed: mocks.planIdeaSeed,
  runControlExecutorOnce: mocks.runControlExecutorOnce,
  updateIdeaSeed: mocks.updateIdeaSeed,
}));

function ideaSeed(
  id: string,
  status: ControlIdeaSeed["status"],
  title: string,
): ControlIdeaSeed {
  return {
    id,
    project_id: automationProject.id,
    title,
    note: `${title} with tests and documentation.`,
    source: "human",
    status,
    provenance: {},
    created_at: "2026-08-26 10:00:00",
    updated_at: "2026-08-26 10:00:00",
  };
}

const seeds = [
  ideaSeed("IDEA-open", "inbox", "Accessible search"),
  ideaSeed("IDEA-deferred", "deferred", "Database browser"),
  ideaSeed("IDEA-dismissed", "dismissed", "Legacy redesign"),
];

function renderInbox(
  overrides: Partial<React.ComponentProps<typeof IdeaSeedInbox>> = {},
) {
  const props: React.ComponentProps<typeof IdeaSeedInbox> = {
    error: null,
    isError: false,
    isPending: false,
    onChanged: vi.fn().mockResolvedValue(undefined),
    onRetry: vi.fn().mockResolvedValue(undefined),
    projects: [automationProject],
    seeds,
    ...overrides,
  };
  return { props, ...render(<IdeaSeedInbox {...props} />) };
}

describe("IdeaSeedInbox", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows independent loading, error, and empty states", () => {
    const retry = vi.fn();
    const view = renderInbox({ isPending: true, onRetry: retry, seeds: undefined });
    expect(screen.getByText("Ideen werden geladen …")).toBeVisible();

    view.rerender(
      <IdeaSeedInbox
        error={new Error("Seed store unavailable")}
        isError
        isPending={false}
        onChanged={view.props.onChanged}
        onRetry={retry}
        projects={[automationProject]}
        seeds={undefined}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Seed store unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Ideen erneut laden" }));
    expect(retry).toHaveBeenCalledTimes(1);

    view.rerender(
      <IdeaSeedInbox
        error={null}
        isError={false}
        isPending={false}
        onChanged={view.props.onChanged}
        onRetry={retry}
        projects={[automationProject]}
        seeds={[]}
      />,
    );
    expect(screen.getByText("Keine offenen Ideen")).toBeVisible();
    expect(
      screen.getByText(/über „Idee beschreiben“ gestartet werden/),
    ).toBeVisible();
  });

  it("shows active and deferred ideas, reveals dismissed ideas, and edits content", async () => {
    const { props } = renderInbox();
    expect(screen.getByRole("article", { name: "Accessible search" })).toBeVisible();
    expect(screen.getByRole("article", { name: "Database browser" })).toBeVisible();
    expect(screen.queryByRole("article", { name: "Legacy redesign" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "1 verworfene Idee anzeigen" }));
    expect(screen.getByRole("article", { name: "Legacy redesign" })).toBeVisible();

    const card = screen.getByRole("article", { name: "Accessible search" });
    fireEvent.click(within(card).getByRole("button", { name: "Bearbeiten" }));
    const dialog = screen.getByRole("dialog", { name: "Idee bearbeiten" });
    fireEvent.change(within(dialog).getByLabelText("Titel"), {
      target: { value: "Accessible repository search" },
    });
    fireEvent.change(within(dialog).getByLabelText("Beschreibung"), {
      target: { value: "Build an accessible repository search with tests." },
    });
    mocks.updateIdeaSeed.mockResolvedValue({
      ...seeds[0],
      title: "Accessible repository search",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Speichern" }));

    await waitFor(() =>
      expect(mocks.updateIdeaSeed).toHaveBeenCalledWith("IDEA-open", {
        title: "Accessible repository search",
        note: "Build an accessible repository search with tests.",
      }),
    );
    expect(props.onChanged).toHaveBeenCalled();
  });

  it("requires a reason to defer or dismiss and can reopen a seed", async () => {
    const { props } = renderInbox();
    mocks.dispositionIdeaSeed.mockResolvedValue({ ...seeds[0], status: "deferred" });
    const openCard = screen.getByRole("article", { name: "Accessible search" });
    fireEvent.click(within(openCard).getByRole("button", { name: "Zurückstellen" }));
    const deferDialog = screen.getByRole("dialog", { name: "Idee zurückstellen" });
    const deferButton = within(deferDialog).getByRole("button", { name: "Zurückstellen" });
    expect(deferButton).toBeDisabled();
    fireEvent.change(within(deferDialog).getByLabelText("Begründung"), {
      target: { value: "Wait for the API migration." },
    });
    fireEvent.click(deferButton);
    await waitFor(() =>
      expect(mocks.dispositionIdeaSeed).toHaveBeenCalledWith("IDEA-open", {
        disposition: "deferred",
        reason: "Wait for the API migration.",
      }),
    );

    fireEvent.click(within(openCard).getByRole("button", { name: "Verwerfen" }));
    const dismissDialog = screen.getByRole("dialog", { name: "Idee verwerfen" });
    fireEvent.change(within(dismissDialog).getByLabelText("Begründung"), {
      target: { value: "No longer aligned with the product." },
    });
    fireEvent.click(within(dismissDialog).getByRole("button", { name: "Verwerfen" }));
    await waitFor(() =>
      expect(mocks.dispositionIdeaSeed).toHaveBeenCalledWith("IDEA-open", {
        disposition: "dismissed",
        reason: "No longer aligned with the product.",
      }),
    );

    const deferredCard = screen.getByRole("article", { name: "Database browser" });
    fireEvent.click(within(deferredCard).getByRole("button", { name: "Wieder öffnen" }));
    await waitFor(() =>
      expect(mocks.dispositionIdeaSeed).toHaveBeenCalledWith("IDEA-deferred", {
        disposition: "inbox",
        reason: "",
      }),
    );
    expect(props.onChanged).toHaveBeenCalledTimes(3);
  });

  it("keeps mutation errors visible in the active dialog", async () => {
    const { props } = renderInbox();
    mocks.updateIdeaSeed.mockRejectedValue(new Error("Seed could not be saved"));
    const card = screen.getByRole("article", { name: "Accessible search" });
    fireEvent.click(within(card).getByRole("button", { name: "Bearbeiten" }));
    const dialog = screen.getByRole("dialog", { name: "Idee bearbeiten" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Speichern" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Seed could not be saved",
    );
    expect(dialog).toBeVisible();
    expect(props.onChanged).not.toHaveBeenCalled();
  });

  it("starts planning for the existing seed with a clear execution choice and keeps partial success visible", async () => {
    const { props } = renderInbox();
    mocks.planIdeaSeed.mockResolvedValue({
      id: "PLAN-1",
      idea_seed_id: "IDEA-open",
      status: "queued",
    });
    mocks.runControlExecutorOnce.mockRejectedValue(new Error("Executor unavailable"));
    const card = screen.getByRole("article", { name: "Accessible search" });
    fireEvent.click(within(card).getByRole("button", { name: "Mit KI planen" }));
    const dialog = screen.getByRole("dialog", { name: "Idee mit KI planen" });
    expect(
      within(dialog).getByLabelText(
        "Plan freigeben, dann sichere PR-Wellen automatisch abarbeiten",
      ),
    ).toBeChecked();
    fireEvent.click(within(dialog).getByLabelText("Vor jedem PR erneut fragen"));
    fireEvent.click(within(dialog).getByRole("button", { name: "KI-Planung starten" }));

    await waitFor(() =>
      expect(mocks.planIdeaSeed).toHaveBeenCalledWith("IDEA-open", {
        activation_policy: "per_candidate",
        planning_depth: "deep",
        max_candidates: 30,
        constraints: [],
      }),
    );
    expect(mocks.runControlExecutorOnce).toHaveBeenCalledTimes(1);
    expect(props.onChanged).toHaveBeenCalled();
    expect(
      await screen.findByText(/Planung ist eingeplant.*Executor.*nicht sofort gestartet/i),
    ).toBeVisible();
  });
});
