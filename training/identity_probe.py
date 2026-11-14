"""Can the four doubles players be told apart between rallies by their looks?

Per-person statistics need each rally's four tracked players matched to the
same four people through a whole video. Edited footage keeps only some
rallies, so nothing here uses the order of rallies or the score: each tracked
player is described by clothing colour and size, and the rallies are grouped
using only that partners stand at one end and are two different people.

The answer key is the published labels: S2 Doubles and DShuttleNet give all
four players' foot positions under fixed letters A to D at every stroke.

    python training/identity_probe.py --features .cache/dshuttlenet/features \
        --videos data/datasets/dshuttlenet/videos --prefix ds --match 2

Descriptions are cached in --cache, so the grouping can be rerun without
decoding the video again.
"""

import argparse
import gzip
import json
import math
import sys
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from badminton.event_doubles import SLOTS, assign_slots

LETTERS = "ABCD"
# Frames looked at per rally, and how near a published foot position must be
# to a tracked player's feet (share of the frame height) to name that player.
SAMPLES = 8
REACH = 0.07
# Body patches as strips between keypoints (COCO order): the two ends of each
# strip, how far along it the patch starts and stops, and its width as a share
# of its length. A strip end given as two keypoints is their midpoint. Limbs
# are taken one side at a time: the midline between two legs is floor.
PATCHES = {
    "shirt": ([((5, 6), (11, 12))], 0.15, 0.85, 0.33),
    "shorts": ([((11,), (13,)), ((12,), (14,))], 0.05, 0.45, 0.25),
    "legs": ([((13,), (15,)), ((14,), (16,))], 0.25, 0.8, 0.15),
    "shoes": ([((13,), (15,)), ((14,), (16,))], 1.05, 1.3, 0.25),
}
KEYPOINT_CONFIDENCE = 0.4
# Limb pairs whose lengths add up to a body length that bending shortens less
# than it shortens the box around the player.
BONES = ((5, 11), (6, 12), (11, 13), (12, 14), (13, 15), (14, 16))


def camera(row):
    value = row.get("camera_segment_start_frame")
    return -1 if value is None else value


def overlap(box, other):
    left, top = max(box[0], other[0]), max(box[1], other[1])
    right, bottom = min(box[2], other[2]), min(box[3], other[3])
    area = max(0.0, right - left) * max(0.0, bottom - top)
    return area / max(1e-6, (box[2] - box[0]) * (box[3] - box[1]))


def patch_colour(image, person, name):
    """Median Lab colour of one body patch, or None if it cannot be seen."""
    strips, begin, end, width = PATCHES[name]
    points = person["keypoints"]
    samples = []
    for top, bottom in strips:
        if any(points[i][2] < KEYPOINT_CONFIDENCE for i in (*top, *bottom)):
            continue
        upper = np.mean([points[i][:2] for i in top], axis=0)
        lower = np.mean([points[i][:2] for i in bottom], axis=0)
        length = float(np.linalg.norm(lower - upper))
        if length < 6:
            continue
        across = np.array([lower[1] - upper[1], upper[0] - lower[0]]) / length
        for along in np.linspace(begin, end, 7):
            for side in np.linspace(-length * width / 2, length * width / 2, 5):
                spot = upper + (lower - upper) * along + across * side
                x, y = (int(v) for v in np.rint(spot))
                if 0 <= y < image.shape[0] and 0 <= x < image.shape[1]:
                    samples.append(image[y, x])
    if len(samples) < 12:
        return None
    return [round(float(v), 1) for v in np.median(np.array(samples), axis=0)]


def body_length(person):
    """Summed limb lengths in pixels, or None if a joint is not seen."""
    points = person.get("keypoints", [])
    if len(points) != 17:
        return None
    if any(points[i][2] < KEYPOINT_CONFIDENCE for bone in BONES for i in bone):
        return None
    return sum(math.dist(points[a][:2], points[b][:2]) for a, b in BONES) / 2


def truth_letters(document, slots, height):
    """The published letter of each slot, by whose feet the labels stand on."""
    rows = document["players"]
    votes = defaultdict(Counter)
    for event in document["events"]:
        if not 0 <= event["frame"] < len(rows):
            continue
        row = rows[event["frame"]]
        feet = {}
        for person in row["players"]:
            slot = slots.get((camera(row), person.get("track_id")))
            if slot is not None:
                box = person["box"]
                feet[slot] = ((box[0] + box[2]) / 2, box[3])
        for letter in LETTERS:
            x, y = event["feet"].get(letter, (None, None))
            if x is None or y is None or not feet:
                continue
            reach = sorted(
                (math.hypot(x - fx, y - fy), slot) for slot, (fx, fy) in feet.items()
            )
            if reach[0][0] <= REACH * height:
                votes[reach[0][1]][letter] += 1
    named = {slot: count.most_common(1)[0][0] for slot, count in votes.items()}
    # Two slots under one letter means the labels did not separate them.
    doubled = {name for name, n in Counter(named.values()).items() if n > 1}
    return {slot: letter for slot, letter in named.items() if letter not in doubled}


