export interface AntiGravityBackendHealth {
  connected: boolean;
  port: number | null;
}

export interface ControlPlaneHealth {
  mode: string;
  [key: string]: unknown;
}

export interface HubHealthResponse {
  status: string;
  hub: string;
  antigravity_backend: AntiGravityBackendHealth;
  web_ide: Record<string, unknown>;
  control_plane: ControlPlaneHealth;
}

export interface SystemServiceOverview {
  id: string;
  name: string;
  role: string;
  port: number;
  status: "healthy" | "attention" | "offline" | string;
  http_status: number | null;
  latency_ms: number | null;
}

export interface SystemRecordCount {
  table: string;
  label: string;
  count: number;
}

export interface SystemDatabaseOverview {
  engine: string;
  filename: string;
  size_bytes: number;
  table_count: number;
  journal_mode: string;
  schema_version: number;
  quick_check: string;
  foreign_key_violations: number;
  last_modified: string | null;
  record_counts: SystemRecordCount[];
  privacy: string;
}

export interface SystemDeploymentCheck {
  id: string;
  label: string;
  ready: boolean;
  detail: string;
}

export interface SystemOverviewResponse {
  status: "healthy" | "attention" | string;
  generated_at: string;
  services: SystemServiceOverview[];
  database: SystemDatabaseOverview;
  deployment: {
    model: string;
    containerized: boolean;
    runtime_verified: boolean;
    source_manifest_available: boolean;
    compose_service: string;
    network_mode: string;
    checks: SystemDeploymentCheck[];
    configured: boolean;
  };
  runtime: {
    hub_version: string;
    build_sha: string;
    python_version: string;
    platform: string;
    architecture: string;
    cpu_count: number | null;
    uptime_seconds: number;
    watchdog_retention_days: number;
    api_content_logging: boolean;
    control_mode: string;
    paused: boolean;
  };
  integrations: {
    antigravity: {
      connected: boolean;
      port: number | null;
      latency_ms: number | null;
    };
    web_ide: {
      running: boolean;
      port: number;
    };
  };
}

export interface Lesson {
  id: number;
  project_id: number | null;
  issue_id: number | null;
  technique: string;
  solution: string;
  created_at: string;
}

export interface LessonsResponse {
  lessons: Lesson[];
}

export type ControlKnowledgeCoverageState =
  | "present"
  | "missing"
  | "not_required"
  | "pending"
  | string;

export interface ControlKnowledgeProjectSummary {
  id: number;
  name: string;
}

export interface ControlKnowledgeIdeaSeedSummary {
  id: string;
  project_id?: number;
  title: string;
  status: string;
  source: string;
  created_at: string;
}

export interface ControlKnowledgeCampaignSummary {
  id: string;
  title: string;
  status: string;
  version: number;
  base_sha: string;
  plan_signature: string;
}

export interface ControlKnowledgeArtifactSummary {
  id: string;
  artifact_type: string;
  title: string;
  status: string;
  version: number;
  relative_path: string;
  content_sha256: string;
  materialization_status: ControlKnowledgeCoverageState;
  materialized_sha256: string | null;
  materialized_commit_sha: string | null;
  materialized_at: string | null;
}

export interface ControlKnowledgeUnlinkedArtifact extends ControlKnowledgeArtifactSummary {
  project_id: number;
  campaign_id: string | null;
}

export interface ControlKnowledgeArtifactRelation {
  source_artifact_id: string;
  target_artifact_id: string;
  relation_type: string;
}

export interface ControlKnowledgeCandidateSummary {
  id: string;
  campaign_id?: string;
  title: string;
  status: string;
  priority: number;
  base_sha: string;
}

export interface ControlKnowledgeTaskSummary {
  id: string;
  status: string;
  issue_number: number | null;
  issue_url: string;
  pr_number: number | null;
  pr_url: string;
  current_sha: string;
  merged_sha: string;
}

export interface ControlKnowledgeEvidenceSummary {
  id: string;
  status: string;
  sha: string;
  summary: string;
}

