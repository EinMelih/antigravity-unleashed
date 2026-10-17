import { Plus, RefreshCw, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { ApiError } from "@/api/errors";
import { EmptyState, ErrorState, LoadingState, OfflineState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AutomationStatus } from "@/features/automation/automation-status";
import { AutomationDeployments } from "@/features/automation/automation-deployments";
import { AutomationJourney } from "@/features/automation/automation-journey";
import { AutomationMetrics } from "@/features/automation/automation-metrics";
import { AttentionQueue } from "@/features/automation/attention-queue";
import { CampaignPlanDialog } from "@/features/automation/campaign-plan-dialog";
import { IdeaSeedInbox } from "@/features/automation/idea-seed-inbox";
import {
  buildAttentionQueue,
  filterWorkItems,
  flattenWorkItems,
  type WorkItemFilter,
} from "@/features/automation/model";
import { NewEndeavorDialog } from "@/features/automation/new-endeavor-dialog";
import { EndeavorList } from "@/features/automation/endeavor-list";
import { useAutomationData } from "@/features/automation/use-automation-data";
import { WorkItemDetail } from "@/features/automation/work-item-detail";
import { WorkItemList } from "@/features/automation/work-item-list";

const filters: Array<{ id: WorkItemFilter; label: string }> = [
  { id: "active", label: "Aktiv" },
  { id: "attention", label: "Entscheidung nötig" },
  { id: "all", label: "Alle" },
];

export function AutomationPage() {
  const data = useAutomationData();
  const [filter, setFilter] = useState<WorkItemFilter>("active");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string>();
  const [selectedPlanningJobId, setSelectedPlanningJobId] = useState<string>();
  const [selectedCampaignId, setSelectedCampaignId] = useState<string>();
  const [planningOpen, setPlanningOpen] = useState(false);
  const projects = useMemo(
    () => data.projects.data?.projects ?? [],
    [data.projects.data?.projects],
  );
  const planningJobs = data.control.data?.planning_jobs ?? [];
  const explicitlySelectedPlanningJob = planningJobs.find((job) => job.id === selectedPlanningJobId);
  const selectedCampaign = data.control.data?.campaigns.find(
    (campaign) => campaign.id === (selectedCampaignId || explicitlySelectedPlanningJob?.campaign_id),
  );
  const selectedOpenAmendment = selectedCampaign?.amendments?.find((amendment) =>
    ["planning", "review", "failed", "proposed"].includes(amendment.status),
  );
  const selectedPlanningJob = explicitlySelectedPlanningJob ?? (
    !selectedPlanningJobId && selectedCampaign && selectedOpenAmendment
      ? planningJobs.find((job) =>
          job.job_type === "plan_amendment" &&
          job.campaign_id === selectedCampaign.id &&
          (
            job.amendment_id === selectedOpenAmendment.id ||
            job.id === selectedOpenAmendment.planning_job_id
          ),
        )
      : undefined
  );
  const items = useMemo(
    () =>
      data.control.data
        ? flattenWorkItems(data.control.data, projects)
        : [],
    [data.control.data, projects],
  );
  const visibleItems = useMemo(
    () => filterWorkItems(items, filter, search),
    [filter, items, search],
  );
  const selectedItem = items.find((item) => item.id === selectedId);
  const attentionEntries = useMemo(
    () =>
      data.control.data
        ? buildAttentionQueue(data.control.data, projects, items)
        : [],
    [data.control.data, items, projects],
  );
  const supportingQueries = [data.health, data.workers, data.projects];
  const partialErrors = supportingQueries.filter((query) => query.isError).length;

  function refreshAll() {
    void Promise.all([
      data.health.refetch(),
      data.control.refetch(),
      data.workers.refetch(),
      data.projects.refetch(),
      data.ideaSeeds.refetch(),
    ]);
  }

  if (data.control.isPending) {
    return <LoadingState description="Umsetzung und Prüfnachweise werden geladen." />;
  }

  if (data.control.isError) {
    if (data.control.error instanceof ApiError && data.control.error.offline) {
      return <OfflineState onRetry={refreshAll} />;
    }
    return (
      <ErrorState
        description={
          data.control.error instanceof Error
            ? data.control.error.message
            : "Der aktuelle Stand der Automation konnte nicht geladen werden."
        }
        onRetry={refreshAll}
        title="Automation nicht verfügbar"
      />
    );
  }

  return (
    <div className="space-y-7">
      <header className="automation-page-header">
        <div>
          <p className="eyebrow">Arbeitssteuerung</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">Automation</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            Beschreibe dein Ziel. Anti-Gravity erstellt einen Plan, setzt freigegebene PRs in
            Reihenfolge um und legt sie dir zur Prüfung vor.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => setPlanningOpen(true)} size="sm">
            <Plus className="size-4" />
            Idee beschreiben
          </Button>
          <Button onClick={refreshAll} size="sm" variant="secondary">
            <RefreshCw className="size-4" />
            Aktualisieren
          </Button>
        </div>
      </header>

      <AutomationJourney />

      <AutomationStatus
        control={data.control.data}
        health={data.health.data}
        workers={data.workers.data}
        workersError={data.workers.isError}
        workersLoading={data.workers.isPending}
      />

      {partialErrors > 0 ? (
        <div className="partial-error" role="status">
          {partialErrors} ergänzende {partialErrors === 1 ? "Datenquelle ist" : "Datenquellen sind"}
          gerade nicht erreichbar. Die Umsetzung bleibt verfügbar.
        </div>
      ) : null}

      <AttentionQueue
        entries={attentionEntries}
        onOpenPlanning={(campaignId, planningJobId) => {
          setSelectedId(undefined);
          setSelectedCampaignId(campaignId);
          setSelectedPlanningJobId(planningJobId);
        }}
        onOpenWorkItem={(workItemId) => {
          setSelectedCampaignId(undefined);
          setSelectedPlanningJobId(undefined);
          setSelectedId(workItemId);
        }}
      />

      <IdeaSeedInbox
        error={data.ideaSeeds.error}
        isError={data.ideaSeeds.isError}
        isPending={data.ideaSeeds.isPending}
        onChanged={async () => {
          await Promise.all([
            data.ideaSeeds.refetch({ throwOnError: true }),
            data.control.refetch({ throwOnError: true }),
          ]);
        }}
        onRetry={() => data.ideaSeeds.refetch()}
        projects={projects}
        seeds={data.ideaSeeds.data}
      />

      <EndeavorList
        campaigns={data.control.data.campaigns}
        jobs={planningJobs}
        onChanged={async () => {
          await data.control.refetch();
        }}
        onInspectCampaign={(campaign, planningJob) => {
          setSelectedId(undefined);
          setSelectedCampaignId(campaign.id);
          setSelectedPlanningJobId(planningJob?.id);
        }}
        onInspectJob={(job) => {
          setSelectedCampaignId(job.campaign_id || undefined);
          setSelectedPlanningJobId(job.id);
        }}
        onInspectWorkItem={(workItemId) => {
          setSelectedCampaignId(undefined);
          setSelectedPlanningJobId(undefined);
          setSelectedId(workItemId);
        }}
        projects={projects}
      />

      <section aria-labelledby="work-items-title">
        <div className="automation-list-heading">
          <div>
            <p className="eyebrow">Laufende Arbeit</p>
            <h2 className="mt-1 text-xl font-semibold" id="work-items-title">
              Umsetzung &amp; PRs
            </h2>
          </div>
          <span className="text-xs text-muted-foreground">
            {visibleItems.length} von {items.length}
          </span>
        </div>

        <div className="automation-toolbar">
          <div aria-label="Umsetzung und PRs filtern" className="automation-filter" role="group">
            {filters.map((item) => (
              <button
                aria-pressed={filter === item.id}
                className="automation-filter-button"
                key={item.id}
                onClick={() => setFilter(item.id)}
                type="button"
              >
                {item.label}
              </button>
            ))}
          </div>
          <label className="automation-search">
            <Search className="size-4" />
            <span className="sr-only">Umsetzung durchsuchen</span>
            <Input
              className="h-auto border-0 bg-transparent px-0 shadow-none focus-visible:ring-0"
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Umsetzung durchsuchen"
              type="search"
              value={search}
            />
          </label>
        </div>

        {items.length === 0 ? (
          <EmptyState
            description={
              planningJobs.length
                ? "Sobald ein Plan freigegeben ist, erscheinen seine geplanten PRs hier."
                : "Beschreibe oben eine Idee. Anti-Gravity untersucht das Projekt und schlägt einen geordneten Plan vor."
            }
            title="Noch keine PRs in Umsetzung"
          />
        ) : visibleItems.length === 0 ? (
          <div className="automation-local-empty">
            Keine PRs passen zu Filter und Suche.
            <button
              onClick={() => {
                setFilter("all");
                setSearch("");
              }}
              type="button"
            >
              Filter zurücksetzen
            </button>
          </div>
        ) : (
          <WorkItemList items={visibleItems} onSelect={(item) => setSelectedId(item.id)} selectedId={selectedId} />
        )}
      </section>

      <AutomationDeployments deployments={data.control.data.deployments} />
      <AutomationMetrics metrics={data.control.data.flow_metrics ?? []} />

      <WorkItemDetail
        item={selectedItem}
        onChanged={async () => {
          await data.control.refetch();
        }}
        onOpenChange={(open) => {
          if (!open) setSelectedId(undefined);
        }}
        open={Boolean(selectedItem)}
        policy={data.control.data.policy}
      />
      <NewEndeavorDialog
        onCreated={async () => {
          await data.control.refetch();
        }}
        onOpenChange={setPlanningOpen}
        open={planningOpen}
        projects={projects}
      />
      <CampaignPlanDialog
        campaign={selectedCampaign}
        key={`${selectedCampaign?.id || "none"}:${selectedPlanningJob?.id || "none"}:${selectedPlanningJob?.active_question_id || "none"}`}
        onChanged={async () => {
          await data.control.refetch();
        }}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedCampaignId(undefined);
            setSelectedPlanningJobId(undefined);
          }
        }}
        open={Boolean(selectedCampaign)}
        planningJob={selectedPlanningJob}
        policy={data.control.data.policy}
      />
    </div>
  );
}