def describe(path, capture):
    """Each slot of one rally: its letter, sizes and patch colours."""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        document = json.load(handle)
    width, height = document["video"]["width"], document["video"]["height"]
    rows = document["players"]
    slots = assign_slots(rows, width, height, float(document["video"]["fps"]))
    letters = truth_letters(document, slots, height)
    marks = [e["frame"] for e in document["events"] if 0 <= e["frame"] < len(rows)]
    if not marks:
        return None
    played = [
        i for i in range(min(marks), max(marks) + 1) if rows[i].get("calibration_valid")
    ]
    if len(played) < SAMPLES:
        return None
    tracks = {
        slot: {"slot": slot, "letter": letters.get(slot), "sizes": [], "looks": []}
        for slot in range(SLOTS)
    }
    for index in played:
        row = rows[index]
        for person in row["players"]:
            slot = slots.get((camera(row), person.get("track_id")))
            if slot is not None:
                box = person["box"]
                length = body_length(person)
                tracks[slot]["sizes"].append(
                    [
                        round(box[3], 1),
                        round(box[3] - box[1], 1),
                        round(length, 1) if length else None,
                    ]
                )
    chosen = [played[round(i)] for i in np.linspace(0, len(played) - 1, SAMPLES)]
    for index in chosen:
        capture.set(cv2.CAP_PROP_POS_FRAMES, document["start_frame"] + index)
        ok, image = capture.read()
        if not ok:
            continue
        image = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        row = rows[index]
        for person in row["players"]:
            slot = slots.get((camera(row), person.get("track_id")))
            if slot is None or len(person.get("keypoints", [])) != 17:
                continue
            # Another body in front of this one would colour the patches.
            if any(
                overlap(person["box"], other["box"]) > 0.15
                for other in row["players"]
                if other is not person
            ):
                continue
            look = {name: patch_colour(image, person, name) for name in PATCHES}
            tracks[slot]["looks"].append(look)
    return {
        "clip": document["clip_id"],
        "set": document["set_id"],
        "tracks": [t for t in tracks.values() if t["sizes"]],
    }


def load(args):
    cache = args.cache / f"{args.prefix}-{args.match}.json"
    if cache.exists() and not args.refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    video = next(
        p
        for p in sorted(args.videos.glob(f"{args.match}.*"))
        if p.suffix in (".mp4", ".webm", ".mkv")
    )
    capture = cv2.VideoCapture(str(video))
    rallies = []
    files = sorted(args.features.glob(f"{args.prefix}-{args.match}-*.json.gz"))
    for count, path in enumerate(files, 1):
        rally = describe(path, capture)
        if rally:
            rallies.append(rally)
        if count % 10 == 0:
            print(f"described {count}/{len(files)}", flush=True)
    capture.release()
    args.cache.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rallies), encoding="utf-8")
    return rallies


def vectors(rallies, use):
    """One feature vector per track; missing parts are left as NaN."""
    # A body's size in the picture shrinks with distance: take out the trend
    # against where the feet are, fitted over every player and frame.
    column = 2 if "length" in use else 1
    sizes = np.array(
        [
            (s[0], s[column])
            for r in rallies
            for t in r["tracks"]
            for s in t["sizes"]
            if s[column]
        ]
    )
    trend = np.polyfit(sizes[:, 0], np.log(sizes[:, 1]), 2)
    for rally in rallies:
        for track in rally["tracks"]:
            parts = []
            if "size" in use or "length" in use:
                size = np.array(
                    [(s[0], s[column]) for s in track["sizes"] if s[column]]
                )
                if len(size) >= 10:
                    tall = np.log(size[:, 1]) - np.polyval(trend, size[:, 0])
                    # Standing size: much of a rally is spent crouched.
                    parts.append([float(np.percentile(tall, 80))])
                else:
                    parts.append([math.nan])
            for name in PATCHES:
                if name not in use:
                    continue
                seen = [look[name] for look in track["looks"] if look.get(name)]
                parts.append(
                    np.median(np.array(seen), axis=0).tolist()
                    if len(seen) >= 2
                    else [math.nan] * 3
                )
            track["vector"] = np.array([v for part in parts for v in part], float)


def split_two(pairs, rounds=20):
    """Order each pair of vectors so the first members are alike.

    `pairs` is a list of (first, second) vectors whose order means nothing:
    the same two things each time, seen in either order. The midpoint of a
    pair does not depend on its order, so how much midpoints vary from pair to
    pair measures the noise in each feature, and features are weighed by it.
    The differences first minus second then point one way or the other along
    one line; the line of best fit gives a first ordering, which is refined by
    fitting the two things themselves. Returns per pair a sign (+1 keeps the
    order) and how many noise units separate the two orderings.
    """
    if not pairs:
        return np.zeros(0), np.zeros(0)
    first = np.array([a for a, _ in pairs])
    second = np.array([b for _, b in pairs])
    noise = np.nanstd((first + second) / 2, axis=0) * math.sqrt(2)
    noise = np.where(noise > 1e-6, noise, 1.0)
    first, second = first / noise, second / noise
    gaps = np.where(np.isnan(first - second), 0.0, first - second)
    _, _, axes = np.linalg.svd(gaps, full_matrices=False)
    signs = np.where(gaps @ axes[0] >= 0, 1.0, -1.0)
    for _ in range(rounds):
        keep = signs[:, None] > 0
        one = np.nanmedian(np.where(keep, first, second), axis=0)
        two = np.nanmedian(np.where(keep, second, first), axis=0)

        def cost(left, right):
            return np.nansum(np.abs(left - one), axis=1) + np.nansum(
                np.abs(right - two), axis=1
            )

        margin = cost(second, first) - cost(first, second)
        updated = np.where(margin >= 0, 1.0, -1.0)
        if (updated == signs).all():
            break
        signs = updated
    return signs, np.abs(margin)


