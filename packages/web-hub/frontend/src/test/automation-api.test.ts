import { afterEach, describe, expect, it, vi } from "vitest";

import type { ControlPlanningJob } from "@/api/contracts";
import {
  answerPlanningQuestion,
  approveCampaign,
  createPlanningJob,
  decidePlanAmendment,
  evaluateTaskEvidence,
  getPlanAmendment,
  mergeTaskOnGitHub,
  recordTaskApproval,
  startPlanAmendment,
  stopPlanning,
  syncTaskGitHub,
} from "@/features/automation/api";

describe("automation planning API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates an idempotent planning job with the complete planning contract", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ planning_job: { id: "PLAN-1" } }), {
        headers: { "content-type": "application/json" },
        status: 202,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      createPlanningJob({
        project_id: 52,
        wish: "Build an accessible project search.",
        planning_depth: "deep",
        max_candidates: 30,
        activation_policy: "campaign_wave",
        constraints: ["Keep the API compatible"],
      }),
    ).resolves.toMatchObject({ id: "PLAN-1" });

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(path).toBe("/api/control-center/planning-jobs");
    expect(init.method).toBe("POST");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Idempotency-Key")).toMatch(/^planning-job-create:/);
    expect(JSON.parse(String(init.body))).toEqual({
      project_id: 52,
      wish: "Build an accessible project search.",
      planning_depth: "deep",
      max_candidates: 30,
      activation_policy: "campaign_wave",
      constraints: ["Keep the API compatible"],
    });
  });

  it("returns the answered question together with the requeued planning job", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          question: { id: "Q-1", status: "answered" },
          planning_job: { id: "PLAN-1", status: "queued" },
        }),
        { headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(answerPlanningQuestion("Q/1", "Bitte Variante B verwenden.")).resolves.toEqual({
      question: { id: "Q-1", status: "answered" },
      planning_job: { id: "PLAN-1", status: "queued" },
    });

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/control-center/questions/Q%2F1/answer");
    expect(JSON.parse(String(init.body))).toEqual({
      answer: "Bitte Variante B verwenden.",
      status: "answered",
      answer_source: "human",
    });
  });

  it("approves exactly the plan signature shown to the human", async () => {
    const signature = "c".repeat(64);
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ campaign: { id: "CMP-1", status: "approved" } }),
        { headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const campaign = {
      id: "CMP/1",
      version: 7,
      base_sha: "a".repeat(40),
    } as Parameters<typeof approveCampaign>[0];

    await approveCampaign(campaign, signature);

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/control-center/campaigns/CMP%2F1/approve");
    expect(new Headers(init.headers).get("Idempotency-Key")).toContain(signature);
    expect(JSON.parse(String(init.body))).toMatchObject({
      expected_version: 7,
      approval_sha: "a".repeat(40),
      expected_plan_signature: signature,
    });
  });

  it("loads an amendment and decides exactly the reviewed target", async () => {
    const amendment = {
      id: "AMD/1",
      campaign_id: "CMP-1",
      from_version: 7,
      proposed_version: 8,
      reason: "Neue Repository-Erkenntnis",
      impact: {},
      status: "review",
      proposed_by: "agent",
      approved_by: "",
      approved_sha: "",
      prior_campaign_status: "active",
      from_base_sha: "a".repeat(40),
      planning_base_sha: "b".repeat(40),
      from_plan_signature: "c".repeat(64),
      from_signature_version: 2,
      before_plan_sha256: "d".repeat(64),
      target_plan_sha256: "e".repeat(64),
      patch_sha256: "f".repeat(64),
      focus: {},
      target_plan: {},
      patch: {},
      validation: {},
    } as const;
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ amendment }), {
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ amendment: { ...amendment, status: "approved" } }), {
          headers: { "content-type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getPlanAmendment("AMD/1")).resolves.toMatchObject({ id: "AMD/1" });
    await decidePlanAmendment(amendment, "approved", "Zielplan geprüft.");

    const [getPath] = fetchMock.mock.calls[0] as [string, RequestInit];
    const [decisionPath, decisionInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(getPath).toBe("/api/control-center/amendments/AMD%2F1");
    expect(decisionPath).toBe("/api/control-center/amendments/AMD%2F1/decision");
    expect(new Headers(decisionInit.headers).get("Idempotency-Key")).toContain(
      amendment.target_plan_sha256,
    );
    expect(JSON.parse(String(decisionInit.body))).toEqual({
      decision: "approved",
      expected_from_version: 7,
      expected_before_plan_sha256: amendment.before_plan_sha256,
      expected_target_plan_sha256: amendment.target_plan_sha256,
      expected_patch_sha256: amendment.patch_sha256,
      actor: "human",
      reason: "Zielplan geprüft.",
    });
  });

  it("starts a focused amendment job bound to the exact source plan", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        amendment: { id: "AMD-1", status: "planning" },
        planning_job: { id: "PLAN-AMD-1", job_type: "plan_amendment" },
      }), {
        headers: { "content-type": "application/json" },
        status: 202,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const sourceSignature = "c".repeat(64);

    await startPlanAmendment("CMP/1", {
      reason: "A repository finding changes the future API slices.",
      focus: {
        branches: ["architecture"],
        trigger: { type: "finding", id: "FIND-1" },
      },
      expected_version: 7,
      expected_base_sha: "a".repeat(40),
      expected_plan_signature: sourceSignature,
      expected_plan_signature_version: 2,
    });

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/control-center/campaigns/CMP%2F1/amendments");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Idempotency-Key")).toMatch(
      /^plan-amendment-start:CMP-1:7:/,
    );
    expect(JSON.parse(String(init.body))).toEqual({
      reason: "A repository finding changes the future API slices.",
      focus: {
        branches: ["architecture"],
        trigger: { type: "finding", id: "FIND-1" },
      },
      expected_version: 7,
      expected_base_sha: "a".repeat(40),
      expected_plan_signature: sourceSignature,
      expected_plan_signature_version: 2,
      actor: "human",
    });
  });

  it("stops a question job directly and discards a generated plan through its campaign", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ planning_job: { id: "PLAN-question", status: "cancelled" } }), {
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ cancellation: { campaign: { id: "CMP-approval", status: "cancelled" } } }), {
          headers: { "content-type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const questionJob = {
      id: "PLAN/question",
      waiting_reason: "question",
      campaign_id: "CMP-question",
    } as ControlPlanningJob;
    const approvalJob = {
      id: "PLAN/approval",
      waiting_reason: "plan_approval",
      campaign_id: "CMP/approval",
    } as ControlPlanningJob;

    await stopPlanning(questionJob, "Nicht weiter planen.");
    await stopPlanning(approvalJob, "Entwurf verwerfen.");

    const [jobPath, jobInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const [campaignPath, campaignInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(jobPath).toBe("/api/control-center/planning-jobs/PLAN%2Fquestion/cancel");
    expect(JSON.parse(String(jobInit.body))).toEqual({
      actor: "human",
      reason: "Nicht weiter planen.",
    });
    expect(campaignPath).toBe("/api/control-center/campaigns/CMP%2Fapproval/cancel");
    expect(JSON.parse(String(campaignInit.body))).toEqual({
      actor: "human",
      reason: "Entwurf verwerfen.",
    });
  });

  it("cancels an amendment review through its planning job, not the paused campaign", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        planning_job: { id: "PLAN-AMD-1", status: "cancelled" },
      }), {
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await stopPlanning({
      id: "PLAN-AMD-1",
      campaign_id: "CMP-PAUSED-1",
      job_type: "plan_amendment",
      amendment_id: "AMD-1",
      waiting_reason: "amendment_approval",
    } as ControlPlanningJob, "Planänderung abbrechen.");

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/control-center/planning-jobs/PLAN-AMD-1/cancel");
    expect(path).not.toContain("/campaigns/");
    expect(JSON.parse(String(init.body))).toEqual({
      actor: "human",
      reason: "Planänderung abbrechen.",
    });
  });
});

