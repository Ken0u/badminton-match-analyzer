import type { components } from "../../api/client.js";

export type ExportMode = components["schemas"]["MediaExportRequest"]["mode"];
export const exportModes: readonly ExportMode[] = [
  "plain-rallies",
  "annotated-rallies",
  "annotated-full",
];

export interface ExportRequest {
  readonly videoId: string;
  readonly revision: number;
  readonly mode: ExportMode;
}
export interface ExportJob extends ExportRequest {
  readonly id: string;
  readonly status: string;
  readonly progress: number;
  readonly message: string;
}
export interface ExportFile {
  readonly filename: string;
  readonly sizeBytes: number;
  readonly sha256: string;
  readonly mediaType: "application/json" | "video/mp4";
  readonly href: string;
}
export interface CompletedExport extends ExportJob {
  readonly available: true;
  readonly files: readonly ExportFile[];
  readonly counts: {
    readonly total: number;
    readonly eligible: number;
    readonly ineligible: number;
  };
  readonly rallies: readonly {
    readonly rallyId: string;
    readonly eligible: boolean;
    readonly reasons: readonly string[];
  }[];
}
export interface UnavailableExport extends ExportJob {
  readonly available: false;
  readonly unavailableReason?: string;
}
export type ExportStatus = CompletedExport | UnavailableExport;

export class ExportPayloadError extends Error {
  constructor(
    message = "Invalid media export response. Refresh the job or start a new export.",
  ) {
    super(message);
  }
}
const record = (value: unknown, name: string): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new ExportPayloadError(
      `Invalid ${name} response. Refresh the job or start a new export.`,
    );
  return value as Record<string, unknown>;
};
const text = (value: unknown, name: string) => {
  if (typeof value !== "string" || !value)
    throw new ExportPayloadError(
      `Invalid ${name} response. Refresh the job or start a new export.`,
    );
  return value;
};
const integer = (value: unknown, name: string) => {
  if (!Number.isSafeInteger(value) || (value as number) < 0)
    throw new ExportPayloadError(
      `Invalid ${name} response. Refresh the job or start a new export.`,
    );
  return value as number;
};
const SHA256 = /^[a-f0-9]{64}$/;
const JOB_ID = /^[a-f0-9]{32}$/;
const filenameFor = (mode: ExportMode) =>
  new RegExp(
    `^${mode === "annotated-full" ? "full" : "rally"}-[0-9]{6}\\.mp4$`,
  );