def group(rallies):
    """Name every track 0 to 3 (two teams, two partners) from looks alone."""
    # Teams: the pairs at the two ends of one rally are different teams.
    ends = []
    for rally in rallies:
        by_end = defaultdict(list)
        for track in rally["tracks"]:
            by_end[track["slot"] // 2].append(track)
        if len(by_end) == 2:
            ends.append((by_end[0], by_end[1]))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        means = [
            tuple(np.nanmean([t["vector"] for t in end], axis=0) for end in pair)
            for pair in ends
        ]
        signs, margins = split_two(means)
    teams = defaultdict(list)
    for (far, near), sign, margin in zip(ends, signs, margins):
        for end, team in ((far, 0 if sign > 0 else 1), (near, 1 if sign > 0 else 0)):
            for track in end:
                track["team"], track["team_margin"] = team, float(margin)
            teams[team].append(end)
    # Partners: within a team, the two at one end are different people.
    for team, members in teams.items():
        both = [end for end in members if len(end) == 2]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            signs, margins = split_two([(e[0]["vector"], e[1]["vector"]) for e in both])
        for end, sign, margin in zip(both, signs, margins):
            first, second = (0, 1) if sign > 0 else (1, 0)
            end[0]["person"], end[1]["person"] = team * 2 + first, team * 2 + second
            end[0]["margin"] = end[1]["margin"] = float(margin)


def score(rallies):
    """Agreement of the grouping with the published letters."""
    tracks = [
        t for r in rallies for t in r["tracks"] if t.get("letter") and "team" in t
    ]
    # Which letters are partners: the two that share a court end.
    together = Counter()
    for rally in rallies:
        by_end = defaultdict(set)
        for track in rally["tracks"]:
            if track.get("letter"):
                by_end[track["slot"] // 2].add(track["letter"])
        for letters in by_end.values():
            if len(letters) == 2:
                together[frozenset(letters)] += 1
    pair = next(iter(together.most_common(1)), (frozenset("AB"),))[0]
    side = {letter: int(letter not in pair) for letter in LETTERS}
    right = sum(t["team"] == side[t["letter"]] for t in tracks)
    team_score = max(right, len(tracks) - right) / max(1, len(tracks))
    flip = right < len(tracks) - right
    report = {"tracks": len(tracks), "team": round(team_score, 3), "partner": {}}
    whole = Counter()
    for rally in rallies:
        named = [t for t in rally["tracks"] if t.get("letter") and "person" in t]
        for track in named:
            track["team_right"] = (track["team"] == side[track["letter"]]) != flip
    for team in (0, 1):
        ends = defaultdict(list)
        for rally in rallies:
            for track in rally["tracks"]:
                if track.get("letter") and track.get("person", -1) // 2 == team:
                    ends[(rally["clip"], track["slot"] // 2)].append(track)
        votes = Counter()
        for members in ends.values():
            if len(members) == 2 and all(t["team_right"] for t in members):
                first = min(members, key=lambda t: t["person"])
                votes[first["letter"]] += 1
        total = sum(votes.values())
        if total:
            best = votes.most_common(1)[0]
            report["partner"][team] = {
                "pairs": total,
                "right": round(best[1] / total, 3),
                "first_is": best[0],
            }
            for members in ends.values():
                if len(members) == 2 and all(t["team_right"] for t in members):
                    first = min(members, key=lambda t: t["person"])
                    for t in members:
                        t["right"] = first["letter"] == best[0]
    for rally in rallies:
        named = [t for t in rally["tracks"] if t.get("letter")]
        if len(named) == SLOTS:
            whole[all(t.get("right") for t in named)] += 1
    report["rallies_with_four_named"] = sum(whole.values())
    report["all_four_right"] = round(whole[True] / max(1, sum(whole.values())), 3)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--videos", type=Path, required=True)
    parser.add_argument("--prefix", default="ds")
    parser.add_argument("--match", type=int, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".cache/identity"))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--use",
        nargs="*",
        default=["length", *PATCHES],
        help="evidence to group by: size (box height) or length (summed limbs), "
        "and any of " + ", ".join(PATCHES),
    )
    args = parser.parse_args()
    rallies = load(args)
    vectors(rallies, args.use)
    group(rallies)
    report = score(rallies)
    print(f"{args.prefix}-{args.match}: {len(rallies)} rallies, using {args.use}")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    sys.exit(main())
