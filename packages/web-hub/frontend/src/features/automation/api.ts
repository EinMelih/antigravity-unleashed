import { apiRequest } from "@/api/client";
import type {
  ControlActivationPolicy,
  ControlApproval,
  ControlCampaign,
  ControlCampaignReadiness,
  ControlEvidencePack,
  ControlIdeaSeed,
  ControlPlanAmendment,
  ControlPlanningQuestion,
  ControlPlanningDepth,
  ControlPlanningJob,
  ControlPolicy,
  ControlTaskGitHubSyncResult,
  ControlTaskMergeResult,
} from "@/api/contracts";

export interface CreatePlanningJobInput {
  project_id: number;
  wish: string;
  planning_depth: ControlPlanningDepth;
  max_candidates: number;
  activation_policy: ControlActivationPolicy;
  constraints: string[];
}

interface CampaignMutationRecord {
  id: string;
  project_id: number;
  title: string;
  status: string;
  version: number;
  base_sha: string;
  approved_version?: number | null;
  approved_sha: string;
  approved_by?: string;
}

function idempotencyKey(action: string) {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `${action}:${random}`.replace(/[^A-Za-z0-9._:-]+/g, "-").slice(0, 128);
}

function mutationHeaders(action: string) {
  return {
    "Content-Type": "application/json",
    "Idempotency-Key": idempotencyKey(action),
  };
}

export async function createPlanningJob(input: CreatePlanningJobInput) {
  const response = await apiRequest<{ planning_job: ControlPlanningJob }>(
    "/api/control-center/planning-jobs",
    {
      method: "POST",
      headers: mutationHeaders("planning-job-create"),
      body: JSON.stringify(input),
    },
  );
  return response.planning_job;
}

export async function retryPlanningJob(jobId: string) {
  const response = await apiRequest<{ planning_job: ControlPlanningJob }>(
    `/api/control-center/planning-jobs/${encodeURIComponent(jobId)}/retry`,
    {
      method: "POST",
      headers: mutationHeaders(`planning-job-retry:${jobId}`),
      body: "{}",
    },
  );
  return response.planning_job;
}

export async function stopPlanning(
  job: ControlPlanningJob,
  reason = "Planung im Anti-Gravity Hub beendet.",
) {
  const body = JSON.stringify({ actor: "human", reason });
  if (job.waiting_reason === "plan_approval" && job.campaign_id) {
    const response = await apiRequest<{ cancellation: Record<string, unknown> }>(
      `/api/control-center/campaigns/${encodeURIComponent(job.campaign_id)}/cancel`,
      {
        method: "POST",
        headers: mutationHeaders(`campaign-cancel:${job.campaign_id}`),
        body,
      },
    );
    return { target: "campaign" as const, ...response };
  }

  const response = await apiRequest<{ planning_job: ControlPlanningJob }>(
    `/api/control-center/planning-jobs/${encodeURIComponent(job.id)}/cancel`,
    {
      method: "POST",
      headers: mutationHeaders(`planning-job-cancel:${job.id}`),
      body,
    },
  );
  return { target: "planning_job" as const, ...response };
}

export function runControlExecutorOnce() {
  return apiRequest<{ executor: Record<string, unknown> }>(
    "/api/control-center/executor/tick",
    {
      method: "POST",
      headers: mutationHeaders("executor-tick"),
      body: "{}",
    },
  );
}

export async function getCampaignReadiness(campaignId: string) {
  const response = await apiRequest<{ readiness: ControlCampaignReadiness }>(
    `/api/control-center/campaigns/${encodeURIComponent(campaignId)}/readiness`,
  );
  return response.readiness;
}

export interface StartPlanAmendmentInput {
  reason: string;
  focus: {
    branches: string[];
    trigger?: { type: string; id: string };
    requested_change?: string;
    [key: string]: unknown;
  };
  expected_version: number;
  expected_base_sha: string;
  expected_plan_signature: string;
  expected_plan_signature_version: number;
}

export function startPlanAmendment(
  campaignId: string,
  input: StartPlanAmendmentInput,
) {
  return apiRequest<{
    amendment: ControlPlanAmendment;
    planning_job: ControlPlanningJob;
  }>(`/api/control-center/campaigns/${encodeURIComponent(campaignId)}/amendments`, {
    method: "POST",
    headers: mutationHeaders(
      `plan-amendment-start:${campaignId}:${input.expected_version}:${input.expected_plan_signature.slice(0, 16)}`,
    ),
    body: JSON.stringify({ ...input, actor: "human" }),
  });
}

export async function getPlanAmendment(amendmentId: string) {
  const response = await apiRequest<{ amendment: ControlPlanAmendment }>(
    `/api/control-center/amendments/${encodeURIComponent(amendmentId)}`,
  );
  return response.amendment;
}

