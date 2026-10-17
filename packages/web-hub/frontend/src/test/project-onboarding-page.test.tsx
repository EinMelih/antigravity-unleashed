import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HubProject } from "@/api/contracts";
import { ProjectOnboardingPage } from "@/pages/project-onboarding-page";

const mocks = vi.hoisted(() => ({
  createAntiGravityProject: vi.fn(),
  createHubProject: vi.fn(),
  getAvailableAntiGravityProjects: vi.fn(),
  getGitHubRepositories: vi.fn(),
  importGitHubProject: vi.fn(),
  linkAntiGravityProject: vi.fn(),
}));

vi.mock("@/features/projects/onboarding-api", () => mocks);

const project: HubProject = {
  id: 12,
  name: "cats",
  path: "D:\\Projects\\cats",
  github_url: "https://github.com/user/cats",
  github_owner: "user",
  github_repo: "cats",
  default_branch: "main",
  git_branch: "main",
  source_kind: "github",
  github_bootstrap_required: false,
  github_bootstrap_status: "ready",
  antigravity_linked: false,
  antigravity_project_name: "",
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><ProjectOnboardingPage /></QueryClientProvider>);
}

describe("ProjectOnboardingPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getGitHubRepositories.mockResolvedValue({
      repositories: [{
        id: 1,
        name: "cats",
        full_name: "user/cats",
        owner: "user",
        html_url: "https://github.com/user/cats",
        clone_url: "https://github.com/user/cats.git",
        description: "Cat catalog",
        private: true,
        default_branch: "main",
        updated_at: "2026-08-01T12:00:00Z",
        imported: false,
        suggested_local_path: "D:\\Projects\\cats",
      }],
    });
    mocks.getAvailableAntiGravityProjects.mockResolvedValue({ projects: [] });
  });

  it("imports a selected repository into its suggested local path", async () => {
    const user = userEvent.setup();
    mocks.importGitHubProject.mockResolvedValue(project);
    renderPage();

    await user.click(await screen.findByRole("button", { name: /user\/cats/ }));
    expect(screen.getByLabelText(/Windows-Pfad/)).toHaveValue("D:\\Projects\\cats");
    await user.click(screen.getByRole("button", { name: "Repository importieren" }));

    await waitFor(() => expect(mocks.importGitHubProject).toHaveBeenCalledWith({
      full_name: "user/cats",
      path: "D:\\Projects\\cats",
    }));
    expect(await screen.findByText("Repository und lokaler Projektordner sind bereit.")).toBeVisible();
    expect(screen.getByRole("link", { name: /Projekt öffnen/ })).toHaveAttribute("href", "#/projects/12");
  });

  it("creates a private GitHub project with safe defaults", async () => {
    const user = userEvent.setup();
    mocks.createHubProject.mockResolvedValue(project);
    renderPage();

    await user.click(screen.getByRole("button", { name: /Neues Projekt/ }));
    await user.type(screen.getByLabelText("Projektname"), "cats");
    await user.click(screen.getByRole("button", { name: "Projekt erstellen" }));

    await waitFor(() => expect(mocks.createHubProject).toHaveBeenCalledWith({
      name: "cats",
      path: undefined,
      test_command: "python -m unittest",
      create_github: true,
      github_visibility: "private",
    }));
  });

  it("links the imported repository to an existing Anti-Gravity project", async () => {
    const user = userEvent.setup();
    mocks.importGitHubProject.mockResolvedValue(project);
    mocks.getAvailableAntiGravityProjects.mockResolvedValue({
      projects: [{ id: "ag-project-7", name: "Cats", display_name: "Cats", project_uuid: "project-7" }],
    });
    mocks.linkAntiGravityProject.mockResolvedValue({
      success: true,
      project_id: 12,
      antigravity_project_id: "ag-project-7",
      antigravity_project_name: "Cats",
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /user\/cats/ }));
    await user.click(screen.getByRole("button", { name: "Repository importieren" }));
    await user.click(await screen.findByRole("combobox", { name: "Anti-Gravity-Projekt auswählen" }));
    await user.click(await screen.findByRole("option", { name: "Cats" }));
    await user.click(screen.getByRole("button", { name: "Verknüpfen" }));

    await waitFor(() => expect(mocks.linkAntiGravityProject).toHaveBeenCalledWith(12, "ag-project-7"));
    expect(await screen.findByText("Mit Anti-Gravity-Projekt „Cats“ verknüpft.")).toBeVisible();
    expect(screen.getByText("Bereit")).toBeVisible();
  });
});
