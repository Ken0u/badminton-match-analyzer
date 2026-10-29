import {
  array,
  cameraChanged,
  courtSignature,
  displayCalibrations,
  objects,
  str,
} from "./model.js";
import type { Document, ObjectData, Point, Run } from "./model.js";

const finite = (v: unknown): v is number =>
  typeof v === "number" && Number.isFinite(v);

/** Camera/display-normalized coordinates to the outer court unit rectangle.
 * Corner order: far left, far right, near right, near left. No shuttle geometry.
 */
export function courtProjection(corners: readonly Point[]): number[] | null {
  if (
    !Array.isArray(corners) ||
    corners.length !== 4 ||
    corners.some(
      (p) =>
        !p ||
        !finite(p.x) ||
        !finite(p.y) ||
        p.x < 0 ||
        p.x > 1 ||
        p.y < 0 ||
        p.y > 1,
    )
  )
    return null;
  let winding = 0;
  for (let i = 0; i < 4; i++) {
    const a = corners[i]!,
      b = corners[(i + 1) % 4]!,
      c = corners[(i + 2) % 4]!;
    const cross = (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x);
    if (Math.abs(cross) < 1e-6 || (winding && Math.sign(cross) !== winding))
      return null;
    winding = Math.sign(cross);
  }
  const target = [
    [0, 0],
    [1, 0],
    [1, 1],
    [0, 1],
  ];
  const rows: number[][] = [];
  for (let i = 0; i < 4; i++) {
    const { x, y } = corners[i]!,
      [u, v] = target[i]!;
    rows.push([x, y, 1, 0, 0, 0, -u! * x, -u! * y, u!]);
    rows.push([0, 0, 0, x, y, 1, -v! * x, -v! * y, v!]);
  }
  for (let column = 0; column < 8; column++) {
    let pivot = column;
    for (let r = column + 1; r < 8; r++)
      if (Math.abs(rows[r]![column]!) > Math.abs(rows[pivot]![column]!))
        pivot = r;
    if (Math.abs(rows[pivot]![column]!) < 1e-9) return null;
    [rows[column], rows[pivot]] = [rows[pivot]!, rows[column]!];
    const divisor = rows[column]![column]!;
    for (let c = column; c <= 8; c++)
      rows[column]![c] = rows[column]![c]! / divisor;
    for (let r = 0; r < 8; r++) {
      if (r === column) continue;
      const factor = rows[r]![column]!;
      for (let c = column; c <= 8; c++)
        rows[r]![c] = rows[r]![c]! - factor * rows[column]![c]!;
    }
  }
  const matrix = [...rows.map((r) => r[8]!), 1];
  if (!matrix.every(finite)) return null;
  // Verify correspondence and a consistent, nonzero denominator across the court.
  const denominators = corners.map(
    (p) => matrix[6]! * p.x + matrix[7]! * p.y + 1,
  );
  if (
    denominators.some(
      (d) => Math.abs(d) < 1e-7 || Math.sign(d) !== Math.sign(denominators[0]!),
    )
  )
    return null;
  // Orient the homogeneous scale toward the court's side of the horizon.
  // Valid extrapolations must stay on that same continuous ground plane.
  if (denominators[0]! < 0)
    for (let i = 0; i < matrix.length; i++) matrix[i] = -matrix[i]!;
  for (let i = 0; i < 4; i++) {
    const p = projectCourtPoint(matrix, corners[i]!);
    if (!p || Math.hypot(p.x - target[i]![0]!, p.y - target[i]![1]!) > 1e-6)
      return null;
  }
  return matrix;
}

export function projectCourtPoint(
  matrix: readonly number[],
  p: Point,
): Point | null {
  if (
    !Array.isArray(matrix) ||
    matrix.length !== 9 ||
    !matrix.every(finite) ||
    !p ||
    !finite(p.x) ||
    !finite(p.y)
  )
    return null;
  const divisor = matrix[6]! * p.x + matrix[7]! * p.y + matrix[8]!;
  if (divisor < 1e-7) return null;
  const x = (matrix[0]! * p.x + matrix[1]! * p.y + matrix[2]!) / divisor;
  const y = (matrix[3]! * p.x + matrix[4]! * p.y + matrix[5]!) / divisor;
  return finite(x) && finite(y) ? { x, y } : null;
}

export interface CourtPlayer extends Point {
  label: string;
  identity: "reviewed" | "provisional" | "unassigned";
  track: string;
}
export interface CourtView {
  frame: number | null;
  mode: string;
  scene: string;
  automatic: boolean;
  note: string;
  players: CourtPlayer[];
  unavailable: number;
}
export interface CourtInput {
  doc: Document | null;
  run: Run | null;
  runId: string | null;
  videoId: string | null;
  frame: number | null;
  width: number;
  height: number;
  times: number[];
  fps: number;
  editing: boolean;
  actors: ObjectData[];
  actorHintsValid: boolean;
}

