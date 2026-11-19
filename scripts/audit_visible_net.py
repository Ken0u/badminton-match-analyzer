"""Compare saved doubles camera projections with exact native broadcast frames."""

import json
from pathlib import Path

import numpy as np
from badminton.rally_outcomes import camera_for
from badminton.video import iter_frames
from PIL import Image, ImageDraw


def audit():
    import torchvision  # noqa: F401 -- initialize before threaded PyAV decoding

    root = Path(__file__).resolve().parents[1]
    data = root / "data/processed/c406a1187130b845"
    out = root / ".cache/visible-net"
    out.mkdir(parents=True, exist_ok=True)

    def read(name):
        return json.loads((data / name).read_text(encoding="utf8"))

    video, times = read("metadata.json"), read("timestamps.json")
    views = read("match_analysis.json")["court"]["views"]
    w, h = video["width"], video["height"]
    for i in (10405, 10459, 10489, 2494, 2551, 6122, 1874):
        (view,) = [v for v in views if v["start_frame"] <= i < v["end_frame"]]
        cam = camera_for(view["homography"], w / h)

        def pixel(x, z):
            uv, depth = cam.project([x, 6.7, z])
            assert depth > 0
            return tuple(uv * [w, h])

        ((_, pts, frame),) = iter_frames(video, root, times, i, i + 1)
        im = frame.to_image()
        # Fixed image window identified on the raw broadcast, not centred on
        # the projection. The next white court line is above this window.
        red = np.asarray(im, dtype=float)[:, :, 0]
        im.save(out / f"{i}-source.png")
        overlay = im.copy()
        draw = ImageDraw.Draw(overlay)
        tape = [
            pixel(x, 1.524 + 0.026 * (2 * x / 6.1 - 1) ** 2)
            for x in np.linspace(0, 6.1, 101)
        ]
        draw.line(tape, fill="magenta", width=1)
        for col in (480, 765, 875):
            profile = np.median(red[277:284, col - 3 : col + 4], axis=1)
            edge = 277.5 + np.argmax(np.diff(profile))
            predicted = np.interp(col, *np.array(tape).T)
            print(
                i,
                col,
                "upper edge / projected / observed minus projected px:",
                round(edge, 1),
                round(predicted, 1),
                round(edge - predicted, 1),
            )
        for x in (0, 6.1):
            draw.line([pixel(x, 0), pixel(x, 1.55)], fill="orange")
        if i == 10459:
            x, y = pixel(3.438, 1.45754)
            draw.ellipse((x - 3, y - 3, x + 3, y + 3), outline="cyan")
        overlay.save(out / f"{i}-overlay.png")
        y0 = int(min(y for _, y in tape)) - 45
        box = (300, y0, 980, y0 + 90)
        pair = Image.new("RGB", (680, 180))
        for n, image in enumerate((im, overlay)):
            pair.paste(image.crop(box), (0, 90 * n))
        pair.resize((1360, 360), Image.Resampling.NEAREST).save(out / f"{i}-strip.png")
        print(
            i,
            pts,
            "view",
            view["start_frame"],
            "tape L/M/R",
            np.round([tape[j] for j in (0, 50, 100)], 1).tolist(),
            "bases",
            np.round([pixel(x, 0) for x in (0, 6.1)], 1).tolist(),
        )
        if i == 10459:
            print("crossing/tape reference:", pixel(3.438, 1.45754), pixel(3.438, 1.53))


if __name__ == "__main__":
    audit()