export interface ControlKnowledgeDeploymentSummary {
  id: string;
  environment: string;
  status: string;
  sha: string;
  artifact_ref: string;
  previous_stable_sha: string;
  rollback_of: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface ControlKnowledgeBranch {
  candidate: ControlKnowledgeCandidateSummary;
  artifacts: ControlKnowledgeArtifactSummary[];
  task: ControlKnowledgeTaskSummary | null;
  evidence: ControlKnowledgeEvidenceSummary | null;
  deployments: ControlKnowledgeDeploymentSummary[];
}

export interface ControlKnowledgeCoverage {
  idea_group_files: number;
  linked_artifacts: number;
  unlinked_artifacts: number;
  linked_candidates: number;
  unlinked_candidates: number;
}

export interface ControlKnowledgeChain {
  project: ControlKnowledgeProjectSummary;
  idea_seed: ControlKnowledgeIdeaSeedSummary | null;
  campaign: ControlKnowledgeCampaignSummary | null;
  idea_group: ControlKnowledgeArtifactSummary[];
  artifacts: ControlKnowledgeArtifactSummary[];
  relations: ControlKnowledgeArtifactRelation[];
  branches: ControlKnowledgeBranch[];
  coverage: ControlKnowledgeCoverage;
}

export interface ControlKnowledgeChainsResponse {
  chains: ControlKnowledgeChain[];
  unlinked: {
    idea_seeds: ControlKnowledgeIdeaSeedSummary[];
    artifacts: ControlKnowledgeUnlinkedArtifact[];
    candidates: ControlKnowledgeCandidateSummary[];
  };
}

export interface GitHubStatusResponse {
  configured: boolean;
  valid: boolean;
  status: "missing" | "valid" | "invalid" | "rate_limited" | string;
  owner: string;
  login?: string;
  projects_base_dir: string;
  error: string;
}

export interface CustomModel {
  id: number;
  name: string;
  base_url: string;
  model_id: string;
  api_key_header: string;
  api_key_prefix: string;
  extra_headers: Record<string, string | null>;
  system_prompt: string;
  temperature: number;
  verify_tls: boolean;
  timeout_seconds: number;
  has_api_key: boolean;
}

export interface CustomModelsResponse {
  models: CustomModel[];
}

export interface CustomModelInput extends Omit<CustomModel, "id" | "has_api_key" | "extra_headers"> {
  id?: number;
  api_key?: string;
  extra_headers: string;
}

export interface CodexStatus {
  available: boolean;
  running: boolean;
  authenticated: boolean;
  requires_openai_auth: boolean;
  account_type?: string | null;
  plan_type?: string | null;
}

export interface CodexReasoningEffort {
  value: string;
  description?: string;
}

export interface CodexModel {
  id: string;
  model: string;
  display_name: string;
  description?: string;
  hidden: boolean;
  supported_reasoning_efforts: CodexReasoningEffort[];
  default_reasoning_effort?: string;
  input_modalities?: string[];
  is_default?: boolean;
}

export interface ControlPolicy {
  mode: string;
  paused: boolean;
}

export interface ControlSummary {
  attention_open: number;
  recommendations_open: number;
  campaigns_open: number;
  work_orders_approved: number;
  tasks_active: number;
  tasks_waiting_human: number;
  human_gates_open: number;
  deployments_active: number;
  webhooks_pending: number;
  planning_jobs_active: number;
}

export type ControlFlowMetricUnit = "percent" | "count";

export interface ControlFlowMetric {
  key:
    | "planning_outcomes"
    | "campaign_progress"
    | "task_progress"
    | "human_questions"
    | "repair_reopen_events"
    | "plan_amendments"
    | "deployment_rollbacks";
  label: string;
  description: string;
  value: number | null;
  unit: ControlFlowMetricUnit;
  numerator: number;
  denominator: number;
  sample_size: number;
  breakdown: Record<string, number>;
}

export interface ControlAttentionItem {
  id: string;
  project_id: number;
  category: string;
  entity_type: string;
  entity_id: string;
  title: string;
  consequence: string;
  recommendation: string;
  urgency: "critical" | "high" | "normal" | string;
  status: string;
  created_at?: string;
}

export interface ControlTask {
  id: string;
  project_id: number;
  campaign_id: string;
  candidate_id: string;
  role: string;
  status: string;
  wake_reason: string;
  base_sha: string;
  current_sha: string;
  merged_sha: string;
  branch_name: string;
  worktree_path: string;
  antigravity_chat_id: string;
  issue_number: number | null;
  issue_url: string;
  pr_number: number | null;
  pr_url: string;
  attempt: number;
  started_at?: string | null;
  finished_at?: string | null;
  last_error: string;
  updated_at?: string;
  agent_gate?: ControlAttentionItem | null;
}

export interface ControlChecklistItem {
  key: string;
  text: string;
}

export interface ControlEvidencePack {
  id: string;
  task_id: string;
  project_id: number;
  candidate_id: string;
  sha: string;
  status: string;
  summary: string;
  preview_url: string;
  rollback_plan: string;
  risk: Record<string, unknown>;
  test_pack: {
    acceptance_criteria?: ControlChecklistItem[];
    required_checks?: ControlChecklistItem[];
    manual_tests?: ControlChecklistItem[];
    missing?: string[];
    failed?: string[];
    blocking_findings?: unknown[];
    sha?: string;
  };
  updated_at?: string;
}

export interface ControlDeployment {
  id: string;
  task_id: string | null;
  project_id: number;
  environment: string;
  status: string;
  sha: string;
  artifact_ref: string;
  preview_url?: string;
  previous_stable_sha: string;
  migration: unknown;
  logs: unknown;
  health: unknown;
  approved_by: string;
  rollback_of: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ControlFinding {
  id: string;
  task_id: string;
  classification: string;
  source: string;
  body: string;
  status: string;
  resolution: string;
  sha: string;
  created_at?: string;
}

export interface ControlApproval {
  id: string;
  approval_type: "protected_path" | "human_test" | "merge" | "production";
  decision: "approved" | "rejected";
  sha: string;
  actor?: string;
  reason?: string;
  revoked_at?: string | null;
  created_at?: string;
}

export interface ControlTaskGitHubSyncResult {
  task: ControlTask;
  evidence_pack: ControlEvidencePack;
  terminal_noop?: boolean;
  remote_reconciled?: string;
  campaign_completed?: boolean;
  stale_sync_ignored?: boolean;
}

export interface ControlTaskMergeResult {
  task: ControlTask;
  merge: {
    sha: string;
    merged: boolean;
    message: string;
  };
  campaign_completed: boolean;
  issue_close_warning: string;
}

export interface ControlCandidateContract {
  purpose: string;
  expected_diff_type: string;
  reversibility: string;
  migration_plan: string;
  compatibility_plan: string;
  definition_of_done: string;
  estimated_size: string;
  components: string[];
  required_checks: string[];
  manual_tests: string[];
  documentation: string[];
  wave?: number;
  ready_score?: number;
  paused?: number | boolean;
  pinned?: number | boolean;
}

export interface ControlCandidateConflict {
  candidate_id: string;
  conflicts_with_id: string;
  reason: string;
  resources: string[];
  created_at?: string;
}

export interface ControlPrCandidate {
  id: string;
  campaign_id: string;
  title: string;
  scope: string;
  non_goals: string;
  risk_level: string;
  priority: number;
  status: string;
  base_sha: string;
  acceptance_criteria: string[];
  depends_on: string[];
  conflicts?: ControlCandidateConflict[];
  work_order: {
    id: string;
    status: string;
    rationale: string;
    approval_sha: string;
  } | null;
  contract: ControlCandidateContract | null;
  task: ControlTask | null;
  evidence_pack: ControlEvidencePack | null;
  findings: ControlFinding[];
  approvals: ControlApproval[];
  created_at?: string;
  updated_at?: string;
}

export interface ControlCampaignProfile {
  campaign_id?: string;
  slug?: string;
  planning_depth: ControlPlanningDepth;
  requested_max_candidates: number;
  activation_policy: ControlActivationPolicy;
  readiness_status?: string;
  readiness_score?: number;
  plan_signature?: string;
  pivotal_fork?: string;
  success_metrics?: string[];
  constraints?: string[];
  assumptions?: string[];
  acceptance_matrix?: string[];
  rollout_plan?: string;
  rollback_plan?: string;
  current_wave?: number;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at?: string;
}

export interface ControlPlanningQuestion {
  id: string;
  campaign_id: string;
  branch: string;
  question: string;
  rationale: string;
  answer: string;
  answer_source: string;
  status: string;
  owner: string;
  evidence: Record<string, unknown>;
  contradiction_of?: string | null;
  resolved_in_version?: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface ControlArtifact {
  id: string;
  project_id: number;
  campaign_id: string | null;
  artifact_type: string;
  slug: string;
  title: string;
  status: string;
  version: number;
  supersedes_id?: string | null;
  relative_path: string;
  content_text: string;
  content_sha256: string;
  metadata: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export interface ControlPlanAmendment {
  id: string;
  campaign_id: string;
  from_version: number;
  proposed_version: number;
  reason: string;
  impact: Record<string, unknown>;
  status: string;
  proposed_by: string;
  approved_by: string;
  approved_sha: string;
  prior_campaign_status?: "approved" | "active" | "paused" | string;
  from_base_sha?: string;
  planning_base_sha?: string;
  from_plan_signature?: string;
  from_signature_version?: number;
  before_plan_sha256?: string;
  target_plan_sha256?: string;
  patch_sha256?: string;
  focus?: Record<string, unknown>;
  target_plan?: Record<string, unknown>;
  patch?: ControlPlanAmendmentPatch;
  validation?: ControlPlanAmendmentValidation;
  decision_reason?: string;
  resolved_by?: string;
  planning_job_id?: string | null;
  created_at?: string;
  updated_at?: string;
  resolved_at?: string | null;
}

export interface ControlPlanAmendmentCandidateChange {
  id: string;
  title?: string;
  fields?: string[];
}

export interface ControlPlanAmendmentRelationChange {
  source_kind: "idea_seed" | "artifact" | "candidate" | string;
  source_id: string;
  target_kind: "artifact" | string;
  target_id: string;
  relation_type: string;
}

export interface ControlPlanAmendmentPatch {
  campaign?: { set?: Record<string, unknown> };
  profile?: { set?: Record<string, unknown> };
  ledger?: { add?: Array<Record<string, unknown>> };
  artifacts?: {
    add?: Array<{ id: string; title?: string; artifact_type?: string }>;
    supersede?: Array<{ id: string; title?: string; supersedes_artifact_id?: string }>;
  };
  candidates?: {
    add?: ControlPlanAmendmentCandidateChange[];
    update?: ControlPlanAmendmentCandidateChange[];
    retire?: Array<ControlPlanAmendmentCandidateChange | string>;
  };
  dependencies?: { replace_for_mutable?: Array<Record<string, unknown>> };
  conflicts?: { replace_for_mutable?: Array<Record<string, unknown>> };
  knowledge_relations?: {
    add?: ControlPlanAmendmentRelationChange[];
    remove?: ControlPlanAmendmentRelationChange[];
  };
}

export interface ControlPlanAmendmentValidation {
  ready?: boolean;
  gates?: ControlCampaignReadinessGate[];
  mutable_candidate_ids?: string[];
  immutable_candidate_ids?: string[];
  warnings?: string[];
}

export interface ControlCampaign {
  id: string;
  project_id: number;
  title: string;
  goal: string;
  non_goals: string;
  risk_level: string;
  status: string;
  version: number;
  base_sha: string;
  approved_sha: string;
  approved_version?: number | null;
  approved_by?: string;
  pr_candidates: ControlPrCandidate[];
  profile?: ControlCampaignProfile | null;
  questions?: ControlPlanningQuestion[];
  artifacts?: ControlArtifact[];
  amendments?: ControlPlanAmendment[];
  created_at?: string;
  updated_at?: string;
}

export type ControlPlanningDepth = "compact" | "balanced" | "deep" | "exhaustive";

export type ControlActivationPolicy = "per_candidate" | "campaign_wave" | "autopilot";

export type ControlIdeaSeedStatus =
  | "inbox"
  | "deferred"
  | "dismissed"
  | "planning"
  | "planned";

export interface ControlIdeaSeed {
  id: string;
  project_id: number;
  title: string;
  note: string;
  source: string;
  status: ControlIdeaSeedStatus;
  provenance: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ControlPlanningJob {
  id: string;
  project_id: number;
  idea_seed_id: string | null;
  job_type?: "initial_plan" | "plan_amendment" | string;
  amendment_id?: string | null;
  status: "queued" | "running" | "waiting_human" | "failed" | "cancelled" | string;
  planning_depth: ControlPlanningDepth;
  max_candidates: number;
  activation_policy: ControlActivationPolicy;
  wish: string;
  constraints: string[];
  antigravity_chat_id: string;
  campaign_id: string | null;
  waiting_reason: "" | "question" | "plan_approval" | "amendment_approval";
  active_question_id: string | null;
  round_number: number;
  attempt: number;
  output: Record<string, unknown>;
  last_error: string;
  created_by: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
  agent_gate?: ControlAttentionItem | null;
}

export interface ControlCampaignWave {
  wave: number;
  candidate_ids: string[];
  parallel_count: number;
}

export interface ControlCampaignSimulation {
  campaign_id: string;
  acyclic: boolean;
  candidate_count: number;
  topological_order: string[];
  waves: ControlCampaignWave[];
  dependencies: Record<string, string[]>;
  conflicts: ControlCandidateConflict[];
  max_wave: number;
}

export interface ControlCampaignReadinessGate {
  key: string;
  passed: boolean;
  missing: string[];
  evidence: string[];
}

export interface ControlCampaignReadiness {
  campaign_id: string;
  ready: boolean;
  status: string;
  score: number;
  missing: string[];
  gates?: ControlCampaignReadinessGate[];
  plan_signature: string;
  plan_signature_version?: number;
  simulation: ControlCampaignSimulation | null;
  grandfathered_approval?: boolean;
}

export interface ControlAuditEvent {
  id: number;
  project_id: number | null;
  entity_type: string;
  entity_id: string;
  action: string;
  actor: string;
  from_state: string;
  to_state: string;
  reason: string;
  evidence: Record<string, unknown>;
  created_at: string;
}

export interface ControlCheckpoint {
  id: string;
  project_id: number;
  entity_type: string;
  entity_id: string;
  actor: string;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ControlOverviewResponse {
  policy: ControlPolicy;
  summary: ControlSummary;
  attention: ControlAttentionItem[];
  tasks: ControlTask[];
  recommendations: unknown[];
  campaigns: ControlCampaign[];
  planning_jobs: ControlPlanningJob[];
  deployments: ControlDeployment[];
  metrics: unknown[];
  flow_metrics?: ControlFlowMetric[];
  checkpoints: ControlCheckpoint[];
  audit: ControlAuditEvent[];
}

export interface ConversationCounts {
  running: number;
  complete: number;
  archived: number;
  [key: string]: number;
}

export interface ActiveConversationAgent {
  convo_id: string;
  title: string;
  project_name?: string;
  repository_name?: string;
  status?: string;
}

export interface ConversationSummaryResponse {
  conversations: [];
  counts: ConversationCounts;
  active_agents: ActiveConversationAgent[];
  filters: Record<string, unknown>;
}

export interface WorkerCapacity {
  active: number;
  maximum: number;
  minimum_warm: number;
  queued: number;
  idle_ttl_seconds: number;
}

export interface WorkerSnapshot {
  target_id: string;
  window_id: string | null;
  state: string;
  detail: string;
  chat_id: string | null;
  loaded_chat_id?: string | null;
  reserved?: boolean;
  purpose?: string;
  composer_visible?: boolean;
  focused?: boolean;
  has_draft?: boolean;
  updated_at?: number | null;
  last_used_at?: number | null;
  error?: string;
  chat?: ActiveConversationAgent;
}

export interface WorkersResponse {
  success: boolean;
  primary: WorkerSnapshot | null;
  workers: WorkerSnapshot[];
  capacity: WorkerCapacity;
}

export type AntigravityConnection = "online" | "degraded" | "offline";
export type AntigravityInstanceRole = "primary" | "worker" | "dictation";
export type AntigravityInstanceAvailability = "online" | "unreachable";
export type AntigravityInstanceActivity =
  | "manual"
  | "idle"
  | "preparing"
  | "sending"
  | "working"
  | "waiting_human"
  | "error"
  | "unknown";
export type AntigravityBindingStatus = "confirmed" | "mismatch" | "none";

export interface AntigravityInstanceConversation {
  conversation_id: string;
  title?: string | null;
  status?: string | null;
  kind?: string | null;
  project_name?: string | null;
  repository_name?: string | null;
}

export interface AntigravityInstance {
  instance_ref: string;
  instance_id: string;
  role: AntigravityInstanceRole;
  availability: AntigravityInstanceAvailability;
  activity: AntigravityInstanceActivity;
  detail_code: string;
  conversation: AntigravityInstanceConversation | null;
  binding_status: AntigravityBindingStatus;
  focused: boolean;
  has_draft: boolean;
  can_close: boolean;
  can_focus: boolean;
  can_snap: boolean;
  updated_at?: number | null;
}

export interface AntigravityInstanceCapacity {
  open_workers: number;
  busy_workers: number;
  idle_workers: number;
  maximum_workers: number;
  queued: number;
}

export interface AntigravityInstancesResponse {
  connection: AntigravityConnection;
  observed_at: string;
  revision: string;
  stale: boolean;
  instances: AntigravityInstance[];
  capacity: AntigravityInstanceCapacity;
}

export interface HubProject {
  id: number;
  name: string;
  path: string;
  github_url: string;
  github_owner: string;
  github_repo: string;
  default_branch: string;
  git_branch: string;
  source_kind: string;
  github_bootstrap_required: boolean;
  github_bootstrap_status: string;
  github_setup_error?: string;
  antigravity_linked: boolean;
  antigravity_project_name: string;
  integrity_project_uuid?: string;
  integrity_workspace_path?: string;
  created_at?: string;
}

export interface ProjectsResponse {
  projects: HubProject[];
}

export interface ProjectDependencyCount {
  total: number;
  active?: number;
  open?: number;
  with_pull_request?: number;
  with_native_chat?: number;
}

export interface ProjectRemovalImpact {
  project: {
    id: number;
    name: string;
    archived: boolean;
    github_repository: {
      linked: boolean;
      full_name: string;
    };
  };
  dependencies: Record<string, ProjectDependencyCount>;
  retention: Record<string, string>;
  remote_repository_deletion: {
    supported: boolean;
    separate_confirmation_required: boolean;
    required_identity: string;
    required_permission: string;
  };
}

export interface ProjectArchiveResponse {
  success: boolean;
  archived: boolean;
  already_archived: boolean;
  project: { id: number; name: string; archived_at: string | null };
  transitions: Record<string, number>;
  retention: Record<string, string>;
}

export interface GitHubRepository {
  id: number;
  name: string;
  full_name: string;
  owner: string;
  html_url: string;
  clone_url: string;
  description: string;
  private: boolean;
  default_branch: string;
  updated_at: string;
  imported: boolean;
  project_id?: number;
  suggested_local_path: string;
}

export interface GitHubRepositoriesResponse {
  repositories: GitHubRepository[];
}

export interface CreateHubProjectInput {
  name: string;
  path?: string;
  test_command?: string;
  create_github: boolean;
  github_visibility?: "private" | "public";
}

export interface ImportGitHubProjectInput {
  full_name: string;
  path?: string;
}

export interface AntiGravityProjectLinkResponse {
  success: boolean;
  project_id: number;
  antigravity_project_id?: string;
  antigravity_project_name: string;
}

export interface ConversationCatalogItem {
  convo_id: string;
  title: string;
  workspace_path: string;
  project_uuid: string;
  project_name: string;
  repository_name: string;
  conversation_type: "normal" | "project" | string;
  archived: boolean;
  status: "running" | "complete" | string;
  status_code?: number;
  step_count: number;
  created_at: number;
  updated_at: number;
  source: "antigravity" | "custom" | string;
  visible_in_sidebar: boolean;
  sidebar_position: number | null;
}

export interface ConversationCatalogResponse {
  conversations: ConversationCatalogItem[];
  active_agents: ActiveConversationAgent[];
  counts: ConversationCounts & {
    all: number;
    visible: number;
    normal: number;
    project: number;
  };
  visible_conversation_ids: string[];
  archived_conversation_ids: string[];
  filters: Record<string, unknown>;
  sidebar: {
    available: boolean;
    stale: boolean;
    count: number;
    active_id: string | null;
    error?: string | null;
  };
}

export interface ChatAttachment {
  name?: string;
  file_name?: string;
  type?: string;
  data?: string;
  file_path?: string;
}

export interface ChatHistoryEntry {
  idx: number;
  type: "message" | "tool_call" | "tool_output" | string;
  role?: "user" | "assistant" | string;
  content?: string | null;
  thinking?: string | null;
  attachments?: ChatAttachment[];
  tool_name?: string;
  args?: string | Record<string, unknown>;
  output?: unknown;
  status?: number | string;
  state?: string;
  is_running?: boolean;
  is_terminal?: boolean;
  complete?: boolean;
  started_at?: number;
  finished_at?: number;
  duration_ms?: number;
  enriched?: Record<string, unknown>;
  model_name?: string | null;
  source?: string;
}

export interface ChatHistoryResponse {
  history: ChatHistoryEntry[];
  max_idx: number;
}

export interface ModelCatalogItem {
  label: string;
  badge?: string;
  source: "official" | "custom" | string;
  selection_id?: string;
  custom_model_id?: number;
  model_id?: string;
  default_reasoning_effort?: string;
  supported_reasoning_efforts?: string[];
}

export interface ModelCatalogResponse {
  models: ModelCatalogItem[];
  current?: string;
  source?: string;
  stale?: boolean;
  native_error?: string;
}

export interface ActiveModelResponse {
  model: string | null;
  source: string;
  confirmed: boolean;
  selection_id?: string;
  custom_model_id?: number;
  model_id?: string;
  reasoning_effort?: string;
  window_id?: string | null;
}

export interface ChatDeliveryResponse {
  success: boolean;
  verified?: boolean;
  accepted?: boolean;
  pending_verification?: boolean;
  convo_id?: string;
  conversation_id: string;
  verified_idx?: number;
  window?: {
    window_id?: string;
    [key: string]: unknown;
  };
}

export interface AntiGravityProject {
  id: string;
  name: string;
  display_name: string;
  workspace_path?: string;
  project_uuid?: string;
}

export interface AntiGravityProjectsResponse {
  projects: AntiGravityProject[];
}

export interface ScheduledTask {
  id: string;
  name: string;
  schedule: string;
  command: string[];
  prompt: string;
  enabled: boolean;
  project_id: string;
  all_projects: boolean;
  status_code: number;
  last_error: string;
  start_time_ms: string;
  is_bundled: boolean;
}

export interface ScheduledTasksResponse {
  connected: boolean;
  tasks: ScheduledTask[];
  count: number;
}

export interface ScheduledTaskEventsResponse {
  task_id: string;
  events: Array<Record<string, unknown>>;
}

export interface ScheduledTaskInput {
  name: string;
  schedule: string;
  prompt: string;
  project_id: string;
  all_projects: boolean;
  enabled: boolean;
}

export interface ProjectRuntimeServiceConfig {
  name: string;
  enabled: boolean;
  command: string;
  cwd: string;
  host: string;
  port: number;
  health_path: string;
  detected: boolean;
  reason: string;
}

export interface ProjectRuntimeProfile {
  version: number;
  project_id: number;
  detected_at?: number;
  updated_at?: number;
  services: {
    frontend: ProjectRuntimeServiceConfig;
    backend: ProjectRuntimeServiceConfig;
  };
}

export interface ProjectRuntimeServiceStatus {
  service: "frontend" | "backend";
  active: boolean;
  managed: boolean;
  status: "running" | "starting" | "stopped" | "external" | string;
  url: string;
  pid: number | null;
  started_at: number | null;
  config: ProjectRuntimeServiceConfig;
  log: string;
  setup?: {
    required: boolean;
    command: string;
    reason: string;
  };
  unchanged?: boolean;
  message?: string;
}

export interface ProjectRuntimeSnapshot {
  project_id: number;
  configured: boolean;
  profile: ProjectRuntimeProfile;
  services: {
    frontend: ProjectRuntimeServiceStatus;
    backend: ProjectRuntimeServiceStatus;
  };
  storage_path: string;
}

export interface ProjectScreenshotResponse {
  success: boolean;
  captured_at: number;
  path: string;
  url: string;
}

export interface ProjectIdeResponse {
  success: boolean;
  url: string;
  workspace: {
    kind: string;
    project_id: number;
    path: string;
  };
  ide: Record<string, unknown>;
}

export interface ProjectStackTechnology {
  id?: string;
  name?: string;
  category?: string;
  evidence?: string[];
}

export interface ProjectStackManifest {
  path?: string;
  kind?: string;
  ecosystem?: string;
  status?: "parsed" | "invalid" | "skipped" | string;
  dependency_count?: number;
  dev_dependency_count?: number;
  reason?: "parse_error" | "size_limit" | string;
}

export interface ProjectStackDockerStage {
  name?: string | null;
  base_image?: string;
}

export interface ProjectStackDockerfile {
  path?: string;
  status?: "parsed" | "invalid" | "skipped" | string;
  stages?: ProjectStackDockerStage[];
  base_images?: string[];
  exposed_ports?: string[];
  healthcheck?: "configured" | "none" | "absent" | string;
  reason?: string;
}

export interface ProjectStackComposeBuild {
  context?: string | null;
  external?: boolean;
}

export interface ProjectStackComposeVolume {
  source?: string;
  target?: string;
  type?: "bind" | "volume" | "anonymous" | string;
  external?: boolean;
}

export interface ProjectStackComposeService {
  name?: string;
  image?: string | null;
  build?: ProjectStackComposeBuild | null;
  ports?: string[];
  volumes?: ProjectStackComposeVolume[];
  depends_on?: string[];
  healthcheck?: boolean;
}

export interface ProjectStackComposeFile {
  path?: string;
  status?: "parsed" | "invalid" | "skipped" | string;
  services?: ProjectStackComposeService[];
  named_volumes?: string[];
  networks?: string[];
  reason?: string;
}

export interface ProjectStackDatabaseTable {
  name?: string;
  row_count?: number | null;
  count_status?: "ok" | "limited" | "unavailable" | string;
}

export interface ProjectStackDatabase {
  path?: string;
  size_bytes?: number;
  status?: "ok" | "invalid" | "skipped" | "unavailable" | string;
  quick_check?: "ok" | "failed" | "limited" | "unavailable" | string;
  table_count?: number | null;
  tables?: ProjectStackDatabaseTable[];
  tables_truncated?: boolean;
  reason?: string;
}

export interface ProjectStackProcess {
  id?: string;
  name?: string;
  kind?: string;
  status?: string;
  port?: number | string | null;
  health?: string;
}

export interface ProjectStackTopologyNode {
  id?: string;
  label?: string;
  kind?: string;
  status?: string;
  port?: number | string | null;
}

export interface ProjectStackTopologyEdge {
  source?: string;
  target?: string;
  label?: string;
}

export interface ProjectStackResponse {
  project?: {
    id?: number;
    name?: string;
  };
  technologies?: ProjectStackTechnology[];
  database_drivers?: ProjectStackTechnology[];
  manifests?: ProjectStackManifest[];
  docker?: {
    dockerfiles?: ProjectStackDockerfile[];
    compose_files?: ProjectStackComposeFile[];
  };
  databases?: ProjectStackDatabase[];
  scan?: {
    read_only?: boolean;
    truncated?: boolean;
    files_considered?: number;
    limits?: {
      max_depth?: number;
      max_files?: number;
      max_manifest_bytes?: number;
      max_sqlite_files?: number;
      max_sqlite_bytes?: number;
      max_tables_per_database?: number;
    };
  };
  privacy?: {
    notice?: string;
    guarantees?: string[];
  };
  processes?: ProjectStackProcess[];
  topology?: {
    nodes?: ProjectStackTopologyNode[];
    edges?: ProjectStackTopologyEdge[];
  };
}
