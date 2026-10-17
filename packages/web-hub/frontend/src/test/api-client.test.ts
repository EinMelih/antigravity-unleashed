import { afterEach, describe, expect, it, vi } from "vitest";

import { apiRequest } from "@/api/client";

describe("apiRequest", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns typed JSON responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "ok" }), {
          headers: { "content-type": "application/json" },
          status: 200,
        }),
      ),
    );

    await expect(apiRequest<{ status: string }>("/health")).resolves.toEqual({
      status: "ok",
    });
  });

  it("normalizes backend failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "Nicht erlaubt", code: "permission_denied" }), {
          headers: { "content-type": "application/json" },
          status: 403,
        }),
      ),
    );

    await expect(apiRequest("/api/protected")).rejects.toMatchObject({
      code: "permission_denied",
      message: "Nicht erlaubt",
      status: 403,
    });
  });

  it("marks network failures as offline", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));

    await expect(apiRequest("/health")).rejects.toEqual(
      expect.objectContaining({
        offline: true,
      }),
    );
  });

  it("treats unavailable proxy gateways as offline", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("upstream unavailable", {
          headers: { "content-type": "text/plain" },
          status: 502,
        }),
      ),
    );

    await expect(apiRequest("/health")).rejects.toEqual(
      expect.objectContaining({
        offline: true,
        status: 502,
      }),
    );
  });
});
