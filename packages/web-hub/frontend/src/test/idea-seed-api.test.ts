import { afterEach, describe, expect, it, vi } from "vitest";

import {
  dispositionIdeaSeed,
  getIdeaSeed,
  listIdeaSeeds,
  planIdeaSeed,
  updateIdeaSeed,
} from "@/features/automation/api";

const seed = {
  id: "IDEA/1",
  project_id: 52,
  title: "Accessible search",
  note: "Build an accessible project search with tests.",
  source: "human",
  status: "inbox",
  provenance: {},
};

describe("idea-seed API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists and gets the exact persisted seed records", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ idea_seeds: [seed] }), {
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ idea_seed: seed }), {
          headers: { "content-type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(listIdeaSeeds(52)).resolves.toEqual([seed]);
    await expect(getIdeaSeed("IDEA/1")).resolves.toEqual(seed);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/control-center/idea-seeds?project_id=52",
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      "/api/control-center/idea-seeds/IDEA%2F1",
    );
  });

  it("updates editable content and records a valid disposition", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ idea_seed: { ...seed, title: "Accessible repository search" } }),
          { headers: { "content-type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ idea_seed: { ...seed, status: "deferred" } }),
          { headers: { "content-type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    await updateIdeaSeed("IDEA/1", {
      title: "Accessible repository search",
      note: "Build an accessible repository search with tests.",
    });
    await dispositionIdeaSeed("IDEA/1", {
      disposition: "deferred",
      reason: "Wait for the API migration.",
    });

    const [updatePath, updateInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const [dispositionPath, dispositionInit] = fetchMock.mock.calls[1] as [
      string,
      RequestInit,
    ];
    expect(updatePath).toBe("/api/control-center/idea-seeds/IDEA%2F1");
    expect(updateInit.method).toBe("PATCH");
    expect(new Headers(updateInit.headers).get("Idempotency-Key")).toMatch(
      /^idea-seed-update:IDEA-1:/,
    );
    expect(JSON.parse(String(updateInit.body))).toEqual({
      actor: "human",
      title: "Accessible repository search",
      note: "Build an accessible repository search with tests.",
    });
    expect(dispositionPath).toBe(
      "/api/control-center/idea-seeds/IDEA%2F1/disposition",
    );
    expect(dispositionInit.method).toBe("POST");
    expect(new Headers(dispositionInit.headers).get("Idempotency-Key")).toMatch(
      /^idea-seed-disposition:IDEA-1:deferred:/,
    );
    expect(JSON.parse(String(dispositionInit.body))).toEqual({
      actor: "human",
      disposition: "deferred",
      reason: "Wait for the API migration.",
    });
  });

  it("plans the existing seed without sending duplicate seed content", async () => {
    const planningJob = {
      id: "PLAN-1",
      idea_seed_id: "IDEA/1",
      status: "queued",
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ planning_job: planningJob }), {
        headers: { "content-type": "application/json" },
        status: 202,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      planIdeaSeed("IDEA/1", {
        activation_policy: "campaign_wave",
        planning_depth: "deep",
        max_candidates: 30,
        constraints: ["Keep the API compatible"],
      }),
    ).resolves.toEqual(planningJob);

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/control-center/idea-seeds/IDEA%2F1/plan");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Idempotency-Key")).toMatch(
      /^idea-seed-plan:IDEA-1:/,
    );
    expect(JSON.parse(String(init.body))).toEqual({
      actor: "human",
      activation_policy: "campaign_wave",
      planning_depth: "deep",
      max_candidates: 30,
      constraints: ["Keep the API compatible"],
    });
  });
});
