import { ApiError } from "@/api/errors";

interface ApiErrorPayload {
  code?: unknown;
  error?: unknown;
  message?: unknown;
  detail?: unknown;
  request_id?: unknown;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

async function parseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  const text = await response.text();
  return text || undefined;
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;

  try {
    response = await fetch(path, {
      ...init,
      headers: {
        Accept: "application/json",
        ...init.headers,
      },
    });
  } catch (error) {
    throw new ApiError("Der Anti-Gravity Hub ist nicht erreichbar.", {
      offline: true,
      technicalDetails: error instanceof Error ? error.message : String(error),
    });
  }

  const body = await parseBody(response);

  if (!response.ok) {
    const payload =
      typeof body === "object" && body !== null
        ? (body as ApiErrorPayload)
        : undefined;
    const technicalDetails =
      stringValue(payload?.detail) ??
      stringValue(payload?.error) ??
      (typeof body === "string" ? body : undefined);

    throw new ApiError(
      stringValue(payload?.message) ??
        stringValue(payload?.error) ??
        `Die Anfrage ist fehlgeschlagen (HTTP ${response.status}).`,
      {
        code: stringValue(payload?.code),
        offline: [502, 503, 504].includes(response.status),
        status: response.status,
        technicalDetails,
        requestId: stringValue(payload?.request_id),
      },
    );
  }

  return body as T;
}