describe("automation delivery API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("syncs GitHub and reevaluates evidence through their task-scoped mutations", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            sync: {
              task: { id: "TASK-1" },
              evidence_pack: { id: "EVD-1", status: "ready_for_human" },
            },
          }),
          { headers: { "content-type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            evidence_pack: { id: "EVD-1", status: "ready_for_human" },
          }),
          { headers: { "content-type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(syncTaskGitHub("TASK/1")).resolves.toMatchObject({
      task: { id: "TASK-1" },
    });
    await expect(evaluateTaskEvidence("TASK/1")).resolves.toMatchObject({
      id: "EVD-1",
    });

    const [syncPath, syncInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const [evidencePath, evidenceInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(syncPath).toBe("/api/control-center/tasks/TASK%2F1/github/sync");
    expect(syncInit.method).toBe("POST");
    expect(new Headers(syncInit.headers).get("Idempotency-Key")).toMatch(
      /^github-sync:TASK-1:/,
    );
    expect(evidencePath).toBe("/api/control-center/tasks/TASK%2F1/evidence/evaluate");
    expect(evidenceInit.method).toBe("POST");
    expect(new Headers(evidenceInit.headers).get("Idempotency-Key")).toMatch(
      /^evidence-evaluate:TASK-1:/,
    );
  });

  it("records an exact SHA-bound approval and sends merge with a human actor", async () => {
    const sha = "b".repeat(40);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            approval: {
              id: "APR-1",
              approval_type: "human_test",
              decision: "approved",
              sha,
            },
          }),
          { headers: { "content-type": "application/json" }, status: 201 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            merge: {
              task: { id: "TASK-1", status: "completed" },
              merge: { merged: true, message: "Pull Request successfully merged", sha },
              campaign_completed: false,
              issue_close_warning: "",
            },
          }),
          { headers: { "content-type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    await recordTaskApproval("TASK-1", {
      approval_type: "human_test",
      decision: "approved",
      sha,
      reason: "Manual browser test passed.",
    });
    await expect(mergeTaskOnGitHub("TASK-1")).resolves.toMatchObject({
      merge: { merged: true, sha },
    });

    const [approvalPath, approvalInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const [mergePath, mergeInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(approvalPath).toBe("/api/control-center/tasks/TASK-1/approvals");
    expect(approvalInit.method).toBe("POST");
    expect(new Headers(approvalInit.headers).get("Idempotency-Key")).toMatch(
      /^task-approval:TASK-1:human_test:approved:/,
    );
    expect(JSON.parse(String(approvalInit.body))).toEqual({
      approval_type: "human_test",
      decision: "approved",
      sha,
      actor: "human",
      reason: "Manual browser test passed.",
    });
    expect(mergePath).toBe("/api/control-center/tasks/TASK-1/github/merge");
    expect(mergeInit.method).toBe("POST");
    expect(new Headers(mergeInit.headers).get("Idempotency-Key")).toMatch(
      /^github-merge:TASK-1:/,
    );
    expect(JSON.parse(String(mergeInit.body))).toEqual({ actor: "human" });
  });

  it("sends the structured reproduction evidence with a rejected human test", async () => {
    const sha = "c".repeat(40);
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          approval: {
            id: "APR-rejected",
            approval_type: "human_test",
            decision: "rejected",
            sha,
          },
        }),
        { headers: { "content-type": "application/json" }, status: 201 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await recordTaskApproval("TASK-1", {
      approval_type: "human_test",
      decision: "rejected",
      sha,
      reason: "Reproduction captured.",
      evidence: {
        environment: "Windows 11, Chrome 128",
        executed_steps: "Open preview and press Enter on the focused result.",
        expected_behavior: "The result opens.",
        observed_behavior: "Nothing opens.",
        artifact_ref: "artifacts/failure.webm",
      },
    });

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/control-center/tasks/TASK-1/approvals");
    expect(JSON.parse(String(init.body))).toEqual({
      actor: "human",
      approval_type: "human_test",
      decision: "rejected",
      sha,
      reason: "Reproduction captured.",
      evidence: {
        artifact_ref: "artifacts/failure.webm",
        environment: "Windows 11, Chrome 128",
        executed_steps: "Open preview and press Enter on the focused result.",
        expected_behavior: "The result opens.",
        observed_behavior: "Nothing opens.",
      },
    });
  });
});
