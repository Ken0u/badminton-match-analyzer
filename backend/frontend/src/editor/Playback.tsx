import { memo, useEffect, useRef } from "react";
import type { EditorController } from "./controller.js";
import {
  array,
  clock,
  displayCalibrations,
  displayShuttle,
  frameAt,
  num,
  objects,
  str,
  cameraChanged,
  courtSignature,
} from "./model.js";
import type { Point } from "./model.js";
export interface PlaybackActions {
  seek: (frame: number) => void;
  toggle: () => void;
  exactReady: () => boolean;
}
export const Playback = memo(function Playback({
  controller,
  actions,
  onPoint,
  corners,
  showTracks,
  showShuttle,
}: {
  controller: EditorController;
  actions: { current: PlaybackActions | null };
  onPoint: (point: Point, ready: boolean) => void;
  corners: Point[] | null;
  showTracks: boolean;
  showShuttle: boolean;
}) {
  const video = useRef<HTMLVideoElement>(null),
    image = useRef<HTMLImageElement>(null),
    canvas = useRef<HTMLCanvasElement>(null),
    frameInput = useRef<HTMLInputElement>(null),
    scrubber = useRef<HTMLInputElement>(null),
    clockOutput = useRef<HTMLSpanElement>(null),
    loading = useRef<HTMLDivElement>(null),
    playButton = useRef<HTMLButtonElement>(null),
    courtStatus = useRef<HTMLElement>(null),
    labelStatus = useRef<HTMLElement>(null);
  const config = useRef({ onPoint, corners, showTracks, showShuttle });
  config.current = { onPoint, corners, showTracks, showShuttle };
  const source = useRef(""),
    activeId = useRef(""),
    switching = useRef(false),
    exactSequence = useRef(0),
    prepared = useRef<string | null>(null);
  useEffect(() => {
    const v = video.current!,
      img = image.current!,
      ctx = canvas.current!.getContext("2d")!;
    let disposed = false,
      rvfc: number | null = null;
    function current() {
      return controller.playback.getSnapshot().sourceFrame ?? 0;
    }
    function ready() {
      return (
        !img.hidden &&
        img.complete &&
        img.naturalWidth > 0 &&
        img.dataset.frame === String(current()) &&
        img.dataset.video === activeId.current
      );
    }
    function exact() {
      const s = controller.snapshot();
      // Source frames are decoded by the server, independently of whether the
      // browser has loaded metadata or supports the native playback format.
      if (!s.video || !v.paused) return;
      const f = current(),
        id = s.video.id,
        sequence = ++exactSequence.current;
      img.hidden = true;
      loading.current!.hidden = false;
      loading.current!.textContent = "Loading source frame…";
      img.onload = () => {
        if (
          disposed ||
          sequence !== exactSequence.current ||
          id !== activeId.current ||
          f !== current() ||
          !v.paused
        )
          return;
        img.dataset.frame = String(f);
        img.dataset.video = id;
        img.hidden = false;
        loading.current!.hidden = true;
      };
      img.onerror = () => {
        if (
          disposed ||
          sequence !== exactSequence.current ||
          id !== activeId.current
        )
          return;
        loading.current!.textContent =
          "Source frame unavailable. Try again or use playback.";
        controller.notice(
          "Could not load the source frame. Check whether the video changed or is unavailable.",
          true,
        );
      };
      img.src = `/api/videos/${encodeURIComponent(id)}/frame?index=${f}`;
    }
    function draw() {
      const s = controller.snapshot(),
        d = controller.drafts.getSnapshot()?.value;
      if (!s.video || !d) return;
      const f = current(),
        w = s.video.width,
        h = s.video.height;
      if (ctx.canvas.width !== w) ctx.canvas.width = w;
      if (ctx.canvas.height !== h) ctx.canvas.height = h;
      ctx.clearRect(0, 0, w, h);
      const run = s.runs.players?.run ?? null;
      const valid = Boolean(
        run &&
        !run.requires_tracking_rerun &&
        !cameraChanged(d, run) &&
        JSON.stringify(
          courtSignature(d, run, run.start_frame, run.end_frame),
        ) === JSON.stringify(run.calibration_signature),
      );
      const calibration = displayCalibrations(
        d,
        run,
        s.times,
        s.video.fps,
        valid,
      ).find((c) => c.start_frame <= f && f < c.end_frame);
      const points = config.current.corners ?? calibration?.corners;
      courtStatus.current!.textContent = calibration
        ? `${calibration.automatic ? "Auto-detected · unreviewed" : "Calibrated"} · frames ${calibration.start_frame}–${calibration.end_frame - 1}`
        : "No calibration for this frame";
      if (points?.length) {
        ctx.strokeStyle = "#b5ef91";
        ctx.fillStyle = "#b5ef9112";
        ctx.lineWidth = 3;
        ctx.setLineDash(calibration?.automatic ? [9, 6] : []);
        ctx.beginPath();
        points.forEach((p, i) =>
          i ? ctx.lineTo(p.x * w, p.y * h) : ctx.moveTo(p.x * w, p.y * h),
        );
        if (points.length === 4) ctx.closePath();
        ctx.stroke();
        if (points.length === 4) ctx.fill();
        ctx.setLineDash([]);
        points.forEach((p, i) => {
          ctx.beginPath();
          ctx.arc(p.x * w, p.y * h, 6, 0, Math.PI * 2);
          ctx.fillStyle = "#b5ef91";
          ctx.fill();
          ctx.font = "17px Segoe UI";
          ctx.fillText(String(i + 1), p.x * w + 10, p.y * h - 8);
        });
      }
      if (config.current.showShuttle) {
        const shuttle = displayShuttle(
          d,
          s.runs.shuttle?.run ?? null,
          s.times,
          s.video.fps,
          f,
        );
        ctx.strokeStyle = "#ffd379";
        ctx.fillStyle = "#ffd379";
        ctx.lineWidth = 2;
        ctx.beginPath();
        for (const segment of shuttle.segments) {
          for (const [index, point] of segment.entries()) {
            if (index) ctx.lineTo(point.x, point.y);
            else ctx.moveTo(point.x, point.y);
          }
        }
        ctx.stroke();
        const p = shuttle.current;
        if (p) {
          ctx.beginPath();
          ctx.arc(p.x, p.y, 6, 0, Math.PI * 2);
          ctx.fill();
          ctx.strokeStyle = "#182227";
          ctx.stroke();
        }
      }
      const manual = d.shuttle_points.find((p) => p.frame === f);
      labelStatus.current!.textContent = `${d.shuttle_points.length} labeled frames · frame ${f}: ${manual ? (manual.visible ? "visible, position marked" : "not visible") : "unlabeled"}`;
      if (manual?.visible && manual.x != null && manual.y != null) {
        const x = manual.x * w,
          y = manual.y * h;
        ctx.strokeStyle = "#75e0f5";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(x, y, 10, 0, Math.PI * 2);
        ctx.moveTo(x - 14, y);
        ctx.lineTo(x + 14, y);
        ctx.moveTo(x, y - 14);
        ctx.lineTo(x, y + 14);
        ctx.stroke();
      }
      if (config.current.showTracks) {
        const row = run?.frames.find((r) => num(r.frame) === f);
        for (const p of objects(row?.players)) {
          const box = array(p.box).map((x) => num(x));
          if (box.length !== 4) continue;
          const [x1 = 0, y1 = 0, x2 = 0, y2 = 0] = box;
          ctx.strokeStyle = "#d6f9be";
          ctx.lineWidth = 2;
          ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
          const assigned = d.track_assignments.find(
            (a) =>
              a.run_id === s.runs.players?.id &&
              a.track_id === p.track_id &&
              a.start_frame <= f &&
              f < a.end_frame,
          );
          const actor =
            s.analysisEnabled && !controller.planStale()
              ? s.actors.find(
                  (a) =>
                    a.run_id === s.runs.players?.id &&
                    a.track_id === p.track_id &&
                    a.linked_across_windows &&
                    array(a.observation_ranges).some((range) => {
                      const r = array(range);
                      return num(r[0]) <= f && f < num(r[1]);
                    }),
                )
              : null;
          const label = `${assigned ? `Player ${assigned.player_id} · ` : actor ? `${str(actor.label)}? · ` : ""}Track ${p.track_id ?? "?"} · ${Math.round(num(p.confidence) * 100)}%`;
          ctx.font = "16px Segoe UI";
          ctx.fillStyle = "#14231cdd";
          ctx.fillRect(
            x1,
            Math.max(0, y1 - 24),
            ctx.measureText(label).width + 10,
            24,
          );
          ctx.fillStyle = "#d6f9be";
          ctx.fillText(label, x1 + 5, Math.max(18, y1 - 6));
          for (const [a, b] of [
            [5, 7],
            [7, 9],
            [6, 8],
            [8, 10],
            [5, 6],
            [5, 11],
            [6, 12],
            [11, 12],
            [11, 13],
            [13, 15],
            [12, 14],
            [14, 16],
          ]) {
            const pa = array(array(p.keypoints)[a!]),
              pb = array(array(p.keypoints)[b!]);
            if (num(pa[2]) > 0.35 && num(pb[2]) > 0.35) {
              ctx.beginPath();
              ctx.moveTo(num(pa[0]), num(pa[1]));
              ctx.lineTo(num(pb[0]), num(pb[1]));
              ctx.stroke();
            }
          }
        }
      }
    }
    function update(frame: number, playing = false, mediaTime?: number) {
      const s = controller.snapshot();
      if (!s.video) return;
      const f = Math.max(0, Math.min(s.times.length - 1, Math.round(frame)));
      controller.setFrame(f);
      if (playing)
        controller.playback.update({
          mediaTime: mediaTime ?? v.currentTime,
          sourceTime: s.times[f] ?? 0,
          sourceFrame: f,
          playing: true,
        });
    }
    function seek(f: number) {
      if (!controller.snapshot().video) return;
      v.pause();
      update(f);
      const s = controller.snapshot();
      try {
        v.currentTime = s.times[current()] ?? 0;
      } catch {
        /* Exact source review remains available before media metadata. */
      }
      exact();
    }
    function toggle() {
      if (v.paused) {
        img.hidden = true;
        loading.current!.hidden = true;
        const id = activeId.current,
          url = source.current;
        void v.play().catch((e) => {
          if (
            !disposed &&
            id === activeId.current &&
            url === source.current &&
            !(e instanceof DOMException && e.name === "AbortError")
          )
            mediaError();
        });
      } else {
        v.pause();
        exact();
      }
    }
    function mediaError() {
      if (!switching.current)
        controller.notice(
          "Video playback could not load. Choose Prepare playback or use exact-frame review.",
          true,
        );
      switching.current = false;
      exact();
    }
    function changed() {
      const s = controller.snapshot();
      if (!s.video) {
        v.pause();
        img.hidden = true;
        activeId.current = "";
        return;
      }
      const first = activeId.current !== s.video.id;
      const url =
        s.playbackUrl ?? `/api/videos/${encodeURIComponent(s.video.id)}/media`;
      if (first) {
        activeId.current = s.video.id;
        prepared.current = null;
        update(s.video.review_start_frame);
        frameInput.current!.max = String(s.video.frame_count - 1);
        scrubber.current!.max = String(s.video.frame_count - 1);
      }
      if (
        first ||
        (s.playbackUrl && prepared.current !== s.playbackUrl && v.paused)
      ) {
        switching.current = true;
        v.pause();
        source.current = url;
        prepared.current = s.playbackUrl;
        v.src = url;
        v.load();
        exactSequence.current++;
        img.hidden = true;
      }
      draw();
    }
    function onMetadata() {
      switching.current = false;
      const s = controller.snapshot();
      if (!s.video) return;
      // Restoring source time after metadata must preserve an explicit Play
      // requested while the source was loading. seek() intentionally pauses
      // for manual frame review and would abort that pending play request.
      try {
        v.currentTime = s.times[current()] ?? 0;
      } catch {
        /* Exact source review remains available if media seeking fails. */
      }
      if (v.paused) exact();
    }
    function onReady() {
      if (
        v.readyState >= 2 &&
        !v.error &&
        prepared.current &&
        controller
          .snapshot()
          .notice.startsWith("Video playback could not load.")
      )
        controller.notice("");
    }
    function onTime() {
      if (!switching.current && !v.paused)
        update(
          frameAt(controller.snapshot().times, v.currentTime),
          true,
          v.currentTime,
        );
    }
    function onPause() {
      if (!switching.current) {
        update(frameAt(controller.snapshot().times, v.currentTime));
        playButton.current!.textContent = "▶ Play";
        exact();
      }
    }
    function onPlay() {
      img.hidden = true;
      loading.current!.hidden = true;
      playButton.current!.textContent = "Ⅱ Pause";
    }
    function tick() {
      if (disposed) return;
      onTime();
      if ("requestVideoFrameCallback" in v)
        rvfc = v.requestVideoFrameCallback(tick);
    }
    const unsubscribePlayback = controller.playback.subscribe(() => {
      const p = controller.playback.getSnapshot();
      frameInput.current!.value = String(p.sourceFrame ?? 0);
      scrubber.current!.value = String(p.sourceFrame ?? 0);
      clockOutput.current!.textContent = clock(p.sourceTime ?? 0);
      draw();
    });
    const unsubscribeServer = controller.subscribe(changed),
      unsubscribeDraft = controller.drafts.subscribe(draw);
    actions.current = { seek, toggle, exactReady: ready };
    const onFrame = () => seek(Number(frameInput.current!.value)),
      onScrub = () => seek(Number(scrubber.current!.value));
    frameInput.current!.addEventListener("change", onFrame);
    scrubber.current!.addEventListener("input", onScrub);
    v.addEventListener("loadedmetadata", onMetadata);
    v.addEventListener("canplay", onReady);
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("pause", onPause);
    v.addEventListener("play", onPlay);
    v.addEventListener("seeked", exact);
    v.addEventListener("error", mediaError);
    if ("requestVideoFrameCallback" in v)
      rvfc = v.requestVideoFrameCallback(tick);
    changed();
    return () => {
      disposed = true;
      unsubscribePlayback();
      unsubscribeServer();
      unsubscribeDraft();
      actions.current = null;
      exactSequence.current++;
      img.onload = null;
      img.onerror = null;
      frameInput.current?.removeEventListener("change", onFrame);
      scrubber.current?.removeEventListener("input", onScrub);
      v.removeEventListener("loadedmetadata", onMetadata);
      v.removeEventListener("canplay", onReady);
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("pause", onPause);
      v.removeEventListener("play", onPlay);
      v.removeEventListener("seeked", exact);
      v.removeEventListener("error", mediaError);
      if (rvfc !== null) v.cancelVideoFrameCallback(rvfc);
      v.pause();
      v.removeAttribute("src");
      v.load();
    };
  }, [controller, actions]);
  useEffect(() => {
    const p = controller.playback.getSnapshot();
    controller.playback.update({
      ...p,
      mediaTime: p.mediaTime + Number.EPSILON,
    });
  }, [controller, corners, showTracks, showShuttle]);
  return (
    <>
      <div
        id="stage"
        style={{
          aspectRatio: `${controller.snapshot().video?.width ?? 16}/${controller.snapshot().video?.height ?? 9}`,
        }}
      >
        <video id="video" ref={video} playsInline preload="metadata" />
        <img id="exact-frame" ref={image} alt="Exact source frame" hidden />
        <canvas
          id="overlay"
          ref={canvas}
          aria-label="Court calibration and player tracking overlay"
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            config.current.onPoint(
              {
                x: Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)),
                y: Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)),
              },
              actions.current?.exactReady() ?? false,
            );
          }}
        />
        <div id="calibration-hint" hidden={corners === null}>
          {corners !== null
            ? `${corners.length + 1} / 4 · ${["Far left", "Far right", "Near right", "Near left"][corners.length]} corner`
            : ""}
        </div>
        <div id="frame-loading" ref={loading} role="status" hidden>
          Loading source frame…
        </div>
      </div>
      <div className="transport">
        <button
          id="back-frame"
          title="Previous frame (←)"
          onClick={() =>
            actions.current?.seek(
              (controller.playback.getSnapshot().sourceFrame ?? 0) - 1,
            )
          }
        >
          ←
        </button>
        <button
          id="play"
          ref={playButton}
          onClick={() => actions.current?.toggle()}
        >
          ▶ Play
        </button>
        <button
          id="next-frame"
          title="Next frame (→)"
          onClick={() =>
            actions.current?.seek(
              (controller.playback.getSnapshot().sourceFrame ?? 0) + 1,
            )
          }
        >
          →
        </button>
        <span id="clock" ref={clockOutput}>
          0:00.00
        </span>
        <label>
          FRAME{" "}
          <input
            id="frame-number"
            ref={frameInput}
            type="number"
            min="0"
            defaultValue="0"
            aria-label="Source frame"
          />
        </label>
        <select
          id="speed"
          aria-label="Playback speed"
          defaultValue="1"
          onChange={(e) => {
            if (video.current)
              video.current.playbackRate = Number(e.target.value);
          }}
        >
          {[0.25, 0.5, 1, 2].map((n) => (
            <option key={n} value={n}>
              {n}×
            </option>
          ))}
        </select>
      </div>
      <input
        id="scrubber"
        ref={scrubber}
        type="range"
        min="0"
        max="1"
        defaultValue="0"
        aria-label="Video position in source frames"
      />
      <small id="court-status" ref={courtStatus}>
        No calibration for this frame
      </small>
      <small id="shuttle-label-status" ref={labelStatus}>
        No manually labeled shuttle frames
      </small>
    </>
  );
});
