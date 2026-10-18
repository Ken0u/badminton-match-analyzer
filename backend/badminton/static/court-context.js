// Run-local geometry only; callers never insert these fits into annotations.
export function effectiveCalibrations(doc, run) {
  const cuts = [...(run?.cut_frames ?? [])];
  if (run?.preceding_reviewed_cut_frame != null)
    cuts.push(run.preceding_reviewed_cut_frame);
  const manual = (doc.calibrations ?? []).map((c) => ({
    ...c,
    end_frame:
      run?.court_context_version === 1
        ? Math.min(
            c.end_frame,
            ...cuts.filter((f) => c.start_frame < f && f < c.end_frame),
          )
        : c.end_frame,
  }));
  const derived = [];
  for (const c of run?.automatic_calibrations ?? []) {
    let cursor = c.start_frame;
    for (const m of [...manual].sort((a, b) => a.start_frame - b.start_frame)) {
      if (m.end_frame <= cursor || m.start_frame >= c.end_frame) continue;
      if (m.start_frame > cursor)
        derived.push({
          ...c,
          start_frame: cursor,
          end_frame: m.start_frame,
          automatic: true,
        });
      cursor = Math.max(cursor, m.end_frame);
    }
    if (cursor < c.end_frame)
      derived.push({ ...c, start_frame: cursor, automatic: true });
  }
  return [...manual, ...derived].sort((a, b) => a.start_frame - b.start_frame);
}

export function courtSignature(doc, run, start, end) {
  return effectiveCalibrations(doc, run)
    .filter((c) => c.start_frame < end && start < c.end_frame)
    .map((c) => [c.start_frame, c.end_frame, c.corners.map((p) => [p.x, p.y])]);
}

export function courtContextChanged(doc, artifact) {
  const context = artifact?.court_context;
  return (
    !!context &&
    (JSON.stringify(
      courtSignature(doc, context, context.start_frame, context.end_frame),
    ) !== JSON.stringify(artifact.calibration_signature) ||
      (context.known_preceding_cut_frames != null &&
        cameraContextChanged(doc, context)))
  );
}

export function cameraContextChanged(doc, run) {
  const current = (doc.camera_corrections ?? [])
    .filter((c) => run.start_frame <= c.frame && c.frame < run.end_frame)
    .sort((a, b) => a.frame - b.frame)
    .map((c) => [c.frame, c.is_cut]);
  const saved = (run.applied_camera_corrections ?? [])
    .map((c) => [c.frame, c.is_cut])
    .sort((a, b) => a[0] - b[0]);
  const previous = new Set(run.known_preceding_cut_frames ?? []);
  for (const c of doc.camera_corrections ?? []) {
    if (c.frame >= run.start_frame) continue;
    if (c.is_cut) previous.add(c.frame);
    else if (!(run.known_preceding_timestamp_gaps ?? []).includes(c.frame))
      previous.delete(c.frame);
  }
  const preceding = Math.max(-1, ...previous);
  return (
    JSON.stringify(current) !== JSON.stringify(saved) ||
    preceding !== (run.preceding_reviewed_cut_frame ?? -1)
  );
}
