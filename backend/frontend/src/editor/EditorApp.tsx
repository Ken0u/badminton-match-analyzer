import { memo, useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { ChangeEvent, ReactNode } from "react";
import { createEditorController } from "./controller.js";
import type { EditorController, LoadedRun } from "./controller.js";
import { Playback } from "./Playback.js";
import type { PlaybackActions } from "./Playback.js";
import { ExportPanel } from "./exports/ExportPanel.js";
import {
  array,
  bounds,
  cameraSignature,
  clock,
  contextSignature,
  courtChanged,
  num,
  object,
  objects,
  ownedCandidates,
  pretty,
  str,
} from "./model.js";
import type { Document, Event, ObjectData, Point, Schema } from "./model.js";
import "./editor.css";
const families = [
  "unknown",
  "clear",
  "lift",
  "net",
  "drop",
  "smash",
  "drive",
  "other",
] as const;
const sides = ["unknown", "forehand", "backhand"] as const;
const kinds = ["serve", "shot", "rally_end"] as const;
type FormValues = Record<string, string>;
function useFields(initial: FormValues) {
  const [value, set] = useState(initial);
  return {
    value,
    set,
    put: (key: string, v: string) =>
      set((previous) => ({ ...previous, [key]: v })),
    reset: (v: FormValues) => set({ ...initial, ...v }),
  };
}
type Fields = ReturnType<typeof useFields>;
function Field({
  id,
  label,
  fields,
  type = "number",
  options,
  min = "0",
  max,
  required = false,
}: {
  id: string;
  label: string;
  fields: Fields;
  type?: string;
  options?: readonly string[];
  min?: string;
  max?: number;
  required?: boolean;
}) {
  const value = fields.value[id] ?? "";
  const change = (
    e: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>,
  ) => fields.put(id, e.target.value);
  return (
    <label>
      {label}
      {options ? (
        <select id={id} value={value} onChange={change}>
          {options.map((v) => (
            <option key={v} value={v}>
              {v === "" ? "Unknown hitter" : pretty(v)}
            </option>
          ))}
        </select>
      ) : type === "textarea" ? (
        <textarea
          id={id}
          value={value}
          onChange={change}
          maxLength={2000}
          rows={2}
        />
      ) : (
        <input
          id={id}
          type={type}
          min={min}
          max={max}
          value={value}
          onChange={change}
          required={required}
          maxLength={type === "text" ? 2000 : undefined}
        />
      )}
    </label>
  );
}
function Panel({
  id,
  title,
  children,
  open = false,
}: {
  id?: string;
  title: string;
  children: ReactNode;
  open?: boolean;
}) {
  return (
    <details className="players-panel" id={id} open={open || undefined}>
      <summary>{title}</summary>
      {children}
    </details>
  );
}
const Timeline = memo(function Timeline({
  doc,
  times,
  count,
  selected,
  edit,
}: {
  doc: Document;
  times: number[];
  count: number;
  selected: string | null;
  edit: (id: string) => void;
}) {
  const [filter, setFilter] = useState("");
  const rallies = [...new Set(doc.events.map((e) => e.rally_id))];
  return (
    <>
      <div id="event-markers" aria-label="Event markers">
        {doc.events.map((e) => (
          <button
            key={e.id}
            className={e.kind}
            style={{
              left: `${Math.min(99.5, (e.frame / Math.max(1, count - 1)) * 100)}%`,
            }}
            title={`${pretty(e.kind)} · ${clock(times[e.frame] ?? 0)}`}
            data-jump={e.id}
            aria-label={`Jump to ${pretty(e.kind)} at frame ${e.frame}`}
            onClick={() => edit(e.id)}
          />
        ))}
      </div>
      <div className="list-header">
        RALLY TIMELINE
        <select
          id="filter-rally"
          aria-label="Filter rallies"
          value={rallies.includes(filter) ? filter : ""}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="">All rallies</option>
          {rallies.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
      </div>
      <div id="events">
        {[...doc.events]
          .sort((a, b) => a.frame - b.frame)
          .filter((e) => !filter || e.rally_id === filter)
          .map((e) => (
            <button
              key={e.id}
              className={`event-row ${selected === e.id ? "active" : ""}`}
              data-event={e.id}
              onClick={() => edit(e.id)}
            >
              <span className={`event-dot ${e.kind}`} />
              <time>{clock(times[e.frame] ?? 0)}</time>
              <span>
                {e.kind === "shot" ? pretty(e.family) : pretty(e.kind)}
                <small>
                  {e.rally_id} ·{" "}
                  {doc.players.find((p) => p.id === e.player_id)?.name ?? "—"}
                  {e.side ? ` · ${pretty(e.side)}` : ""}
                  {(e.terminal_start_frame ?? e.contact_start_frame) != null
                    ? ` · timing ${e.terminal_start_frame ?? e.contact_start_frame}–${e.terminal_end_frame ?? e.contact_end_frame}`
                    : ""}
                </small>
              </span>
            </button>
          ))}
        {!doc.events.length && (
          <p className="empty">
            No events yet. Mark the serve to begin a rally.
          </p>
        )}
      </div>
    </>
  );
});
function sourcePlayer(
  doc: Document,
  runId: string | undefined,
  track: unknown,
  frame: number,
) {
  return (
    doc.track_assignments.find(
      (a) =>
        a.run_id === runId &&
        a.track_id === track &&
        a.start_frame <= frame &&
        frame < a.end_frame,
    )?.player_id ?? ""
  );
}
export function EditorApp() {
  const [controller] = useState(createEditorController);
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot),
    draft = useSyncExternalStore(
      controller.drafts.subscribe,
      controller.drafts.getSnapshot,
    );
  const doc = draft?.value;
  const actions = useRef<PlaybackActions | null>(null);
  const [corners, setCorners] = useState<Point[] | null>(null),
    [labeling, setLabeling] = useState(false),
    [showTracks, setShowTracks] = useState(true),
    [showShuttle, setShowShuttle] = useState(true),
    [selected, setSelected] = useState<string | null>(null),
    [pending, setPending] = useState<{
      source: string | null;
      candidate: string | null;
      classification: string | null;
      classificationCandidate: string | null;
      frame: number;
      family: string | null;
      kind: string;
      score: number | null;
    } | null>(null);
  const [sceneId, setSceneId] = useState<string | null>(null);
  const [auto, setAuto] = useState(true),
    [audio, setAudio] = useState(false),
    [recognize, setRecognize] = useState(true),
    [complete, setComplete] = useState(false),
    [servesComplete, setServesComplete] = useState(false),
    [rallyEndsComplete, setRallyEndsComplete] = useState(false);
  const [part, setPart] = useState(0);
  const renders = useRef(0);
  renders.current++;
  const fields = useFields({
    "rally-id": "R1",
    "event-kind": "shot",
    "event-frame": "0",
    "event-player": "",
    "event-family": "unknown",
    "event-side": "unknown",
    "event-notes": "",
    "contact-start": "",
    "contact-end": "",
    "court-start": "0",
    "court-end": "",
    "player-model": "small",
    "track-duration": "10",
    "camera-frame": "",
    "camera-decision": "cut",
    "camera-notes": "",
    "scene-start": "",
    "scene-end": "",
    "scene-kind": "live",
    "scene-notes": "",
    "identity-track": "",
    "identity-player": "",
    "identity-start": "0",
    "identity-end": "",
    "review-start": "0",
    "review-end": "",
    "review-scene": "unknown",
    "review-notes": "",
  });
  const latest = useRef({ fields, doc, selected, pending });
  latest.current = { fields, doc, selected, pending };
  useEffect(() => controller.start(), [controller]);
  const initialSelection = useRef(false);
  useEffect(() => {
    if (initialSelection.current || !state.videos.length) return;
    initialSelection.current = true;
    const id = new URLSearchParams(location.search).get("video");
    if (id && state.videos.some((v) => v.id === id)) void controller.select(id);
  }, [controller, state.videos]);
  useEffect(() => {
    if (!state.video || !doc) return;
    setSelected(null);
    setPending(null);
    setCorners(null);
    setLabeling(false);
    setSceneId(null);
    setComplete(false);
    setServesComplete(false);
    setRallyEndsComplete(false);
    const start = state.video.review_start_frame,
      cal = doc.calibrations.find(
        (c) => c.start_frame <= start && start < c.end_frame,
      );
    fields.reset({
      "court-start": String(cal?.start_frame ?? 0),
      "court-end": String(cal?.end_frame ?? state.video.frame_count),
      "review-start": String(start),
      "review-end": String(Math.min(state.video.frame_count, start + 250)),
      "event-frame": String(start),
      "identity-end": String(state.video.frame_count),
      "identity-player": doc.players[0]?.id ?? "",
    });
  }, [state.video?.id]);
  useEffect(() => {
    const run = state.runs.players?.run;
    if (run) {
      const tracks = [
        ...new Set(
          run.frames
            .flatMap((f) => objects(f.players).map((p) => p.track_id))
            .filter((t) => typeof t === "number"),
        ),
      ].sort((a, b) => num(a) - num(b));
      fields.set((previous) => ({
        ...previous,
        "identity-track": String(tracks[0] ?? ""),
        "identity-start": String(run.start_frame),
        "identity-end": String(run.end_frame),
      }));
    }
  }, [state.runs.players?.id]);
  function frame() {
    return controller.playback.getSnapshot().sourceFrame ?? 0;
  }
  function seek(f: number) {
    actions.current?.seek(f);
  }
  function attempt(action: () => void) {
    try {
      action();
    } catch (e) {
      controller.handle(e);
    }
  }
  function edit(update: (d: Document) => void) {
    controller.edit((d) => {
      update(d);
      return d;
    });
  }
  function reset(kind: Event["kind"] = "shot", at = frame()) {
    setSelected(null);
    setPending(null);
    fields.set((v) => ({
      ...v,
      "event-kind": kind,
      "event-frame": String(at),
      "event-family": "unknown",
      "event-side": "unknown",
      "event-notes": "",
      "contact-start": "",
      "contact-end": "",
    }));
  }
  function mark(kind: Event["kind"]) {
    seek(frame());
    reset(kind);
    requestAnimationFrame(() =>
      document
        .getElementById(
          kind === "shot"
            ? "event-family"
            : kind === "serve"
              ? "event-player"
              : "event-frame",
        )
        ?.focus(),
    );
    controller.notice(
      `Choose the ${kind === "shot" ? "shot family and stroke side" : "event details"}, then add the event.`,
    );
  }
  const editEvent = useRef<(id: string) => void>(() => {});
  editEvent.current = (id: string) => {
    const e = latest.current.doc?.events.find((e) => e.id === id);
    if (!e) return;
    setSelected(id);
    setPending(null);
    fields.set((v) => ({
      ...v,
      "rally-id": e.rally_id,
      "event-kind": e.kind,
      "event-frame": String(e.frame),
      "event-player": e.player_id ?? "",
      "event-family": e.family ?? "unknown",
      "event-side": e.side ?? "unknown",
      "event-notes": e.notes ?? "",
      "contact-start": String(
        (e.kind === "rally_end"
          ? e.terminal_start_frame
          : e.contact_start_frame) ?? "",
      ),
      "contact-end": String(
        (e.kind === "rally_end" ? e.terminal_end_frame : e.contact_end_frame) ??
          "",
      ),
    }));
    seek(e.frame);
  };
  const [stableEdit] = useState(() => (id: string) => editEvent.current(id));
  const keyboard = useRef({ mark, seek });
  keyboard.current = { mark, seek };
  useEffect(() => {
    const unload = (e: BeforeUnloadEvent) => {
      if (controller.drafts.getSnapshot()?.dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        void saveWithFocus();
        return;
      }
      if (
        !controller.snapshot().video ||
        ["INPUT", "TEXTAREA", "SELECT"].includes(
          document.activeElement?.tagName ?? "",
        )
      )
        return;
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        keyboard.current.seek(
          (controller.playback.getSnapshot().sourceFrame ?? 0) +
            (e.key === "ArrowLeft" ? -1 : 1),
        );
      }
      if (e.code === "Space") {
        e.preventDefault();
        actions.current?.toggle();
      }
      if (e.key === "1" || e.key === "2" || e.key === "3")
        keyboard.current.mark(
          e.key === "1" ? "serve" : e.key === "2" ? "shot" : "rally_end",
        );
    };
    window.addEventListener("beforeunload", unload);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("beforeunload", unload);
      window.removeEventListener("keydown", key);
    };
  }, [controller]);
  async function saveWithFocus() {
    const owner = controller.snapshot().video?.id;
    const trigger =
      document.activeElement instanceof HTMLElement
        ? document.activeElement.id
        : "";
    await controller.save();
    if (
      controller.snapshot().video?.id === owner &&
      document.activeElement === document.body
    ) {
      const previous = document.getElementById(trigger);
      const target =
        previous instanceof HTMLButtonElement && previous.disabled
          ? document.getElementById("event-notes")
          : previous;
      (target ?? document.getElementById("event-notes"))?.focus();
    }
  }
  function applyEvent() {
    attempt(() => {
      if (!doc || !state.video) return;
      const v = fields.value,
        kind = v["event-kind"] as Event["kind"],
        f = Number(v["event-frame"]),
        rally = (v["rally-id"] ?? "").trim();
      if (!rally || !Number.isInteger(f) || f < 0 || f >= state.times.length)
        throw Error("Enter a rally and a source frame inside the video.");
      const start =
          v["contact-start"] === "" ? null : Number(v["contact-start"]),
        end = v["contact-end"] === "" ? null : Number(v["contact-end"]);
      if (
        (start === null) !== (end === null) ||
        (start !== null &&
          (!Number.isInteger(start) ||
            !Number.isInteger(end) ||
            start < 0 ||
            end === null ||
            end >= state.times.length ||
            start > f ||
            end < f))
      )
        throw Error(
          "Enter both timing bounds, including the event frame, or clear the interval for exact timing.",
        );
      const existing = doc.events.find((e) => e.id === selected),
        family =
          kind === "shot"
            ? (v["event-family"] as NonNullable<Event["family"]>)
            : null;
      const familyScore = pending
        ? f === pending.frame &&
          kind === pending.kind &&
          (kind !== "shot" || family === pending.family)
          ? pending.score
          : null
        : existing?.frame === f &&
            existing.kind === kind &&
            existing.family === family
          ? (existing.family_score ?? null)
          : null;
      const event: Event = {
        ...existing,
        id: selected ?? crypto.randomUUID(),
        rally_id: rally,
        kind,
        frame: f,
        time_s: state.times[f] ?? 0,
        player_id: kind === "rally_end" ? null : v["event-player"] || null,
        family,
        side:
          kind === "rally_end"
            ? null
            : (v["event-side"] as NonNullable<Event["side"]>),
        status:
          existing?.status === "predicted" || existing?.status === "corrected"
            ? "corrected"
            : "reviewed",
        confidence: existing?.confidence ?? null,
        notes: v["event-notes"] ?? "",
        source_run_id: existing?.source_run_id ?? pending?.source ?? null,
        candidate_id: existing?.candidate_id ?? pending?.candidate ?? null,
        classification_run_id:
          kind === "rally_end"
            ? null
            : (pending?.classification ??
              existing?.classification_run_id ??
              null),
        classification_candidate_id:
          kind === "rally_end"
            ? null
            : (pending?.classificationCandidate ??
              existing?.classification_candidate_id ??
              null),
        family_score: kind === "rally_end" ? null : familyScore,
        contact_start_frame: kind === "rally_end" ? null : start,
        contact_end_frame: kind === "rally_end" ? null : end,
        terminal_start_frame: kind === "rally_end" ? start : null,
        terminal_end_frame: kind === "rally_end" ? end : null,
      };
      edit((d) => {
        d.events = [...d.events.filter((e) => e.id !== event.id), event];
      });
      setSelected(event.id);
      setPending(null);
      controller.notice(
        "Event updated locally. Save annotations to keep your edits.",
      );
    });
  }
  function point(p: Point, ready: boolean) {
    if (labeling) {
      if (!ready) {
        controller.notice(
          "Wait for the exact source frame to load before marking the shuttle.",
          true,
        );
        return;
      }
      edit((d) => {
        d.shuttle_points = [
          ...d.shuttle_points.filter((x) => x.frame !== frame()),
          { frame: frame(), visible: true, ...p },
        ];
      });
      setLabeling(false);
      controller.notice(
        "Shuttle position labeled. Save annotations to keep it.",
      );
      return;
    }
    if (corners === null) return;
    const next = [...corners, p];
    if (next.length < 4) {
      setCorners(next);
      return;
    }
    attempt(() => {
      const range = bounds(
        fields.value["court-start"] ?? "",
        fields.value["court-end"] ?? "",
        state.times.length,
      );
      edit((d) => {
        d.calibrations = [
          ...d.calibrations.filter(
            (c) =>
              c.start_frame !== range.start_frame ||
              c.end_frame !== range.end_frame,
          ),
          { ...range, corners: next },
        ];
      });
      setCorners(null);
      controller.notice(
        "Court corners added. Save annotations to validate the calibration.",
      );
    });
  }
  function addScene() {
    attempt(() => {
      const range = bounds(
        fields.value["scene-start"] ?? "",
        fields.value["scene-end"] ?? "",
        state.times.length,
      );
      if (
        doc?.scene_ranges.some(
          (r) =>
            r.id !== sceneId &&
            r.start_frame < range.end_frame &&
            range.start_frame < r.end_frame,
        )
      )
        throw Error(
          "Reviewed scene ranges must not overlap. Edit or remove the existing range first.",
        );
      edit((d) => {
        d.scene_ranges = [
          ...d.scene_ranges.filter((r) => r.id !== sceneId),
          {
            id: sceneId ?? crypto.randomUUID(),
            ...range,
            scene: fields.value["scene-kind"] as Schema["SceneRange"]["scene"],
            notes: fields.value["scene-notes"] ?? "",
          },
        ].sort((a, b) => a.start_frame - b.start_frame);
      });
      setSceneId(null);
      controller.notice(
        "Scene range added to the draft. Save to apply event exclusions.",
      );
    });
  }
  function addCamera() {
    attempt(() => {
      const f = Number(fields.value["camera-frame"]);
      if (
        !fields.value["camera-frame"] ||
        !Number.isInteger(f) ||
        f <= 0 ||
        f >= state.times.length
      )
        throw Error(
          "Choose a boundary frame after frame 0 and inside the video.",
        );
      const is_cut = fields.value["camera-decision"] === "cut";
      if (
        !is_cut &&
        (state.times[f] ?? 0) - (state.times[f - 1] ?? 0) >
          Math.max(0.1, 2.5 / (state.video?.fps ?? 1)) + 1e-8
      )
        throw Error("Cannot join a source timestamp discontinuity.");
      edit((d) => {
        d.camera_corrections = [
          ...d.camera_corrections.filter((c) => c.frame !== f),
          { frame: f, is_cut, notes: fields.value["camera-notes"] ?? "" },
        ];
      });
      controller.notice(
        "Camera correction added to the draft. Save, then rerun affected tracking windows.",
      );
    });
  }
  function addIdentity() {
    attempt(() => {
      const range = bounds(
          fields.value["identity-start"] ?? "",
          fields.value["identity-end"] ?? "",
          state.times.length,
        ),
        r = state.runs.players;
      if (!r) throw Error("Run player tracking first.");
      if (
        range.start_frame < r.run.start_frame ||
        range.end_frame > r.run.end_frame
      )
        throw Error("Keep the assignment inside the loaded tracking run.");
      const track = Number(fields.value["identity-track"]),
        player = fields.value["identity-player"] ?? "";
      if (!player || !Number.isInteger(track))
        throw Error("Choose a tracker and player.");
      const others =
        doc?.track_assignments.filter(
          (a) =>
            !(
              a.run_id === r.id &&
              a.track_id === track &&
              a.start_frame === range.start_frame &&
              a.end_frame === range.end_frame
            ),
        ) ?? [];
      if (
        others.some(
          (a) =>
            a.run_id === r.id &&
            Math.max(a.start_frame, range.start_frame) <
              Math.min(a.end_frame, range.end_frame) &&
            (a.track_id === track || a.player_id === player),
        )
      )
        throw Error(
          "This overlaps an existing tracker or player assignment. Remove or shorten that assignment first.",
        );
      edit((d) => {
        d.track_assignments = [
          ...others,
          { run_id: r.id, track_id: track, player_id: player, ...range },
        ];
      });
      controller.notice(
        "Player assignment added. Save annotations to keep it.",
      );
    });
  }
  function addReview() {
    attempt(() => {
      const range = bounds(
          fields.value["review-start"] ?? "",
          fields.value["review-end"] ?? "",
          state.times.length,
        ),
        existing = doc?.review_windows.find(
          (w) =>
            w.start_frame === range.start_frame &&
            w.end_frame === range.end_frame,
        ),
        others = doc?.review_windows.filter((w) => w !== existing) ?? [];
      if (
        others.some(
          (w) =>
            Math.max(w.start_frame, range.start_frame) <
            Math.min(w.end_frame, range.end_frame),
        )
      )
        throw Error(
          "Reviewed clips cannot overlap. Remove the old clip before changing its range.",
        );
      edit((d) => {
        d.review_windows = [
          ...others,
          {
            id: existing?.id ?? crypto.randomUUID(),
            ...range,
            contacts_complete: complete,
            serves_complete: servesComplete,
            rally_ends_complete: rallyEndsComplete,
            scene: fields.value["review-scene"] as NonNullable<
              Schema["ReviewWindow"]["scene"]
            >,
            notes: fields.value["review-notes"] ?? "",
          },
        ];
      });
      controller.notice(
        "Reviewed clip added. Save annotations before measuring accuracy.",
      );
    });
  }
  function useCandidate(
    stage: "contacts" | "recognition" | "rallies",
    c: ObjectData,
    r: LoadedRun,
  ) {
    const f = num(c.frame);
    if (
      stage === "recognition" &&
      c.status !== "predicted" &&
      !array(c.top_classes).length
    ) {
      seek(f);
      controller.notice(str(c.reason, "More tracking context is needed."));
      return;
    }
    if (stage === "recognition" && c.event_id)
      editEvent.current(str(c.event_id));
    else reset(stage === "rallies" ? (c.kind as Event["kind"]) : "shot", f);
    const hitter = c.hitter_hint
      ? str(object(c.hitter_hint).player_id)
      : stage === "contacts" && doc
        ? sourcePlayer(doc, str(r.run.player_run_id), c.track_id, f)
        : "";
    fields.set((v) => ({
      ...v,
      "event-frame": String(f),
      "event-player":
        stage === "rallies"
          ? ""
          : stage === "contacts"
            ? hitter
            : v["event-player"] || hitter,
      "event-kind":
        stage === "recognition" && c.status === "predicted"
          ? str(c.kind, "shot")
          : stage === "rallies"
            ? str(c.kind, "serve")
            : "shot",
      "event-family":
        stage === "recognition" && c.status === "predicted"
          ? str(c.family, "unknown")
          : (v["event-family"] ?? "unknown"),
      "event-side":
        stage === "recognition" &&
        hitter &&
        (!v["event-player"] || v["event-player"] === hitter) &&
        v["event-side"] === "unknown" &&
        sides.includes(c.side as (typeof sides)[number])
          ? str(c.side, "unknown")
          : (v["event-side"] ?? "unknown"),
      "contact-start": String(
        stage === "recognition"
          ? (c.contact_start_frame ?? v["contact-start"] ?? "")
          : stage === "rallies" || c.timing === "uncertain_interval"
            ? (c.start_frame ?? "")
            : "",
      ),
      "contact-end": String(
        stage === "recognition"
          ? (c.contact_end_frame ?? v["contact-end"] ?? "")
          : stage === "rallies" || c.timing === "uncertain_interval"
            ? (c.end_frame ?? "")
            : "",
      ),
      "event-notes":
        stage === "recognition"
          ? (v["event-notes"] ?? "")
          : stage === "rallies"
            ? `Experimental ${c.kind === "serve" ? "serve" : "rally-end"} suggestion; verify the source and uncertain timing.${c.evidence && object(c.evidence).settled_region === "near_court_surround" ? " Shuttle settled near a court edge; landing, fault and line call are unverified." : ""}`
            : `Contact suggestion: ${str(c.reason)}. Verify contact, hitter, and stroke.`,
    }));
    setPending({
      source:
        stage === "recognition"
          ? c.contact_candidate_id
            ? str(r.run.contacts_run_id) || null
            : null
          : r.id,
      candidate:
        stage === "recognition"
          ? str(c.contact_candidate_id) || null
          : str(c.id),
      classification: stage === "recognition" ? r.id : null,
      classificationCandidate: stage === "recognition" ? str(c.id) : null,
      frame: f,
      family: typeof c.family === "string" ? c.family : null,
      kind: str(c.kind, "shot"),
      score: typeof c.family_score === "number" ? c.family_score : null,
    });
    seek(f);
    controller.notice(
      "Suggestion loaded into the editor. Review it, then add or update and save the event.",
    );
  }
  const current = state.video,
    active = state.jobs.find((j) => ["queued", "running"].includes(j.status)),
    run = state.runs.players,
    plan = state.plan;
  const eventKind = fields.value["event-kind"] ?? "shot",
    analysisJob = state.jobs.find(
      (j) => j.video_id === current?.id && j.kind === "analysis",
    ),
    planState = plan ? str(plan.state) : "",
    planJob = plan?.job ? object(plan.job) : null;
  const stale = controller.planStale();
  const trackIds = [
    ...new Set(
      run?.run.frames
        .flatMap((f) => objects(f.players).map((p) => p.track_id))
        .filter((t) => typeof t === "number") ?? [],
    ),
  ].map(String);
  const status = (stage: string) => {
    const latest = state.jobs.find(
      (j) => j.video_id === current?.id && j.kind === stage,
    );
    if (latest?.status === "failed") return latest.message;
    if (latest && ["queued", "running"].includes(latest.status))
      return `${pretty(stage)} · ${Math.round(latest.progress * 100)}%`;
    const r = state.runs[stage as keyof typeof state.runs];
    if (!r)
      return stage === "players"
        ? "No tracking run loaded"
        : stage === "shuttle"
          ? "No shuttle run loaded"
          : "Track players and the shuttle first.";
    if (stage === "players")
      return `${num(r.run.processed_frames)} frames · ${num(r.run.inference_fps)} fps · ${str(r.run.device)}${r.run.calibrated ? " · court filter" : ""}`;
    if (stage === "shuttle")
      return `${num(r.run.visible_frames)}/${num(r.run.processed_frames)} frames visible · ${num(r.run.inference_fps)} fps · raw detections`;
    return `${num(r.run.candidate_count)} experimental suggestions · saved revision ${num(r.run.annotation_revision)}`;
  };
  return (
    <div className="editor-app">
      <aside className="sidebar">
        <div className="brand">
          Court Notes<small>REVIEW EDITOR</small>
        </div>
        <a href="/library">Imports and match library ↗</a>
        <p>Automatic annotation accuracy is not established.</p>
        <div className="section-label">
          VIDEO LIBRARY <span id="library-count">{state.videos.length}</span>
        </div>
        <div id="library">
          {state.videos.map((v) => (
            <button
              key={v.id}
              className={`library-item ${v.id === current?.id ? "active" : ""}`}
              data-video={v.id}
              onClick={() => {
                void controller.select(v.id);
              }}
            >
              <img
                src={`/api/videos/${encodeURIComponent(v.id)}/image/poster.jpg`}
                alt=""
              />
              <strong>{v.name}</strong>
              <small>
                {v.mode} · {clock(v.duration_s)}
              </small>
            </button>
          ))}
        </div>
        <button
          onClick={() => {
            void controller.library().catch(controller.handle);
          }}
        >
          Refresh library
        </button>
      </aside>
      <main>
        <header>
          <div>
            <p className="eyebrow">MATCH WORKSPACE · REVIEW EDITOR</p>
            <h1 id="title">{current?.name ?? "Review your match"}</h1>
            <p id="video-info">
              {current
                ? `${pretty(current.mode)} · ${current.width} × ${current.height} · ${current.fps.toFixed(2).replace(".00", "")} fps · ${clock(current.duration_s)} · ${current.frame_count.toLocaleString()} source frames`
                : "Import a video to begin."}
            </p>
          </div>
          <div>
            <span id="save-state">
              {draft?.saving
                ? "Saving snapshot…"
                : draft?.dirty
                  ? "Unsaved edits"
                  : `Saved · revision ${draft?.revision ?? 0}`}
            </span>
            <button
              id="save"
              disabled={!draft?.dirty || draft.saving}
              onClick={() => {
                void saveWithFocus();
              }}
            >
              Save annotations
            </button>
            <button
              id="reload-annotations"
              disabled={!current || Boolean(draft?.saving)}
              onClick={() => {
                void controller.reload();
              }}
            >
              Reload saved revision
            </button>
            <button
              id="discard-edits"
              disabled={!draft?.dirty || draft.saving}
              onClick={() => {
                controller.drafts.discard();
                controller.notice("Local edits discarded.");
                requestAnimationFrame(() =>
                  document.getElementById("event-notes")?.focus(),
                );
              }}
            >
              Discard edits
            </button>
          </div>
        </header>
        <div
          id="notice"
          className={state.error ? "error" : ""}
          role="status"
          aria-live="polite"
        >
          {state.loading ? "Loading source and annotations…" : state.notice}
        </div>
        {!current && (
          <section id="onboarding">
            <h2>Bring your match into view.</h2>
            <p>
              Choose a match from the library, or add footage from the import
              workflow.
            </p>
            <a href="/library">Open imports and jobs</a>
          </section>
        )}
        <output hidden data-testid="editor-renders">
          {renders.current}
        </output>
        {current && doc && (
          <div id="workspace">
            <div className="workspace-grid">
              <section className="review-panel">
                <div className="panel-bar">
                  <span>VIDEO REVIEW</span>
                  <label className="inline">
                    <input
                      id="show-tracks"
                      type="checkbox"
                      checked={showTracks}
                      onChange={(e) => setShowTracks(e.target.checked)}
                    />
                    Tracks
                  </label>
                  <label className="inline">
                    <input
                      id="show-shuttle"
                      type="checkbox"
                      checked={showShuttle}
                      onChange={(e) => setShowShuttle(e.target.checked)}
                    />
                    Shuttle
                  </label>
                  <a
                    id="audit"
                    href={`/api/videos/${encodeURIComponent(current.id)}/image/contact-sheet.jpg`}
                    target="_blank"
                    rel="noopener"
                  >
                    Contact sheet ↗
                  </a>
                </div>
                <Playback
                  controller={controller}
                  actions={actions}
                  corners={corners}
                  onPoint={point}
                  showTracks={showTracks}
                  showShuttle={showShuttle}
                />
                <div className="playback-options">
                  <button
                    id="prepare-playback"
                    disabled={state.playbackBusy || Boolean(state.playbackUrl)}
                    onClick={() => controller.preparePlayback()}
                  >
                    {state.playbackUrl ? "Playback ready" : "Prepare playback"}
                  </button>
                  <small id="playback-status" role="status">
                    {state.playbackBusy
                      ? "Preparing playback… Exact-frame review remains available."
                      : state.playbackUrl
                        ? "Prepared playback · source frame timing preserved"
                        : "Video not playing smoothly? Prepare a compatible copy."}
                  </small>
                </div>
                <div className="mark-bar">
                  <span>MARK CURRENT FRAME</span>
                  {kinds.map((kind, i) => (
                    <button
                      key={kind}
                      data-mark={kind}
                      onClick={() => mark(kind)}
                    >
                      {pretty(kind)} <kbd>{i + 1}</kbd>
                    </button>
                  ))}
                </div>
                <div className="tools-grid">
                  <section className="tool-card">
                    <h2>COURT CALIBRATION</h2>
                    <p>Click far left, far right, near right, near left.</p>
                    <label>
                      <input
                        id="auto-court"
                        type="checkbox"
                        checked={auto}
                        onChange={(e) => setAuto(e.target.checked)}
                      />
                      Find court automatically when needed
                    </label>
                    <div className="row">
                      <Field
                        id="court-start"
                        label="Start frame"
                        fields={fields}
                      />
                      <Field
                        id="court-end"
                        label="End frame (exclusive)"
                        fields={fields}
                      />
                    </div>
                    <button
                      id="calibrate"
                      onClick={() => {
                        setLabeling(false);
                        setCorners(corners === null ? [] : null);
                        seek(frame());
                      }}
                    >
                      {corners === null
                        ? "Select 4 corners"
                        : "Cancel selection"}
                    </button>
                    <button
                      id="clear-court"
                      onClick={() =>
                        edit((d) => {
                          d.calibrations = d.calibrations.filter(
                            (c) =>
                              c.start_frame !==
                                Number(fields.value["court-start"]) ||
                              c.end_frame !== Number(fields.value["court-end"]),
                          );
                        })
                      }
                    >
                      Clear range
                    </button>
                  </section>
                  <section className="tool-card">
                    <h2>PLAYER & SHUTTLE TRACKING</h2>
                    <Field
                      id="player-model"
                      label="Player model"
                      fields={fields}
                      options={["small", "nano"]}
                    />
                    <Field
                      id="track-duration"
                      label="Duration"
                      fields={fields}
                      options={["5", "10", "30"]}
                    />
                    <button
                      id="track"
                      disabled={Boolean(active)}
                      onClick={() =>
                        controller.track("players", {
                          duration: Number(fields.value["track-duration"]),
                          model: fields.value["player-model"] as
                            "small" | "nano",
                          auto,
                        })
                      }
                    >
                      Track players
                    </button>
                    <small id="track-status">{status("players")}</small>
                    <button
                      id="track-shuttle"
                      disabled={Boolean(active)}
                      onClick={() =>
                        controller.track("shuttle", {
                          duration: Number(fields.value["track-duration"]),
                          model: "small",
                          auto,
                        })
                      }
                    >
                      Track shuttle
                    </button>
                    <button
                      id="detect-contacts"
                      disabled={Boolean(active) || !state.runs.shuttle}
                      onClick={() => controller.suggest("contacts", audio)}
                    >
                      Suggest contacts
                    </button>
                    <label>
                      <input
                        id="contact-audio"
                        type="checkbox"
                        checked={audio}
                        onChange={(e) => setAudio(e.target.checked)}
                      />
                      Use audio support (experimental; requires player tracking)
                    </label>
                    <small id="audio-status">
                      {state.runs.contacts?.run.audio
                        ? object(state.runs.contacts.run.audio).status ===
                          "available"
                          ? "Audio support is experimental. Verify the sound source and contact interval."
                          : "No usable audio in this window. Showing visual suggestions."
                        : ""}
                    </small>
                    <small id="shuttle-status">{status("shuttle")}</small>
                  </section>
                </div>
                <Panel id="analysis-panel" title="Full-match processing">
                  <p>
                    Process all source frames in overlapping windows. Review
                    proposals and unresolved labels. Tracker IDs remain local to
                    a window; linked actor hints remain unreviewed.
                  </p>
                  <label>
                    <input
                      id="analysis-recognize"
                      type="checkbox"
                      checked={recognize}
                      onChange={(e) => setRecognize(e.target.checked)}
                    />
                    Include experimental singles shot labels (doubles labels
                    unavailable)
                  </label>
                  <button
                    id="process-analysis"
                    disabled={Boolean(active)}
                    onClick={() =>
                      controller.process({
                        player_model: fields.value["player-model"] as
                          "small" | "nano",
                        auto_calibrate: auto,
                        recognize,
                      })
                    }
                  >
                    Process / resume full match
                  </button>
                  <button
                    id="pause-analysis"
                    disabled={
                      !analysisJob ||
                      !["queued", "running"].includes(analysisJob.status) ||
                      analysisJob.cancel_requested
                    }
                    onClick={() => controller.pause()}
                  >
                    Pause
                  </button>
                  <small
                    id="analysis-status"
                    data-job-id={analysisJob?.id}
                    data-job-status={planJob ? str(planJob.status) : undefined}
                  >
                    {stale
                      ? "Camera, scene or court context changed. Save, then process again with the current context."
                      : plan
                        ? `${planState === "completed" ? "Processing complete; review proposals and unresolved labels" : planJob?.cancel_requested && ["queued", "running"].includes(str(planJob.status)) ? "Pausing…" : planState === "interrupted" ? "Paused; resume to reuse completed stages" : planState === "failed" ? `Stopped: ${str(plan.error) || str(planJob?.message)}` : `Processing ${plan.active ? str(object(plan.active).stage, "source") : "source"}`} · ${Math.round(num(planJob?.progress) * 100)}%${plan.identities ? ` · ${num(object(plan.identities).linked_actor_count)} overlap-linked actor groups (unreviewed)` : ""}`
                        : "Process all source frames; completed stages are reused after a pause or restart."}
                  </small>
                  <label>
                    Review window
                    <select
                      id="analysis-windows"
                      value={part}
                      onChange={(e) => setPart(Number(e.target.value))}
                    >
                      {objects(plan?.parts).map((p) => {
                        const w = object(p.window);
                        return (
                          <option key={num(w.index)} value={num(w.index)}>
                            {clock(state.times[num(w.core_start_frame)] ?? 0)}–
                            {clock(
                              state.times[num(w.core_end_frame)] ??
                                current.duration_s,
                            )}{" "}
                            · {Object.keys(object(p.stages)).length}/5 stages
                          </option>
                        );
                      })}
                    </select>
                  </label>
                  <button
                    id="review-analysis"
                    disabled={!objects(plan?.parts).length || stale}
                    onClick={() => {
                      const target = controller.reviewPart(part);
                      if (target !== undefined) seek(target);
                    }}
                  >
                    Review window
                  </button>
                  <button
                    id="leave-analysis"
                    disabled={!state.analysisEnabled}
                    onClick={() => controller.leave()}
                  >
                    Use window tools
                  </button>
                </Panel>
                <Panel id="camera-panel" title="Camera changes">
                  <p>
                    Camera boundaries, replay, live play and rally boundaries
                    need separate review. Saved corrections invalidate affected
                    derived results.
                  </p>
                  <button
                    id="scan-segments"
                    disabled={Boolean(active)}
                    onClick={() => controller.suggest("segments")}
                  >
                    Scan camera changes
                  </button>
                  <small id="segment-status">
                    {state.runs.segments
                      ? `${objects(state.runs.segments.run.boundaries).length} possible boundaries · review scenes separately`
                      : "Scan camera changes across the full video."}
                  </small>
                  <div
                    id="camera-boundaries"
                    data-run-id={state.runs.segments?.id}
                  >
                    {[
                      ...new Set([
                        ...objects(state.runs.segments?.run.boundaries).map(
                          (b) => num(b.frame),
                        ),
                        ...doc.camera_corrections.map((c) => c.frame),
                      ]),
                    ]
                      .sort((a, b) => a - b)
                      .map((f) => {
                        const correction = doc.camera_corrections.find(
                            (c) => c.frame === f,
                          ),
                          raw = objects(
                            state.runs.segments?.run.boundaries,
                          ).find((c) => num(c.frame) === f);
                        return (
                          <div className="boundary-row" key={f}>
                            <button
                              data-boundary={f}
                              onClick={() => {
                                fields.set((v) => ({
                                  ...v,
                                  "camera-frame": String(f),
                                  "camera-decision":
                                    correction?.is_cut === false
                                      ? "not_cut"
                                      : "cut",
                                  "camera-notes": correction?.notes ?? "",
                                }));
                                seek(f);
                                controller.notice(
                                  "Possible camera boundary. Step back and forward to inspect it; this is not a rally boundary.",
                                );
                              }}
                            >
                              {clock(state.times[f] ?? 0)} · frame {f} ·{" "}
                              {correction
                                ? correction.is_cut
                                  ? "Confirmed cut"
                                  : "Rejected cut"
                                : pretty(raw?.reason)}
                            </button>
                            {correction && (
                              <button
                                data-reset-cut={f}
                                onClick={() =>
                                  edit((d) => {
                                    d.camera_corrections =
                                      d.camera_corrections.filter(
                                        (c) => c.frame !== f,
                                      );
                                  })
                                }
                              >
                                Remove correction
                              </button>
                            )}
                          </div>
                        );
                      })}
                  </div>
                  <div className="row">
                    <Field
                      id="camera-frame"
                      label="First frame of new view"
                      fields={fields}
                    />
                    <Field
                      id="camera-decision"
                      label="Decision"
                      fields={fields}
                      options={["cut", "not_cut"]}
                    />
                  </div>
                  <Field
                    id="camera-notes"
                    label="Review notes"
                    fields={fields}
                    type="text"
                  />
                  <button
                    id="camera-use-frame"
                    onClick={() => fields.put("camera-frame", String(frame()))}
                  >
                    Use current frame
                  </button>
                  <button id="camera-apply" onClick={addCamera}>
                    Add / update correction
                  </button>
                  <div className="row">
                    <Field
                      id="scene-start"
                      label="Scene start"
                      fields={fields}
                    />
                    <Field
                      id="scene-end"
                      label="End (exclusive)"
                      fields={fields}
                    />
                    <Field
                      id="scene-kind"
                      label="Scene"
                      fields={fields}
                      options={["live", "replay", "non_play", "unknown"]}
                    />
                  </div>
                  <Field
                    id="scene-notes"
                    label="Scene notes"
                    fields={fields}
                    type="text"
                  />
                  <button id="add-scene" onClick={addScene}>
                    {sceneId ? "Update scene range" : "Add scene range"}
                  </button>
                  <p>
                    Replay, non-play and explicitly unknown scenes are excluded
                    from event suggestions. Live status does not declare
                    contacts complete.
                  </p>
                  <div id="scene-ranges">
                    {doc.scene_ranges.map((r) => (
                      <div className="boundary-row" key={r.id}>
                        <button
                          data-edit-scene={r.id}
                          onClick={() => {
                            setSceneId(r.id);
                            fields.set((v) => ({
                              ...v,
                              "scene-start": String(r.start_frame),
                              "scene-end": String(r.end_frame),
                              "scene-kind": r.scene,
                              "scene-notes": r.notes ?? "",
                            }));
                            seek(r.start_frame);
                          }}
                        >
                          Frames {r.start_frame}–{r.end_frame - 1} ·{" "}
                          {pretty(r.scene)}
                        </button>
                        <button
                          data-remove-scene={r.id}
                          onClick={() => {
                            edit((d) => {
                              d.scene_ranges = d.scene_ranges.filter(
                                (x) => x.id !== r.id,
                              );
                            });
                            if (sceneId === r.id) setSceneId(null);
                            controller.notice(
                              "Scene range removed from the draft. Save, then request new contacts and shot labels to restore omitted suggestions.",
                            );
                          }}
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                </Panel>
                {(["contacts", "rallies", "recognition"] as const).map(
                  (stage) => (
                    <Suggestions
                      key={stage}
                      stage={stage}
                      controller={controller}
                      doc={doc}
                      loaded={state.runs[stage] ?? null}
                      onChoose={(c) => {
                        const r = state.runs[stage];
                        if (r) useCandidate(stage, c, r);
                      }}
                      status={status(stage)}
                      disabled={
                        Boolean(active) ||
                        !run ||
                        !state.runs.shuttle ||
                        (stage === "recognition" && current.mode !== "singles")
                      }
                    />
                  ),
                )}
                <Panel title="Player names, teams & handedness">
                  <div id="players">
                    {doc.players.map((p) => (
                      <div className="player-row" key={p.id}>
                        <strong>{p.id}</strong>
                        <input
                          data-player={p.id}
                          data-field="name"
                          aria-label={`Player ${p.id} name`}
                          value={p.name}
                          maxLength={100}
                          onChange={(e) =>
                            edit((d) => {
                              const player = d.players.find(
                                (x) => x.id === p.id,
                              );
                              if (player) player.name = e.target.value;
                            })
                          }
                        />
                        <select
                          data-player={p.id}
                          data-field="team"
                          aria-label={`Player ${p.id} team`}
                          value={p.team}
                          onChange={(e) =>
                            edit((d) => {
                              const player = d.players.find(
                                (x) => x.id === p.id,
                              );
                              if (player)
                                player.team = e.target.value as "T1" | "T2";
                            })
                          }
                        >
                          {["T1", "T2"].map((t) => (
                            <option key={t}>{t}</option>
                          ))}
                        </select>
                        <select
                          data-player={p.id}
                          data-field="handedness"
                          aria-label={`Player ${p.id} handedness`}
                          value={p.handedness ?? "unknown"}
                          onChange={(e) =>
                            edit((d) => {
                              const player = d.players.find(
                                (x) => x.id === p.id,
                              );
                              if (player)
                                player.handedness = e.target.value as
                                  "unknown" | "left" | "right";
                            })
                          }
                        >
                          {["unknown", "right", "left"].map((t) => (
                            <option key={t}>{t}</option>
                          ))}
                        </select>
                      </div>
                    ))}
                  </div>
                </Panel>
                <Panel id="identity-panel" title="Assign tracks to players">
                  <p>
                    Confirm identities within each source-frame range; inspect
                    crossings and end changes.
                  </p>
                  <div className="row">
                    <Field
                      id="identity-track"
                      label="Tracker"
                      fields={fields}
                      options={trackIds}
                    />
                    <label>
                      Player
                      <select
                        id="identity-player"
                        value={fields.value["identity-player"] ?? ""}
                        onChange={(e) =>
                          fields.put("identity-player", e.target.value)
                        }
                      >
                        {doc.players.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name} ({p.id})
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <div className="row">
                    <Field
                      id="identity-start"
                      label="Start frame"
                      fields={fields}
                    />
                    <Field
                      id="identity-end"
                      label="End frame (exclusive)"
                      fields={fields}
                    />
                  </div>
                  <button
                    id="assign-identity"
                    disabled={!run || !trackIds.length}
                    onClick={addIdentity}
                  >
                    Assign player
                  </button>
                  <div id="identity-list">
                    {doc.track_assignments.map((a, i) => (
                      <div
                        className="review-row"
                        key={`${a.run_id}:${a.track_id}:${a.start_frame}`}
                      >
                        <span>
                          Player {a.player_id} ← Track {a.track_id}
                          <small>
                            Frames {a.start_frame}–{a.end_frame - 1} ·{" "}
                            {a.run_id === run?.id
                              ? "loaded run"
                              : "another run"}
                          </small>
                        </span>
                        <button
                          data-remove-assignment={i}
                          aria-label={`Remove assignment ${i + 1}`}
                          onClick={() =>
                            edit((d) => {
                              d.track_assignments.splice(i, 1);
                            })
                          }
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                </Panel>
                <Panel id="review-panel" title="Reviewed clips & accuracy">
                  <p>
                    Inspect the whole clip using native source frames. Declare
                    contact, serve and rally-ending coverage separately, only
                    after labeling every event of that kind, including missed
                    proposals.
                  </p>
                  <div className="row">
                    <Field
                      id="review-start"
                      label="Start frame"
                      fields={fields}
                    />
                    <Field
                      id="review-end"
                      label="End frame (exclusive)"
                      fields={fields}
                    />
                  </div>
                  <Field
                    id="review-scene"
                    label="Footage"
                    fields={fields}
                    options={["unknown", "live", "replay"]}
                  />
                  <label>
                    <input
                      id="review-complete"
                      type="checkbox"
                      checked={complete}
                      onChange={(e) => setComplete(e.target.checked)}
                    />
                    Every contact in this clip is labeled
                  </label>
                  <label>
                    <input
                      id="review-serves-complete"
                      type="checkbox"
                      checked={servesComplete}
                      onChange={(e) => setServesComplete(e.target.checked)}
                    />
                    Every serve in this clip is labeled
                  </label>
                  <label>
                    <input
                      id="review-rally-ends-complete"
                      type="checkbox"
                      checked={rallyEndsComplete}
                      onChange={(e) => setRallyEndsComplete(e.target.checked)}
                    />
                    Every rally ending in this clip is labeled
                  </label>
                  <small>
                    A complete contact review does not establish complete serve
                    or ending labels. Keep uncertain timing bounds; a clip edge
                    or last stroke alone does not establish a boundary.
                  </small>
                  <Field
                    id="review-notes"
                    label="Review notes"
                    fields={fields}
                    type="text"
                  />
                  <button id="add-review" onClick={addReview}>
                    Save reviewed clip
                  </button>
                  <div id="review-list">
                    {doc.review_windows.map((w) => (
                      <div className="review-row" key={w.id}>
                        <button
                          data-load-review={w.id}
                          onClick={() => {
                            fields.set((v) => ({
                              ...v,
                              "review-start": String(w.start_frame),
                              "review-end": String(w.end_frame),
                              "review-scene": w.scene ?? "unknown",
                              "review-notes": w.notes ?? "",
                            }));
                            setComplete(w.contacts_complete ?? false);
                            setServesComplete(w.serves_complete ?? false);
                            setRallyEndsComplete(
                              w.rally_ends_complete ?? false,
                            );
                            seek(w.start_frame);
                          }}
                        >
                          Frames {w.start_frame}–{w.end_frame - 1}
                          <small>
                            {w.scene} ·{" "}
                            {w.contacts_complete
                              ? "all contacts labeled"
                              : "incomplete"}
                            {w.serves_complete && " · all serves labeled"}
                            {w.rally_ends_complete && " · all endings labeled"}
                          </small>
                        </button>
                        <button
                          data-remove-review={w.id}
                          aria-label="Remove reviewed clip"
                          onClick={() =>
                            edit((d) => {
                              d.review_windows = d.review_windows.filter(
                                (x) => x.id !== w.id,
                              );
                            })
                          }
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                  <hr />
                  <p>
                    Hide model overlays and label separate source frames. Skip
                    ambiguous positions.
                  </p>
                  <button
                    id="label-shuttle"
                    onClick={() => {
                      setCorners(null);
                      setLabeling(!labeling);
                      if (!labeling) {
                        setShowShuttle(false);
                        seek(frame());
                      }
                    }}
                  >
                    {labeling ? "Cancel shuttle mark" : "Mark visible shuttle"}
                  </button>
                  <button
                    id="label-invisible"
                    onClick={() => {
                      seek(frame());
                      edit((d) => {
                        d.shuttle_points = [
                          ...d.shuttle_points.filter(
                            (p) => p.frame !== frame(),
                          ),
                          { frame: frame(), visible: false, x: null, y: null },
                        ];
                      });
                      setLabeling(false);
                    }}
                  >
                    Shuttle not visible
                  </button>
                  <button
                    id="clear-shuttle-label"
                    onClick={() => {
                      edit((d) => {
                        d.shuttle_points = d.shuttle_points.filter(
                          (p) => p.frame !== frame(),
                        );
                      });
                      setLabeling(false);
                    }}
                  >
                    Clear frame label
                  </button>
                  <hr />
                  <button
                    id="evaluate"
                    onClick={() => {
                      void controller.evaluate();
                    }}
                  >
                    Measure saved labels
                  </button>
                  <Evaluation
                    report={state.report}
                    dirty={Boolean(draft.dirty)}
                    videoId={current.id}
                  />
                </Panel>
              </section>
              <aside className="events-panel">
                <div className="panel-bar">
                  <span>EVENT EDITOR</span>
                  <span id="event-count">
                    {doc.events.length}{" "}
                    {doc.events.length === 1 ? "event" : "events"}
                  </span>
                </div>
                <form
                  id="event-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    applyEvent();
                  }}
                >
                  <p id="editor-hint">
                    {pending
                      ? `Model suggestion at frame ${pending.frame}; verify family, hitter, contact time and stroke side before updating.`
                      : selected
                        ? `Editing ${pretty(eventKind)} · frame ${fields.value["event-frame"]}`
                        : `New ${pretty(eventKind)} at the current source frame.`}
                  </p>
                  <Field
                    id="rally-id"
                    label="Rally"
                    fields={fields}
                    type="text"
                    required
                  />
                  <label>
                    Event
                    <select
                      id="event-kind"
                      value={eventKind}
                      onChange={(e) =>
                        fields.set((v) => ({
                          ...v,
                          "event-kind": e.target.value,
                          "contact-start": "",
                          "contact-end": "",
                        }))
                      }
                    >
                      {kinds.map((k) => (
                        <option key={k} value={k}>
                          {k === "serve" ? "Serve / rally start" : pretty(k)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <Field
                    id="event-frame"
                    label="Source frame"
                    fields={fields}
                    max={current.frame_count - 1}
                    required
                  />
                  <label id="player-label" hidden={eventKind === "rally_end"}>
                    Hitter
                    <select
                      id="event-player"
                      value={fields.value["event-player"] ?? ""}
                      onChange={(e) =>
                        fields.put("event-player", e.target.value)
                      }
                    >
                      <option value="">Unknown hitter</option>
                      {doc.players.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} ({p.id})
                        </option>
                      ))}
                    </select>
                  </label>
                  <details
                    id="contact-uncertainty"
                    open={
                      Boolean(
                        fields.value["contact-start"] ||
                        fields.value["contact-end"],
                      ) || undefined
                    }
                  >
                    <summary id="timing-uncertainty-title">
                      {eventKind === "rally_end" ? "Rally end" : "Contact"}{" "}
                      timing uncertainty
                    </summary>
                    <p id="timing-uncertainty-help">
                      {eventKind === "rally_end"
                        ? "Keep the possible terminal frame range when ground contact or a fault is obscured. The final racket contact alone is not a rally ending."
                        : "When contact timing is unclear, keep the possible frame range. Clear it once you can identify one source frame."}
                    </p>
                    <div className="row">
                      <Field
                        id="contact-start"
                        label="Earliest frame"
                        fields={fields}
                      />
                      <Field
                        id="contact-end"
                        label="Latest frame (inclusive)"
                        fields={fields}
                      />
                    </div>
                    <button
                      id="clear-contact-interval"
                      type="button"
                      onClick={() =>
                        fields.set((v) => ({
                          ...v,
                          "contact-start": "",
                          "contact-end": "",
                        }))
                      }
                    >
                      Use exact{" "}
                      {eventKind === "rally_end" ? "rally-end" : "contact"}{" "}
                      frame
                    </button>
                  </details>
                  <div id="family-label" hidden={eventKind !== "shot"}>
                    <Field
                      id="event-family"
                      label="Shot family"
                      fields={fields}
                      options={families}
                    />
                  </div>
                  <div id="side-label" hidden={eventKind === "rally_end"}>
                    <Field
                      id="event-side"
                      label="Stroke side"
                      fields={fields}
                      options={sides}
                    />
                  </div>
                  <Field
                    id="event-notes"
                    label="Notes"
                    fields={fields}
                    type="textarea"
                  />
                  <div className="row">
                    <button id="apply-event" type="submit">
                      {selected ? "Update event" : "Add event"}
                    </button>
                    <button
                      id="new-event"
                      type="button"
                      onClick={() => reset()}
                    >
                      New
                    </button>
                    <button
                      id="delete-event"
                      type="button"
                      hidden={!selected}
                      onClick={() => {
                        edit((d) => {
                          d.events = d.events.filter((e) => e.id !== selected);
                        });
                        reset();
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </form>
                <Timeline
                  doc={doc}
                  times={state.times}
                  count={current.frame_count}
                  selected={selected}
                  edit={stableEdit}
                />
                <div className="export-bar">
                  <span>EXPORT REVIEWED DATA</span>
                  {["json", "csv"].map((format) => (
                    <a
                      key={format}
                      id={`export-${format}`}
                      href={`/api/videos/${encodeURIComponent(current.id)}/export?format=${format}`}
                      onClick={(e) => {
                        if (draft.dirty || draft.saving) {
                          e.preventDefault();
                          controller.notice(
                            "Save annotations before exporting.",
                            true,
                          );
                        }
                      }}
                    >
                      {format.toUpperCase()} ↗
                    </a>
                  ))}
                </div>
                <ExportPanel
                  videoId={current.id}
                  revision={draft.revision}
                  dirty={draft.dirty}
                  saving={draft.saving}
                />
              </aside>
            </div>
            <footer>
              ← → Frame step · Space Play / pause · 1 2 3 Mark events · Ctrl S
              Save<span>Source timestamps preserved</span>
            </footer>
          </div>
        )}
      </main>
    </div>
  );
}
function Suggestions({
  stage,
  controller,
  doc,
  loaded,
  onChoose,
  status,
  disabled,
}: {
  stage: "contacts" | "recognition" | "rallies";
  controller: EditorController;
  doc: Document;
  loaded: LoadedRun | null;
  onChoose: (c: ObjectData) => void;
  status: string;
  disabled: boolean;
}) {
  const candidates = ownedCandidates(loaded?.run ?? null),
    run = loaded?.run ?? null;
  let stale = false,
    courtStale = false;
  if (run) {
    if (stage === "rallies")
      stale =
        JSON.stringify(
          contextSignature(
            doc,
            num(run.context_start_frame),
            num(run.context_end_frame),
            run.court_context ? object(run.court_context) : null,
          ),
        ) !== JSON.stringify(run.context_signature);
    else {
      stale =
        JSON.stringify(cameraSignature(doc, run.start_frame, run.end_frame)) !==
        JSON.stringify(run.camera_review_signature ?? []);
      courtStale = courtChanged(doc, run);
    }
  }
  const id =
    stage === "contacts"
      ? "candidates"
      : stage === "recognition"
        ? "stroke-predictions"
        : "rally-candidates";
  return (
    <section
      className="suggestions-panel"
      id={
        stage === "recognition"
          ? "recognition-tools"
          : stage === "rallies"
            ? "rally-tools"
            : undefined
      }
    >
      <div className="section-label">
        {stage === "contacts"
          ? "CONTACT SUGGESTIONS"
          : stage === "recognition"
            ? "SHOT LABEL SUGGESTIONS"
            : "RALLY BOUNDARIES"}{" "}
        <span
          id={
            stage === "contacts"
              ? "candidate-count"
              : stage === "recognition"
                ? "stroke-count"
                : "rally-count"
          }
        >
          {candidates.length}
        </span>
      </div>
      <p>
        Experimental proposals require source review. Saved labels are never
        replaced automatically. Missing proposals remain unresolved.
      </p>
      {stage !== "contacts" && (
        <button
          id={stage === "recognition" ? "recognize" : "suggest-rallies"}
          disabled={disabled}
          onClick={() => controller.suggest(stage)}
        >
          {stage === "recognition"
            ? "Suggest shot labels"
            : "Suggest rally boundaries"}
        </button>
      )}
      {stage !== "contacts" && (
        <small
          id={stage === "recognition" ? "recognition-status" : "rally-status"}
        >
          {stage === "recognition" &&
          controller.snapshot().video?.mode !== "singles"
            ? "The current learned family model supports singles. Doubles recognition remains in development."
            : status}
        </small>
      )}
      <div id={id}>
        {candidates.map((c) => {
          const frame = num(c.frame),
            source = c.event_id
              ? doc.events.find((e) => e.id === c.event_id)
              : null,
            changed = Boolean(
              c.event_id && (!source || source.frame !== frame),
            ),
            added = doc.events.some((e) =>
              stage === "recognition"
                ? e.classification_run_id === loaded?.id &&
                  e.classification_candidate_id === c.id
                : e.source_run_id === loaded?.id && e.candidate_id === c.id,
            );
          const start = num(
              stage === "recognition"
                ? (c.clip_start_frame ?? c.frame)
                : (c.context_start_frame ?? c.start_frame ?? c.frame),
            ),
            end = num(
              stage === "recognition"
                ? (c.clip_end_frame ?? frame + 1)
                : (c.context_end_frame ??
                    (typeof c.end_frame === "number"
                      ? c.end_frame + 1
                      : frame + 1)),
            );
          const excluded =
            stage !== "rallies" &&
            doc.scene_ranges.some(
              (r) =>
                r.scene !== "live" &&
                r.start_frame < end &&
                start < r.end_frame,
            );
          const title = courtStale
            ? "Court changed; rerun tracking and suggestions"
            : stale
              ? "Review context changed; request new suggestions"
              : excluded
                ? "Excluded by scene review"
                : added
                  ? stage === "recognition"
                    ? "Applied"
                    : "Added"
                  : changed
                    ? "Contact changed; classify again"
                    : stage === "rallies"
                      ? c.kind === "serve"
                        ? "Review possible serve"
                        : "Review possible rally end"
                      : stage === "recognition"
                        ? c.status === "predicted"
                          ? c.kind === "serve"
                            ? "Possible serve"
                            : `Possible ${str(c.family)}`
                          : "Needs source review"
                        : c.timing === "uncertain_interval"
                          ? "Review possible contact"
                          : "Review contact";
          const attrs =
            stage === "contacts"
              ? { "data-candidate": str(c.id) }
              : stage === "recognition"
                ? { "data-stroke": str(c.id) }
                : { "data-rally-candidate": str(c.id) };
          return (
            <button
              key={str(c.id)}
              className={`candidate-row ${stage === "recognition" ? "stroke-row" : ""}`}
              {...attrs}
              disabled={stale || courtStale || added || excluded || changed}
              onClick={() => onChoose(c)}
            >
              <time>
                {stage === "recognition" ? `F${frame}` : clock(num(c.time_s))}
              </time>
              <span>
                {title}
                <small>
                  {stage !== "recognition" && c.start_frame != null
                    ? `Frames ${num(c.start_frame)}–${num(c.end_frame)} · timing uncertain · `
                    : ""}
                  {stage === "contacts"
                    ? `Track ${c.track_id ?? "?"} · identity unconfirmed · score ${num(c.score).toFixed(2)}`
                    : stage === "recognition"
                      ? `${str(c.reason)} · ${sides.includes(c.side as (typeof sides)[number]) && c.side !== "unknown" ? `possible ${str(c.side)} (${num(c.side_score).toFixed(2)})` : "stroke side unresolved"} · verify mechanics`
                      : "hitter and timing unconfirmed"}
                </small>
              </span>
            </button>
          );
        })}
        {!candidates.length && (
          <p className="empty">
            {stage === "contacts"
              ? "Track the shuttle, then suggest contacts."
              : stage === "recognition"
                ? "Family suggestions appear here. They never replace your saved labels automatically."
                : "Boundary suggestions appear here. Missing proposals do not mean there was no rally."}
          </p>
        )}
      </div>
    </section>
  );
}
function BoundaryEvaluation({
  kind,
  result,
}: {
  kind: "serve" | "rally_end";
  result: ObjectData;
}) {
  const label = kind === "serve" ? "Serve" : "Rally-ending",
    coverage = object(result.coverage ?? {}),
    timing = result.representative_timing
      ? object(result.representative_timing)
      : null,
    metrics = timing?.metrics ? object(timing.metrics) : null,
    intervals = result.interval_compatibility
      ? object(result.interval_compatibility)
      : null,
    skipped = objects(coverage.skipped_windows),
    timingSkipped = objects(coverage.point_timing_skipped_windows),
    percent = (value: unknown) =>
      typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—",
    reason = (value: unknown) =>
      str(value, "review needed").replaceAll("_", " ");
  return (
    <section
      id={kind === "serve" ? "evaluation-serve" : "evaluation-rally-end"}
    >
      <p>
        <strong>{label} proposals</strong>
        <br />
        {array(coverage.usable_window_ids).length} complete live review
        window(s) cover {num(coverage.reviewed_events)} reviewed boundary
        event(s) and {num(coverage.evaluated_candidates)} proposal(s).
      </p>
      {metrics ? (
        <p>
          Representative-timing F1 {percent(metrics.f1)}
          <br />
          Precision {percent(metrics.precision)} · recall{" "}
          {percent(metrics.recall)}
          <br />
          {num(metrics.tp)} matched · {num(metrics.fp)} false ·{" "}
          {num(metrics.fn)} missed within {num(timing?.tolerance_s).toFixed(3)}{" "}
          s.
          <br />
          Point-timing coverage: {num(coverage.point_timing_event_count)}{" "}
          reviewed boundary event(s) and{" "}
          {num(coverage.point_timing_candidate_count)} proposal(s).
        </p>
      ) : (
        <p>
          {result.status === "needs_exact_boundary_timing"
            ? "Reviewed boundary timing remains uncertain; point-timing metrics are unavailable."
            : "No complete live boundary review window is fully covered for point-timing metrics."}
        </p>
      )}
      {intervals ? (
        <p>
          Possible interval support: {num(intervals.matched_count)}/
          {num(intervals.reviewed_event_count)} reviewed boundary event(s) have
          a one-to-one compatible proposal interval across{" "}
          {num(intervals.candidate_count)} proposal(s).
        </p>
      ) : (
        <p>No exhaustively reviewed live coverage for interval comparison.</p>
      )}
      <small>
        Uncertain proposal representative times are navigation frames, not exact
        physical boundary times. Interval compatibility is possible temporal
        support, not accuracy or F1; it cannot resolve uncertain source
        evidence.
      </small>
      {(skipped.length > 0 || timingSkipped.length > 0) && (
        <ul>
          {skipped.map((window, index) => (
            <li key={`coverage-${index}`}>
              Clip {str(window.id)} excluded: {reason(window.reason)}.
            </li>
          ))}
          {timingSkipped.map((window, index) => (
            <li key={`timing-${index}`}>
              Clip {str(window.id)} excluded from point timing:{" "}
              {reason(window.reason)}.
            </li>
          ))}
        </ul>
      )}
      <small>
        {array(coverage.excluded_event_ids).length} event(s) and{" "}
        {array(coverage.excluded_candidate_ids).length} proposal(s) excluded
        from coverage. Download the report for frame intervals, unmatched IDs
        and source/run provenance.
      </small>
    </section>
  );
}
function Evaluation({
  report,
  dirty,
  videoId,
}: {
  report: ObjectData | null;
  dirty: boolean;
  videoId: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!report || dirty) {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(
      new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }),
    );
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [report, dirty]);
  const percent = (n: unknown) =>
    typeof n === "number" ? `${(n * 100).toFixed(1)}%` : "—";
  return (
    <>
      <a
        id="download-evaluation"
        href={url ?? undefined}
        download={`${videoId}-evaluation.json`}
        hidden={!url}
      >
        Download report
      </a>
      <div id="evaluation-results" role="status">
        {dirty ? (
          "Save your edits, then measure this revision."
        ) : !report ? (
          "Label a complete live clip and declare review coverage before measuring."
        ) : (
          <>
            <p>Saved revision {num(report.annotation_revision)}</p>
            {["contacts", "shuttle"].map((key) => {
              if (!report[key]) return null;
              const result = object(report[key]),
                metric = result.metrics ? object(result.metrics) : null,
                coverage = object(result.coverage ?? {});
              return (
                <div key={key}>
                  {metric ? (
                    <>
                      <p>
                        <strong>
                          {key === "contacts" ? "Contact proposals" : "Shuttle"}{" "}
                          F1 {percent(metric.f1)}
                        </strong>
                        <br />
                        Precision {percent(metric.precision)} · recall{" "}
                        {percent(metric.recall)}
                        <br />
                        {num(metric.tp)} matched · {num(metric.fp)} false ·{" "}
                        {num(metric.fn)} missed
                      </p>
                      {key === "contacts" &&
                        num(coverage.uncertain_candidate_count) > 0 && (
                          <p>
                            {num(coverage.uncertain_candidate_count)} uncertain
                            proposal(s) use navigation frames in this timing
                            score.{" "}
                            {num(
                              result.interval_coverage
                                ? object(result.interval_coverage).matched_count
                                : 0,
                            )}{" "}
                            reviewed contact(s) lie within proposed frame
                            ranges. Inspect the interval before assigning an
                            exact contact.
                          </p>
                        )}
                    </>
                  ) : (
                    <p>
                      {key === "contacts"
                        ? objects(coverage.skipped_windows).some(
                            (w) =>
                              w.reason === "contact_timing_needs_adjudication",
                          )
                          ? "Contact timing needs review before this clip can be scored."
                          : "No complete live clip is fully covered by this run."
                        : "No manually labeled shuttle frames in this run."}
                    </p>
                  )}
                </div>
              );
            })}
            {report.rallies &&
              (() => {
                const boundaryKinds = object(
                  object(report.rallies).kinds ?? {},
                );
                return (["serve", "rally_end"] as const).map((kind) =>
                  boundaryKinds[kind] ? (
                    <BoundaryEvaluation
                      key={kind}
                      kind={kind}
                      result={object(boundaryKinds[kind])}
                    />
                  ) : null,
                );
              })()}
            {report.recognition &&
              (() => {
                const r = object(report.recognition),
                  family = object(r.family),
                  side = object(r.side),
                  labels = object(r.labels);
                return (
                  <>
                    <p>
                      <strong>
                        Shot-family F1 {percent(family.macro_f1_supported)}
                      </strong>
                      <br />
                      {array(family.supported_classes).length}/6 target families
                      have independent labels.
                      <br />
                      {num(family.answered_contact_count)}/
                      {num(family.known_contact_count)} labeled contacts
                      answered.
                    </p>
                    {array(family.supported_classes).length < 6 && (
                      <small>
                        Only represented target families contribute to this
                        average. This is not a six-family benchmark.
                      </small>
                    )}
                    {array(labels.excluded_model_assisted_event_ids).length >
                      0 && (
                      <small>
                        {array(labels.excluded_model_assisted_event_ids).length}{" "}
                        classifier-assisted label(s) excluded from accuracy
                        scoring.
                      </small>
                    )}
                    {side.balanced_accuracy != null && (
                      <p>
                        Stroke-side balanced accuracy{" "}
                        {percent(side.balanced_accuracy)}
                      </p>
                    )}
                    {r.complete_event && (
                      <p>
                        Complete shot-event F1{" "}
                        {percent(object(r.complete_event).f1)}
                        <br />
                        {num(r.complete_event_label_count)} contacts have
                        family, side, and hitter labels.
                      </p>
                    )}
                    <small>
                      Recognition scores are conditional on the supplied
                      contacts. See the downloaded report for per-class errors,
                      missing outputs, and input provenance.
                    </small>
                  </>
                );
              })()}
          </>
        )}
      </div>
    </>
  );
}