export async function decidePlanAmendment(
  amendment: Pick<
    ControlPlanAmendment,
    | "id"
    | "from_version"
    | "before_plan_sha256"
    | "target_plan_sha256"
    | "patch_sha256"
  >,
  decision: "approved" | "rejected",
  reason: string,
) {
  const response = await apiRequest<{
    amendment: ControlPlanAmendment;
    campaign?: CampaignMutationRecord;
    planning_job?: ControlPlanningJob;
  }>(`/api/control-center/amendments/${encodeURIComponent(amendment.id)}/decision`, {
    method: "POST",
    headers: mutationHeaders(
      `plan-amendment-decide:${amendment.id}:${decision}:${amendment.target_plan_sha256 || "missing"}`,
    ),
    body: JSON.stringify({
      decision,
      expected_from_version: amendment.from_version,
      expected_before_plan_sha256: amendment.before_plan_sha256,
      expected_target_plan_sha256: amendment.target_plan_sha256,
      expected_patch_sha256: amendment.patch_sha256,
      actor: "human",
      reason,
    }),
  });
  return response;
}

export async function answerPlanningQuestion(questionId: string, answer: string) {
  return apiRequest<{
    question: ControlPlanningQuestion;
    planning_job?: ControlPlanningJob;
  }>(
    `/api/control-center/questions/${encodeURIComponent(questionId)}/answer`,
    {
      method: "POST",
      headers: mutationHeaders(`planning-question-answer:${questionId}`),
      body: JSON.stringify({ answer, status: "answered", answer_source: "human" }),
    },
  );
}

export async function approveCampaign(
  campaign: ControlCampaign,
  expectedPlanSignature: string,
) {
  const response = await apiRequest<{ campaign: CampaignMutationRecord }>(
    `/api/control-center/campaigns/${encodeURIComponent(campaign.id)}/approve`,
    {
      method: "POST",
      headers: mutationHeaders(
        `campaign-approve:${campaign.id}:${campaign.version}:${expectedPlanSignature}`,
      ),
      body: JSON.stringify({
        expected_version: campaign.version,
        approval_sha: campaign.base_sha,
        expected_plan_signature: expectedPlanSignature,
        actor: "human",
        reason: "Plan im Anti-Gravity Hub geprüft und freigegeben.",
      }),
    },
  );
  return response.campaign;
}

export async function updateControlPolicy(mode: "guided" | "campaign" | "autopilot") {
  const response = await apiRequest<{ policy: ControlPolicy }>(
    "/api/control-center/policy",
    {
      method: "POST",
      headers: mutationHeaders(`control-policy:${mode}`),
      body: JSON.stringify({
        mode,
        paused: false,
        actor: "human",
        reason: "Ausführungsart beim freigegebenen Campaign-Plan gewählt.",
      }),
    },
  );
  return response.policy;
}

export async function activateCampaignWave(campaignId: string) {
  const response = await apiRequest<{
    wave: {
      campaign_id: string;
      activated: Array<{ candidate_id: string; work_order_id: string; task_id: string }>;
      remaining_capacity?: number;
      reason?: string;
    };
  }>(`/api/control-center/campaigns/${encodeURIComponent(campaignId)}/activate-wave`, {
    method: "POST",
    headers: mutationHeaders(`campaign-wave:${campaignId}`),
    body: JSON.stringify({ actor: "human" }),
  });
  return response.wave;
}

export async function activateCandidate(
  candidateId: string,
  approvalSha: string,
  rationale: string,
) {
  const response = await apiRequest<{
    work_order: {
      id: string;
      candidate_id: string;
      status: string;
      approval_sha: string;
    };
  }>(`/api/control-center/pr-candidates/${encodeURIComponent(candidateId)}/activate`, {
    method: "POST",
    headers: mutationHeaders(`candidate-activate:${candidateId}:${approvalSha}`),
    body: JSON.stringify({
      approval_sha: approvalSha,
      actor: "human",
      rationale,
    }),
  });
  return response.work_order;
}

export async function cancelWorkOrder(workOrderId: string, reason: string) {
  const response = await apiRequest<{
    cancellation: {
      candidate_id: string;
      idempotent: boolean;
      task: Record<string, unknown>;
      work_order: Record<string, unknown>;
    };
  }>(`/api/control-center/work-orders/${encodeURIComponent(workOrderId)}/cancel`, {
    method: "POST",
    headers: mutationHeaders(`work-order-cancel:${workOrderId}`),
    body: JSON.stringify({ actor: "human", reason }),
  });
  return response.cancellation;
}