function parseMode(value: unknown): ExportMode {
  if (!exportModes.includes(value as ExportMode))
    throw new ExportPayloadError();
  return value as ExportMode;
}
function sameRequest(job: ExportJob, expected: ExportRequest) {
  if (
    job.videoId !== expected.videoId ||
    job.revision !== expected.revision ||
    job.mode !== expected.mode
  )
    throw new ExportPayloadError(
      "Media export ownership does not match the selected saved revision.",
    );
}
export function parseExportJob(
  value: unknown,
  expected?: ExportRequest,
): ExportJob {
  const raw = record(value, "media export job");
  const id = text(raw.id, "media export job id");
  if (!JOB_ID.test(id) || raw.kind !== "media-export")
    throw new ExportPayloadError();
  const details = record(raw.details, "media export details");
  const job: ExportJob = {
    id,
    videoId: text(raw.video_id, "media export video"),
    revision: integer(details.revision, "media export revision"),
    mode: parseMode(details.mode),
    status: text(raw.status, "media export status"),
    progress:
      typeof raw.progress === "number" &&
      Number.isFinite(raw.progress) &&
      raw.progress >= 0 &&
      raw.progress <= 1
        ? raw.progress
        : 0,
    message: typeof raw.message === "string" ? raw.message : "",
  };
  if (expected) sameRequest(job, expected);
  return job;
}
export function parseRecoveredExports(
  value: unknown,
  videoId: string,
): ExportJob[] {
  if (!Array.isArray(value))
    throw new ExportPayloadError(
      "Invalid media export list. Refresh the job list.",
    );
  const jobs = value
    .filter((item) => record(item, "job").kind === "media-export")
    .map((item) => parseExportJob(item));
  if (
    jobs.some((job) => job.videoId !== videoId) ||
    new Set(jobs.map((job) => job.id)).size !== jobs.length
  )
    throw new ExportPayloadError(
      "Media export list contains an unexpected job.",
    );
  return jobs;
}
function safeDownload(videoId: string, jobId: string, filename: string) {
  return `/api/videos/${encodeURIComponent(videoId)}/media-exports/${encodeURIComponent(jobId)}/files/${encodeURIComponent(filename)}`;
}
function parseManifest(value: unknown, request: ExportRequest) {
  const manifest = record(value, "media export manifest");
  const source = record(manifest.source, "media export source");
  const annotations = record(manifest.annotations, "media export annotations");
  if (
    manifest.schema_version !== 1 ||
    manifest.purpose !==
      (request.mode === "plain-rallies"
        ? "reviewed_rally_videos"
        : "annotated_videos") ||
    (request.mode !== "plain-rallies" &&
      manifest.scope !==
        (request.mode === "annotated-full" ? "full" : "rallies"))
  )
    throw new ExportPayloadError(
      "Media export manifest does not match the selected mode.",
    );
  if (
    source.id !== request.videoId ||
    integer(manifest.annotation_revision, "manifest revision") !==
      request.revision ||
    integer(annotations.revision, "manifest annotation revision") !==
      request.revision
  )
    throw new ExportPayloadError(
      "Media export manifest does not own the requested saved revision.",
    );
  const counts = record(manifest.counts, "media export counts");
  const parsedCounts = {
    total: integer(counts.total, "rally count"),
    eligible: integer(counts.eligible, "eligible rally count"),
    ineligible: integer(counts.ineligible, "ineligible rally count"),
  };
  if (
    parsedCounts.total !== parsedCounts.eligible + parsedCounts.ineligible ||
    !Array.isArray(manifest.rallies) ||
    manifest.rallies.length !== parsedCounts.total
  )
    throw new ExportPayloadError(
      "Media export counts do not match every rally receipt.",
    );
  let eligible = 0;
  const rallies: { rallyId: string; eligible: boolean; reasons: string[] }[] =
    [];
  const clips: { filename: string; sha256: string }[] = [];
  for (const rally of manifest.rallies) {
    const item = record(rally, "rally receipt");
    if (
      typeof item.eligible !== "boolean" ||
      !Array.isArray(item.reasons) ||
      item.reasons.some((reason) => typeof reason !== "string" || !reason)
    )
      throw new ExportPayloadError("Invalid rally eligibility receipt.");
    const clip = item.clip;
    const rallyId = text(item.rally_id, "rally id");
    const reasons = [...item.reasons] as string[];
    if (item.eligible) {
      eligible++;
      if (request.mode !== "annotated-full") {
        const receipt = record(clip, "rally media receipt");
        clips.push({
          filename: text(receipt.file, "rally media filename"),
          sha256: text(receipt.sha256, "rally media hash"),
        });
      }
    } else if (clip !== null)
      throw new ExportPayloadError(
        "Ineligible rally unexpectedly has an export file.",
      );
    rallies.push({ rallyId, eligible: item.eligible, reasons });
  }
  if (eligible !== parsedCounts.eligible)
    throw new ExportPayloadError(
      "Media export eligibility does not match every rally receipt.",
    );
  if (request.mode === "annotated-full") {
    if (!Array.isArray(manifest.exports) || manifest.exports.length !== 1)
      throw new ExportPayloadError("Full media export receipt is incomplete.");
    const receipt = record(manifest.exports[0], "full media receipt");
    clips.push({
      filename: text(receipt.file, "full media filename"),
      sha256: text(receipt.sha256, "full media hash"),
    });
  } else if (request.mode === "annotated-rallies") {
    if (
      !Array.isArray(manifest.exports) ||
      manifest.exports.length !== clips.length
    )
      throw new ExportPayloadError("Annotated rally receipts are incomplete.");
    const exports = manifest.exports.map((item) =>
      record(item, "annotated rally receipt"),
    );
    if (
      exports.some(
        (item, index) =>
          item.file !== clips[index]?.filename ||
          item.sha256 !== clips[index]?.sha256,
      )
    )
      throw new ExportPayloadError(
        "Annotated rally receipts do not match every exported rally.",
      );
  }
  if (
    new Set(clips.map((clip) => clip.filename)).size !== clips.length ||
    clips.some(
      (clip) =>
        !filenameFor(request.mode).test(clip.filename) ||
        !SHA256.test(clip.sha256),
    )
  )
    throw new ExportPayloadError("Invalid media receipt in export manifest.");
  if (
    rallies.filter((rally) => !rally.eligible).length !==
      parsedCounts.ineligible ||
    new Set(rallies.map((rally) => rally.rallyId)).size !== rallies.length
  )
    throw new ExportPayloadError("Media export rally receipts are incomplete.");
  return { counts: parsedCounts, rallies, clips };
}
export function parseExportStatus(
  value: unknown,
  request: ExportRequest,
  jobId: string,
): ExportStatus {
  const raw = record(value, "media export status");
  const job = parseExportJob(raw.job, request);
  if (job.id !== jobId)
    throw new ExportPayloadError("Media export status belongs to another job.");
  if (raw.available !== true) {
    if (raw.available !== false) throw new ExportPayloadError();
    return { ...job, available: false };
  }
  if (job.status !== "completed")
    throw new ExportPayloadError(
      "Only completed media exports can be available.",
    );
  const manifest = parseManifest(raw.manifest, request);
  if (!Array.isArray(raw.files))
    throw new ExportPayloadError("Invalid media export files response.");
  const names = new Set<string>();
  const files: ExportFile[] = raw.files.map((value) => {
    const file = record(value, "media export file");
    const filename = text(file.filename, "media export filename");
    const manifestFile = filename === "manifest.json";
    if (
      (!manifestFile && !filenameFor(request.mode).test(filename)) ||
      names.has(filename)
    )
      throw new ExportPayloadError(
        "Media export includes an unsafe or duplicate file.",
      );
    names.add(filename);
    const mediaType = file.media_type;
    if (
      (manifestFile && mediaType !== "application/json") ||
      (!manifestFile && mediaType !== "video/mp4") ||
      !SHA256.test(text(file.sha256, "media export hash"))
    )
      throw new ExportPayloadError(
        "Media export file receipt is inconsistent.",
      );
    return {
      filename,
      sizeBytes: integer(file.size_bytes, "media export file size"),
      sha256: file.sha256 as string,
      mediaType: mediaType as ExportFile["mediaType"],
      href: safeDownload(request.videoId, job.id, filename),
    };
  });
  if (!names.has("manifest.json") || files.length !== names.size)
    throw new ExportPayloadError("Media export is missing its manifest.");
  const videos = files.filter((file) => file.mediaType === "video/mp4");
  if (
    videos.length !== manifest.clips.length ||
    videos.some(
      (file) =>
        !manifest.clips.some(
          (clip) =>
            clip.filename === file.filename && clip.sha256 === file.sha256,
        ),
    )
  )
    throw new ExportPayloadError(
      "Media export files do not cover the completed rally receipts.",
    );
  return { ...job, available: true, files, ...manifest };
}
