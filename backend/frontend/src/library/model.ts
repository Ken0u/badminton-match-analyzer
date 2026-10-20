import { ApiError } from "../api/client.js";
import type { components } from "../api/client.js";

export type AnalysisSettings = components["schemas"]["AnalysisRequest"];
export interface Video {
  id: string;
  name: string;
  mode: string;
  duration_s: number;
  frame_count: number;
}
export interface Job {
  id: string;
  kind: string;
  video_id: string | null;
  status: string;
  progress: number;
  message: string;
  cancel_requested: boolean;
  settings: AnalysisSettings | null;
}
export interface Playback {
  status: "ready" | "missing";
  url: string | null;
}
export interface Analysis {
  job: Job;
  state: string;
  requiresProcessingRerun: boolean;
}
export class PayloadError extends Error {
  constructor(resource: string) {
    super(`Invalid ${resource} response. Reload before continuing.`);
  }
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new PayloadError("server");
  return value as Record<string, unknown>;
}
function text(value: unknown, field: string): string {
  if (typeof value !== "string" || !value) throw new PayloadError(field);
  return value;
}
function number(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0)
    throw new PayloadError(field);
  return value;
}
export function parseVideo(value: unknown): Video {
  const v = record(value);
  if (!Number.isInteger(v.frame_count)) throw new PayloadError("frame count");
  return {
    id: text(v.id, "video id"),
    name: text(v.name, "video name"),
    mode: text(v.mode, "video mode"),
    duration_s: number(v.duration_s, "duration"),
    frame_count: number(v.frame_count, "frame count"),
  };
}
export function parseVideos(value: unknown): Video[] {
  if (!Array.isArray(value)) throw new PayloadError("library");
  const videos = value.map(parseVideo);
  if (new Set(videos.map((v) => v.id)).size !== videos.length)
    throw new PayloadError("duplicate video");
  return videos;
}
export function parseSettings(value: unknown): AnalysisSettings | null {
  if (value == null) return null;
  const s = record(value);
  if (
    (s.player_model !== "small" && s.player_model !== "nano") ||
    typeof s.auto_calibrate !== "boolean" ||
    typeof s.recognize !== "boolean"
  )
    throw new PayloadError("processing settings");
  return {
    player_model: s.player_model,
    auto_calibrate: s.auto_calibrate,
    recognize: s.recognize,
  };
}
export function parseJob(value: unknown): Job {
  const j = record(value);
  const progress = number(j.progress, "job progress");
  if (progress > 1 || (j.video_id !== null && typeof j.video_id !== "string"))
    throw new PayloadError("job");
  if (
    j.cancel_requested !== undefined &&
    typeof j.cancel_requested !== "boolean"
  )
    throw new PayloadError("pause status");
  const details = j.details == null ? null : record(j.details);
  return {
    id: text(j.id, "job id"),
    kind: text(j.kind, "job kind"),
    video_id: j.video_id,
    status: text(j.status, "job status"),
    progress,
    message: typeof j.message === "string" ? j.message : "",
    cancel_requested: j.cancel_requested === true,
    settings:
      details?.settings == null ? null : parseSettings(details.settings),
  };
}
export function parseJobs(value: unknown): Job[] {
  if (!Array.isArray(value)) throw new PayloadError("jobs");
  return value.map(parseJob);
}
export function parsePlayback(value: unknown, videoId: string): Playback {
  const p = record(value);
  if (p.status === "missing" && p.url === null)
    return { status: "missing", url: null };
  const expected = `/api/videos/${encodeURIComponent(videoId)}/playback/media`;
  if (p.status === "ready" && p.url === expected)
    return { status: "ready", url: expected };
  throw new PayloadError("playback");
}
export function parseAnalysis(
  value: unknown,
  videoId: string,
  jobId: string,
): Analysis {
  const p = record(value),
    job = parseJob(p.job);
  if (
    job.video_id !== videoId ||
    job.id !== jobId ||
    job.kind !== "analysis" ||
    typeof p.requires_processing_rerun !== "boolean"
  )
    throw new PayloadError("processing progress");
  return {
    job,
    state: typeof p.state === "string" ? p.state : job.status,
    requiresProcessingRerun: p.requires_processing_rerun,
  };
}
export const activeJob = (j: Job) =>
  j.status === "queued" || j.status === "running";
export function validateYoutube(raw: string): string {
  const message = "Enter an HTTPS YouTube video URL without a playlist.";
  if (raw.length > 2048 || /[\s\\]/.test(raw)) throw new Error(message);
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(message);
  }
  if (
    url.protocol !== "https:" ||
    !["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"].includes(
      url.hostname,
    ) ||
    url.username ||
    url.password ||
    url.port ||
    Array.from(url.searchParams.keys()).some((k) =>
      ["list", "playlist", "index", "start_radio"].includes(k.toLowerCase()),
    )
  )
    throw new Error(message);
  const values = url.searchParams.getAll("v");
  let id: string | undefined;
  if (url.hostname === "youtu.be") {
    id = /^\/([A-Za-z0-9_-]{11})\/?$/.exec(url.pathname)?.[1];
    if (values.length) throw new Error(message);
  } else if (url.pathname === "/watch") {
    if (values.length === 1) id = values[0];
  } else {
    id = /^\/(?:shorts|live)\/([A-Za-z0-9_-]{11})\/?$/.exec(url.pathname)?.[1];
    if (values.length) throw new Error(message);
  }
  if (!id || !/^[A-Za-z0-9_-]{11}$/.test(id)) throw new Error(message);
  return `https://www.youtube.com/watch?v=${id}`;
}
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const detail =
      typeof error.detail === "string"
        ? error.detail
        : error.detail
          ? JSON.stringify(error.detail)
          : error.message;
    const hint =
      error.status === 401 || error.status === 403
        ? " Authentication is required; sign in and retry."
        : error.status === 413
          ? " Choose a smaller video."
          : error.status === 409
            ? " Reload jobs and source state before retrying."
            : error.status === 422
              ? " Check the input and try again."
              : "";
    return `HTTP ${error.status}: ${detail}${hint}`;
  }
  return error instanceof Error ? error.message : "Request failed. Try again.";
}
