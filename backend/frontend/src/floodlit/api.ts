// The matches API (docs/MATCHES_API.md) as the Floodlit screens use it.
import { ApiError, createApiClient, isCancellation } from "../api/client.js";
import type {
  Analysis,
  MatchPlayers,
  MatchStatus,
  MatchSummary,
  Mode,
  PersonId,
  Stats,
} from "./model.js";

// Looked up per request, so a test page can stand in for the server.
const client = createApiClient({
  fetch: (input, init) => globalThis.fetch(input, init),
});

function object(value: unknown, what: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error(`The server sent an unexpected ${what}`);
  return value as Record<string, unknown>;
}

export async function listMatches(signal?: AbortSignal) {
  const value: unknown = await client.request("get", "/api/matches", {
    ...(signal ? { signal } : {}),
  });
  if (!Array.isArray(value))
    throw new Error("The server sent an unexpected match list");
  return value.map((m) => object(m, "match") as unknown as MatchSummary);
}

export async function matchStatus(id: string, signal?: AbortSignal) {
  const value = object(
    await client.request("get", "/api/matches/{match_id}", {
      path: { match_id: id },
      ...(signal ? { signal } : {}),
    }),
    "match status",
  );
  if (typeof value.state !== "string" || typeof value.progress !== "number")
    throw new Error("The server sent an unexpected match status");
  return value as unknown as MatchStatus;
}

export async function matchPlayers(id: string, signal?: AbortSignal) {
  const value = object(
    await client.request("get", "/api/matches/{match_id}/players", {
      path: { match_id: id },
      ...(signal ? { signal } : {}),
    }),
    "player list",
  );
  if (!Array.isArray(value.players))
    throw new Error("The server sent an unexpected player list");
  return value as unknown as MatchPlayers;
}

export async function confirmNames(
  id: string,
  names: Partial<Record<PersonId, string>>,
) {
  return (await client.request("put", "/api/matches/{match_id}/players", {
    path: { match_id: id },
    json: { names },
  })) as MatchPlayers;
}

export async function loadAnalysis(id: string, signal?: AbortSignal) {
  const value = object(
    await client.request("get", "/api/matches/{match_id}/analysis", {
      path: { match_id: id },
      ...(signal ? { signal } : {}),
    }),
    "analysis",
  );
  if (
    !Array.isArray(value.rallies) ||
    !Array.isArray(value.players) ||
    !value.tracks ||
    !value.video ||
    !value.court
  )
    throw new Error("The server sent an analysis this page cannot read");
  return value as unknown as Analysis;
}

export async function loadStats(id: string, signal?: AbortSignal) {
  const value = object(
    await client.request("get", "/api/matches/{match_id}/stats", {
      path: { match_id: id },
      ...(signal ? { signal } : {}),
    }),
    "statistics",
  );
  if (
    !value.clip ||
    !Array.isArray(value.players) ||
    !Array.isArray(value.teams)
  )
    throw new Error("The server sent statistics this page cannot read");
  return value as unknown as Stats;
}

export async function swapRally(
  id: string,
  rallyId: string,
  persons: [PersonId, PersonId],
) {
  return client.request(
    "post",
    "/api/matches/{match_id}/rallies/{rally_id}/swap",
    {
      path: { match_id: id, rally_id: rallyId },
      json: { persons },
    },
  );
}

export async function undoSwaps(id: string, rallyId: string) {
  return client.request(
    "delete",
    "/api/matches/{match_id}/rallies/{rally_id}/swap",
    {
      path: { match_id: id, rally_id: rallyId },
    },
  );
}

export async function resumeMatch(id: string) {
  return client.request("post", "/api/matches/{match_id}/resume", {
    path: { match_id: id },
  });
}

export async function pauseMatch(id: string) {
  return client.request("post", "/api/matches/{match_id}/pause", {
    path: { match_id: id },
  });
}