export async function syncTaskGitHub(taskId: string) {
  const response = await apiRequest<{ sync: ControlTaskGitHubSyncResult }>(
    `/api/control-center/tasks/${encodeURIComponent(taskId)}/github/sync`,
    {
      method: "POST",
      headers: mutationHeaders(`github-sync:${taskId}`),
      body: "{}",
    },
  );
  return response.sync;
}

export async function evaluateTaskEvidence(taskId: string) {
  const response = await apiRequest<{ evidence_pack: ControlEvidencePack }>(
    `/api/control-center/tasks/${encodeURIComponent(taskId)}/evidence/evaluate`,
    {
      method: "POST",
      headers: mutationHeaders(`evidence-evaluate:${taskId}`),
      body: "{}",
    },
  );
  return response.evidence_pack;
}

export interface RecordTaskApprovalInput {
  approval_type: "human_test" | "merge";
  decision: "approved" | "rejected";
  sha: string;
  reason: string;
  evidence?: HumanTestReproductionEvidence;
}

export interface HumanTestReproductionEvidence {
  executed_steps: string;
  expected_behavior: string;
  observed_behavior: string;
  environment: string;
  diagnosis?: string;
  artifact_ref?: string;
  note?: string;
}

export async function recordTaskApproval(
  taskId: string,
  input: RecordTaskApprovalInput,
) {
  const response = await apiRequest<{ approval: ControlApproval }>(
    `/api/control-center/tasks/${encodeURIComponent(taskId)}/approvals`,
    {
      method: "POST",
      headers: mutationHeaders(
        `task-approval:${taskId}:${input.approval_type}:${input.decision}`,
      ),
      body: JSON.stringify({ ...input, actor: "human" }),
    },
  );
  return response.approval;
}

export async function mergeTaskOnGitHub(taskId: string) {
  const response = await apiRequest<{ merge: ControlTaskMergeResult }>(
    `/api/control-center/tasks/${encodeURIComponent(taskId)}/github/merge`,
    {
      method: "POST",
      headers: mutationHeaders(`github-merge:${taskId}`),
      body: JSON.stringify({ actor: "human" }),
    },
  );
  return response.merge;
}

export async function listIdeaSeeds(projectId?: number) {
  const query = projectId == null ? "" : `?project_id=${encodeURIComponent(projectId)}`;
  const response = await apiRequest<{ idea_seeds: ControlIdeaSeed[] }>(
    `/api/control-center/idea-seeds${query}`,
  );
  return response.idea_seeds;
}

export async function getIdeaSeed(ideaSeedId: string) {
  const response = await apiRequest<{ idea_seed: ControlIdeaSeed }>(
    `/api/control-center/idea-seeds/${encodeURIComponent(ideaSeedId)}`,
  );
  return response.idea_seed;
}

export interface UpdateIdeaSeedInput {
  title?: string;
  note?: string;
  source?: string;
  provenance?: Record<string, unknown>;
}

export async function updateIdeaSeed(
  ideaSeedId: string,
  input: UpdateIdeaSeedInput,
) {
  const response = await apiRequest<{ idea_seed: ControlIdeaSeed }>(
    `/api/control-center/idea-seeds/${encodeURIComponent(ideaSeedId)}`,
    {
      method: "PATCH",
      headers: mutationHeaders(`idea-seed-update:${ideaSeedId}`),
      body: JSON.stringify({ actor: "human", ...input }),
    },
  );
  return response.idea_seed;
}

export interface DispositionIdeaSeedInput {
  disposition: "inbox" | "deferred" | "dismissed";
  reason: string;
}

export async function dispositionIdeaSeed(
  ideaSeedId: string,
  input: DispositionIdeaSeedInput,
) {
  const response = await apiRequest<{ idea_seed: ControlIdeaSeed }>(
    `/api/control-center/idea-seeds/${encodeURIComponent(ideaSeedId)}/disposition`,
    {
      method: "POST",
      headers: mutationHeaders(
        `idea-seed-disposition:${ideaSeedId}:${input.disposition}`,
      ),
      body: JSON.stringify({ actor: "human", ...input }),
    },
  );
  return response.idea_seed;
}

export interface PlanIdeaSeedInput {
  planning_depth: ControlPlanningDepth;
  max_candidates: number;
  activation_policy: ControlActivationPolicy;
  constraints: string[];
}

export async function planIdeaSeed(ideaSeedId: string, input: PlanIdeaSeedInput) {
  const response = await apiRequest<{ planning_job: ControlPlanningJob }>(
    `/api/control-center/idea-seeds/${encodeURIComponent(ideaSeedId)}/plan`,
    {
      method: "POST",
      headers: mutationHeaders(`idea-seed-plan:${ideaSeedId}`),
      body: JSON.stringify({ actor: "human", ...input }),
    },
  );
  return response.planning_job;
}
