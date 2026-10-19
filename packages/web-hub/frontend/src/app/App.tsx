import { lazy, Suspense } from "react";

import { AppShell } from "@/components/shell/app-shell";
import { LoadingState } from "@/components/states";
import { useIsHeadlessLinux } from "@/hooks/use-hub-health";
import { usePageEntrance } from "@/hooks/use-page-entrance";
import { useHubRoute } from "@/lib/routing";

const ApiLogsPage = lazy(() => import("@/pages/api-logs-page").then((module) => ({ default: module.ApiLogsPage })));
const AutomationPage = lazy(() => import("@/pages/automation-page").then((module) => ({ default: module.AutomationPage })));
const ChatsPage = lazy(() => import("@/pages/chats-page").then((module) => ({ default: module.ChatsPage })));
const HelpPage = lazy(() => import("@/pages/help-page").then((module) => ({ default: module.HelpPage })));
const KnowledgePage = lazy(() => import("@/pages/knowledge-page").then((module) => ({ default: module.KnowledgePage })));
const MorePage = lazy(() => import("@/pages/more-page").then((module) => ({ default: module.MorePage })));
const ProjectOnboardingPage = lazy(() => import("@/pages/project-onboarding-page").then((module) => ({ default: module.ProjectOnboardingPage })));
const ProjectOverviewPage = lazy(() => import("@/pages/project-overview-page").then((module) => ({ default: module.ProjectOverviewPage })));
const ScheduledTasksPage = lazy(() => import("@/pages/scheduled-tasks-page").then((module) => ({ default: module.ScheduledTasksPage })));
const SettingsPage = lazy(() => import("@/pages/settings-page").then((module) => ({ default: module.SettingsPage })));
const StudioPage = lazy(() => import("@/pages/studio-page").then((module) => ({ default: module.StudioPage })));
const SystemStatusPage = lazy(() => import("@/pages/system-status-page").then((module) => ({ default: module.SystemStatusPage })));

function CurrentPage() {
  const route = useHubRoute();
  const isHeadlessLinux = useIsHeadlessLinux();
  const pageRef = usePageEntrance(route);

  let content;

  if (isHeadlessLinux) {
    content = <ApiLogsPage />;
  } else if (route === "/projects/new") {
    content = <ProjectOnboardingPage />;
  } else if (route.startsWith("/projects/")) {
    content = <ProjectOverviewPage projectId={Number(route.split("/").at(-1))} />;
  } else {
    switch (route) {
      case "/chats":
        content = <ChatsPage />;
        break;
      case "/automation":
        content = <AutomationPage />;
        break;
      case "/more":
        content = <MorePage />;
        break;
      case "/scheduled-tasks":
        content = <ScheduledTasksPage />;
        break;
      case "/help":
        content = <HelpPage />;
        break;
      case "/system":
        content = <SystemStatusPage />;
        break;
      case "/settings":
        content = <SettingsPage />;
        break;
      case "/knowledge":
        content = <KnowledgePage />;
        break;
      case "/api-logs":
        content = <ApiLogsPage />;
        break;
      case "/studio":
      default:
        content = <StudioPage />;
    }
  }
  return (
    <div key={route} ref={pageRef}>
      <Suspense fallback={<LoadingState description="Die Ansicht wird vorbereitet." />}>
        {content}
      </Suspense>
    </div>
  );
}

export function App() {
  return (
    <AppShell>
      <CurrentPage />
    </AppShell>
  );
}
