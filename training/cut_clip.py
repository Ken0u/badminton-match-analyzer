"""Cut a frame range out of a match video, re-encoded so frame 0 is exact.

Frame numbers are counted the way the published labels count them: source
time times the stream frame rate. The clip keeps the source size and rate, so
clip frame k is source frame start + k. A JSON file next to the clip records
the source, the range and the rate.

    python training/cut_clip.py SOURCE OUTPUT.mp4 --start 9431 --end 36233
"""

import argparse
import json
from fractions import Fraction
from pathlib import Path

import av


def cut(source, output, start, end, crf=18, preset="veryfast"):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.stem + ".part" + output.suffix)
    with av.open(str(source)) as container:
        stream = container.streams.video[0]
        rate = stream.average_rate or stream.guessed_rate
        fps = float(rate)
        origin = stream.start_time or 0
        base = stream.time_base
        if start > 0:
            container.seek(
                origin + int((start / fps - 2.0) / base) if start / fps > 2 else origin,
                stream=stream,
                backward=True,
            )
        written = 0
        with av.open(str(partial), "w", format="mp4") as sink:
            out = sink.add_stream(
                "libx264", rate=Fraction(rate).limit_denominator(1001)
            )
            out.width, out.height = (
                stream.codec_context.width,
                stream.codec_context.height,
            )
            out.pix_fmt = "yuv420p"
            out.options = {"crf": str(crf), "preset": preset}
            for frame in container.decode(stream):
                if frame.pts is None:
                    continue
                index = round(float((frame.pts - origin) * base) * fps)
                if index < start:
                    continue
                if index >= end:
                    break
                image = frame.reformat(format="yuv420p")
                image.pts = written
                image.time_base = Fraction(1) / Fraction(rate).limit_denominator(1001)
                for packet in out.encode(image):
                    sink.mux(packet)
                written += 1
            for packet in out.encode():
                sink.mux(packet)
    partial.replace(output)
    info = {
        "source": str(source),
        "source_start_frame": start,
        "source_end_frame": start + written,
        "fps": fps,
        "frames": written,
    }
    output.with_suffix(".json").write_text(json.dumps(info) + "\n", encoding="utf-8")
    return info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(cut(args.source, args.output, args.start, args.end)))


if __name__ == "__main__":
    main()