/** The browser copy when one was prepared, else the stored video itself. */
export async function videoSource(id: string, signal?: AbortSignal) {
  try {
    const value: unknown = await client.request(
      "get",
      "/api/videos/{video_id}/playback",
      {
        path: { video_id: id },
        ...(signal ? { signal } : {}),
      },
    );
    const record =
      value && typeof value === "object"
        ? (value as Record<string, unknown>)
        : {};
    if (
      record.status === "ready" &&
      record.url === `/api/videos/${id}/playback/media`
    )
      return record.url;
  } catch (error) {
    if (isCancellation(error)) throw error;
  }
  return `/api/videos/${encodeURIComponent(id)}/media`;
}

export const thumbnailUrl = (id: string, person: string) =>
  `/api/matches/${encodeURIComponent(id)}/players/${encodeURIComponent(person)}/thumbnail`;
export const posterUrl = (id: string) =>
  `/api/videos/${encodeURIComponent(id)}/image/poster.jpg`;

export interface UploadProgress {
  loaded: number;
  total: number | null;
}
export interface MatchCreated {
  match_id: string;
  job_id: string;
  reused_video: boolean;
}

/** Upload with real transfer progress (XHR), parsed by the shared typed client. */
export function uploadMatch(
  file: File,
  mode: Mode,
  team1: string[],
  team2: string[],
  signal: AbortSignal,
  progress: (value: UploadProgress) => void,
): Promise<MatchCreated> {
  const body = new FormData();
  body.set("file", file);
  body.set("mode", mode);
  for (const name of team1) body.append("team1", name);
  for (const name of team2) body.append("team2", name);
  const fetcher: typeof fetch = (input, init) =>
    new Promise<Response>((resolve, reject) => {
      if (new URL(String(input), location.href).origin !== location.origin) {
        reject(new Error("Upload must use the same origin"));
        return;
      }
      const xhr = new XMLHttpRequest();
      const abort = () => xhr.abort();
      const cleanup = () => signal.removeEventListener("abort", abort);
      xhr.open(init?.method ?? "POST", String(input));
      xhr.timeout = 60 * 60 * 1000;
      new Headers(init?.headers).forEach((v, k) => xhr.setRequestHeader(k, v));
      xhr.upload.onprogress = (e) =>
        progress({
          loaded: e.loaded,
          total: e.lengthComputable ? e.total : null,
        });
      xhr.onload = () => {
        cleanup();
        resolve(
          new Response(xhr.responseText, {
            status: xhr.status,
            headers: {
              "Content-Type": xhr.getResponseHeader("Content-Type") ?? "",
            },
          }),
        );
      };
      xhr.ontimeout = () => {
        cleanup();
        reject(
          new Error(
            "The upload took too long. Check Your matches before trying again.",
          ),
        );
      };
      xhr.onerror = () => {
        cleanup();
        reject(
          new TypeError(
            "The upload was cut off. Check Your matches before trying again.",
          ),
        );
      };
      xhr.onabort = () => {
        cleanup();
        reject(new DOMException("Upload cancelled", "AbortError"));
      };
      signal.addEventListener("abort", abort, { once: true });
      if (signal.aborted) {
        cleanup();
        reject(new DOMException("Upload cancelled", "AbortError"));
        return;
      }
      xhr.send(init?.body as XMLHttpRequestBodyInit);
    });
  return createApiClient({ fetch: fetcher })
    .request("post", "/api/matches", { body, signal })
    .then((value) => {
      const record = object(value, "upload reply");
      if (typeof record.match_id !== "string")
        throw new Error("The server sent an unexpected upload reply");
      return record as unknown as MatchCreated;
    });
}

/** A plain sentence for an error, for the screens to show. */
export function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 413) return "That file is too large for the server.";
    const detail = error.detail;
    if (typeof detail === "string" && detail) return withStop(detail);
    if (Array.isArray(detail)) {
      const messages = detail
        .map((d) =>
          d && typeof d === "object" && "msg" in d ? String(d.msg) : "",
        )
        .filter(Boolean);
      if (messages.length) return withStop(messages.join(". "));
    }
    return `The server said no (${error.status}).`;
  }
  if (
    error instanceof TypeError &&
    /fetch|network|load failed/i.test(error.message)
  )
    return "Could not reach the analyzer. Is it still running?";
  if (error instanceof Error && error.message) return withStop(error.message);
  return "Something went wrong.";
}
const withStop = (s: string) => (/[.!?]$/.test(s) ? s : `${s}.`);