/** A single native source frame, never interpolated or held from another window. */
export function playerCourtView(input: CourtInput): CourtView {
  const { doc, run, frame, width, height } = input;
  const result: CourtView = {
    frame,
    mode: doc?.mode ?? "singles",
    scene: "unknown",
    automatic: false,
    note: "Choose a video to view player positions.",
    players: [],
    unavailable: 0,
  };
  if (
    !doc ||
    !input.videoId ||
    frame === null ||
    !Number.isSafeInteger(frame) ||
    frame < 0 ||
    frame >= input.times.length ||
    !finite(input.times[frame])
  )
    return result;
  const scenes = doc.scene_ranges.filter(
    (s) => s.start_frame <= frame && frame < s.end_frame,
  );
  result.scene = scenes.length === 1 ? scenes[0]!.scene : "unknown";
  if (result.scene === "replay" || result.scene === "non_play") {
    result.note = `${result.scene === "replay" ? "Replay" : "Non-play"} scene: live player map unavailable.`;
    return result;
  }
  if (input.editing) {
    result.note =
      "Court corners are being edited. Finish or cancel calibration.";
    return result;
  }
  const valid = Boolean(
    run &&
    !run.requires_tracking_rerun &&
    !cameraChanged(doc, run) &&
    JSON.stringify(courtSignature(doc, run, run.start_frame, run.end_frame)) ===
      JSON.stringify(run.calibration_signature),
  );
  const calibration = displayCalibrations(
    doc,
    run,
    input.times,
    input.fps,
    valid,
  ).find((c) => c.start_frame <= frame && frame < c.end_frame);
  if (!calibration) {
    result.note = "No current court calibration for this source frame.";
    return result;
  }
  result.automatic = Boolean(calibration.automatic);
  const matrix = courtProjection(calibration.corners);
  if (!matrix) {
    result.note =
      "Court geometry is incomplete or unstable. Review the four outer corners.";
    return result;
  }
  if (
    !run ||
    !input.runId ||
    (run.video_id != null && run.video_id !== input.videoId) ||
    !valid ||
    frame < run.start_frame ||
    frame >= run.end_frame
  ) {
    result.note =
      "Current tracking is unavailable or its camera/court context changed.";
    return result;
  }
  if (!finite(width) || !finite(height) || width <= 0 || height <= 0) {
    result.note = "Source display dimensions are unavailable.";
    return result;
  }
  const rows = run.frames.filter((r) => r.frame === frame);
  if (rows.length !== 1 || rows[0]!.calibration_valid === false) {
    result.note = "No supported player observation at this exact source frame.";
    return result;
  }
  const people = objects(rows[0]!.players);
  for (const p of people) {
    const box = array(p.box);
    const id = p.track_id;
    const knownTrack =
      (typeof id === "number" && Number.isSafeInteger(id) && id >= 0) ||
      (typeof id === "string" && id.length > 0);
    if (
      box.length !== 4 ||
      !box.every(finite) ||
      box[0]! < 0 ||
      box[1]! < 0 ||
      box[2]! > width ||
      box[3]! > height ||
      box[2]! <= box[0]! ||
      box[3]! <= box[1]!
    ) {
      result.unavailable++;
      continue;
    }
    const point = projectCourtPoint(matrix, {
      x: (box[0]! + box[2]!) / (2 * width),
      y: box[3]! / height,
    });
    // The diagram includes a visible margin; farther estimates remain unavailable,
    // never clamped onto a sideline or manufactured as an on-court observation.
    if (
      !point ||
      point.x < -0.25 ||
      point.x > 1.25 ||
      point.y < -0.12 ||
      point.y > 1.12
    ) {
      result.unavailable++;
      continue;
    }
    const uniqueTrack =
      knownTrack &&
      people.filter((other) => other.track_id === id).length === 1;
    const assignments = uniqueTrack
      ? doc.track_assignments.filter(
          (a) =>
            a.run_id === input.runId &&
            a.track_id === id &&
            a.start_frame <= frame &&
            frame < a.end_frame,
        )
      : [];
    const assignment = assignments.length === 1 ? assignments[0] : undefined;
    const player = assignment
      ? doc.players.find((person) => person.id === assignment.player_id)
      : undefined;
    const actors =
      !assignment && uniqueTrack && input.actorHintsValid
        ? input.actors.filter(
            (a) =>
              a.run_id === input.runId &&
              a.track_id === id &&
              a.linked_across_windows &&
              array(a.observation_ranges).some((r) => {
                const interval = array(r);
                return (
                  interval.length === 2 &&
                  finite(interval[0]) &&
                  finite(interval[1]) &&
                  interval[0] <= frame &&
                  frame < interval[1]
                );
              }),
          )
        : [];
    const actor = actors.length === 1 ? actors[0] : undefined;
    const track = knownTrack ? String(id) : "?";
    result.players.push({
      ...point,
      track,
      label: player
        ? `${player.name || player.id} · ${player.id}${player.team ? ` · ${player.team}` : ""}`
        : actor
          ? `${str(actor.label, "Actor")}? · Track ${track}`
          : `Unassigned track ${track}`,
      identity: player ? "reviewed" : actor ? "provisional" : "unassigned",
    });
  }
  result.note = `${result.automatic ? "Automatic court · unreviewed" : "Saved court calibration"}. Box-foot positions are estimates.${result.scene === "unknown" ? " Scene context is unresolved." : ""}${result.unavailable ? ` ${result.unavailable} observation(s) unavailable or outside the diagram.` : ""}${!result.players.length ? " No supported player positions." : ""}`;
  return result;
}
