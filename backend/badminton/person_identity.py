"""One persistent person id per player through a whole video, from looks alone.

The tracker follows a player only within one camera view, and actor linking
(actor_linking.py) joins a player's track pieces within that view. This groups
every view's player tracks into the same people (two in singles, four in
doubles) by how they look: clothing and shoe colour, body length and a
whole-person OSNet description. Rally order and the score are never used, so
edited highlights work, and players changing ends between games do not
matter.

Each view contributes its far and near players. The two ends of one view are
different sides (teams); in doubles the two players at one end are different
partners. Sides are split by one look per side for the whole video; partners
by comparing views with views. This is the method of
training/identity_probe.py, which put all four doubles players right in 94.5%
of rallies on the unopened DShuttleNet test matches with these settings
(docs/DOUBLES_PLAN.md). Singles is the side split alone and has no labelled
score yet.

Ids are unreviewed suggestions: the name screen and the one-tap swap exist
because looks-only grouping can still mix up partners.
"""

import json
import math
import time
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

from .config import MODEL_MANIFEST, WEIGHTS
from .identity import validate_assignments

METHOD = "looks-only person grouping v1"
SCHEMA_VERSION = 1
MANIFEST_KEY = "player_reid"
PLAYERS_PER_END = {"singles": 1, "doubles": 2}
# Frames looked at per view (the setting that scored 94.5% on the test
# matches), and the fewest rows a view needs before it is grouped at all.
SAMPLES = 16
MIN_VIEW_ROWS = 8
# Pictures wanted of each player per view. Partners often stand close
# together, so evenly spaced frames can miss one of them unobstructed
# entirely; frames where that player stands clear are then added.
MIN_LOOKS = 4
# A player never seen clear in a view (another box covering more than CLEAR
# of theirs) is pictured in the frames where they are least covered, up to
# PARTLY, skipping colour samples inside the box of whoever stands in front.
CLEAR = 0.15
PARTLY = 0.5
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
EVIDENCE = ("length", *PATCHES, "reid")
# Partner comparisons: weight of colour and size against the whole-person
# description, and how many strongest comparisons each view keeps.
AGREE_COLOUR = 0.5
AGREE_LINKS = 10
BATCH = 64
THUMBNAIL_MARGIN = 0.08
# Plain JSON values, as stored in the document's provenance.
RECIPE = json.loads(
    json.dumps(
        {
            "method": METHOD,
            "samples": SAMPLES,
            "min_view_rows": MIN_VIEW_ROWS,
            "min_looks": MIN_LOOKS,
            "clear": CLEAR,
            "partly": PARTLY,
            "patches": PATCHES,
            "keypoint_confidence": KEYPOINT_CONFIDENCE,
            "bones": [list(b) for b in BONES],
            "evidence": list(EVIDENCE),
            "sides_by": "one look per side for the whole video, end look taken out",
            "partners_by": "views compared with views",
            "agree_colour": AGREE_COLOUR,
            "agree_links": AGREE_LINKS,
            "players_per_end": PLAYERS_PER_END,
            "uses": "tracked boxes and poses, actor-linked tracks with court ends, "
            "decoded source frames; never rally order, score or annotations",
        }
    )
)


# Rows and views -----------------------------------------------------------


def chains_of(identity_run):
    """Per (run, track) its joined chain (camera view, continuity) and end."""
    return {
        (t["run_id"], t["track_id"]): (
            (t["camera_segment_start_frame"], t.get("continuity_id", t["actor_id"])),
            t.get("court_end"),
        )
        for t in identity_run["tracks"]
    }


def player_rows(identity_run, player_runs):
    """Per frame the tracked players, each with its joined chain and end.

    `player_runs` yields (run ID, player run) in window order; each frame is
    taken from the window that owns it (its core range), so overlapping
    windows are not counted twice. Only calibrated live frames are used, as in
    actor linking: replays marked in the scene review and frames without a
    court are left out.
    """
    chains = chains_of(identity_run)
    rows = {}
    for run_id, run in player_runs:
        first = run.get("analysis_core_start_frame", run["start_frame"])
        last = run.get("analysis_core_end_frame", run["end_frame"])
        for row in run["frames"]:
            if not first <= row["frame"] < last:
                continue
            if row.get("calibration_valid") is not True:
                continue
            if row.get("scene", "live") != "live":
                continue
            people = []
            for person in row["players"]:
                chain, end = chains.get((run_id, person.get("track_id")), (None, None))
                if chain and end:
                    people.append(
                        person | {"run_id": run_id, "chain": chain, "end": end}
                    )
            rows[row["frame"]] = {"frame": row["frame"], "players": people}
    return rows


def find_views(rows, mode):
    """Camera views with players at both ends, `per_end` slots per end.

    Slots 0 and 1 are the far end, 2 and 3 the near end; in singles only
    slots 0 and 2 are used. An official or a stray detection is shorter-lived
    than a player, so each end keeps its longest-tracked chains.
    """
    per_end = PLAYERS_PER_END[mode]
    by_view = defaultdict(list)
    for frame in sorted(rows):
        for view in {p["chain"][0] for p in rows[frame]["players"]}:
            by_view[view].append(rows[frame])
    found = []
    for view, own in sorted(by_view.items()):
        seen = Counter(
            (p["end"], p["chain"])
            for row in own
            for p in row["players"]
            if p["chain"][0] == view
        )
        slots = {}
        for number, end in enumerate(("far", "near")):
            longest = sorted(
                ((n, chain) for (e, chain), n in seen.items() if e == end),
                reverse=True,
            )[:per_end]
            for place, (_, chain) in enumerate(longest):
                slots[chain] = number * 2 + place
        if len(own) >= MIN_VIEW_ROWS and {s // 2 for s in slots.values()} == {0, 1}:
            found.append({"view": view, "rows": own, "slots": slots})
    return found


# Looks ---------------------------------------------------------------------


def overlap(box, other):
    left, top = max(box[0], other[0]), max(box[1], other[1])
    right, bottom = min(box[2], other[2]), min(box[3], other[3])
    area = max(0.0, right - left) * max(0.0, bottom - top)
    return area / max(1e-6, (box[2] - box[0]) * (box[3] - box[1]))


def covered(row, person):
    """The largest share of a player's box that another box covers."""
    return max(
        (overlap(person["box"], o["box"]) for o in row["players"] if o is not person),
        default=0.0,
    )


def clear(row, person, limit=CLEAR):
    """Whether a player can be pictured: full pose, no other body in front."""
    return len(person.get("keypoints", [])) == 17 and covered(row, person) <= limit


def patch_colour(image, person, name, hidden=()):
    """Median Lab colour of one body patch, or None if it cannot be seen.
    Points inside any box of `hidden` (bodies in front) are not sampled."""
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
                if any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in hidden):
                    continue
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


def frames_to_look_at(rows, slot_of, samples=SAMPLES, wanted=MIN_LOOKS, slots=4):
    """Evenly spaced rows, plus rows where a player short of clear views is
    seen clear, chosen from the tracks alone before any video is decoded.
    Returns the chosen row indices and, per slot never seen clear, the rows
    where it is pictured partly covered."""
    played = list(range(len(rows)))
    chosen = {played[round(i)] for i in np.linspace(0, len(played) - 1, samples)}
    clear_in = defaultdict(list)
    for index in played:
        row = rows[index]
        for person in row["players"]:
            slot = slot_of(person)
            if slot is not None and clear(row, person):
                clear_in[slot].append(index)
    for frames in clear_in.values():
        have = sum(index in chosen for index in frames)
        spare = [index for index in frames if index not in chosen]
        if have < wanted and spare:
            extra = min(wanted - have, len(spare))
            chosen |= {spare[round(i)] for i in np.linspace(0, len(spare) - 1, extra)}
    # Players never clear: their least covered moments, a few frames apart.
    partly = {}
    for slot in range(slots):
        if clear_in.get(slot):
            continue
        options = []
        for index in played:
            row = rows[index]
            for person in row["players"]:
                if slot_of(person) == slot and clear(row, person, PARTLY):
                    options.append((covered(row, person), index))
        picked = []
        for _, index in sorted(options):
            if all(abs(index - other) >= 5 for other in picked):
                picked.append(index)
            if len(picked) == wanted:
                break
        chosen |= set(picked)
        partly[slot] = set(picked)
    return sorted(chosen), partly


def view_tracks(view):
    """Per slot of a view its sizes over every row (no video needed)."""
    tracks = {slot: {"slot": slot, "sizes": [], "looks": []} for slot in range(4)}
    for row in view["rows"]:
        for person in row["players"]:
            slot = view["slots"].get(person["chain"])
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
    return tracks


def look_at(image, picture, row, slot_of, partly):
    """Patch colours and a crop of each slotted player in one decoded row.

    `image` is the frame in Lab, `picture` the same frame in BGR. Yields
    (slot, look, crop or None, clear) for every player who can be pictured.
    """
    for person in row["players"]:
        slot = slot_of(person)
        if slot is None:
            continue
        hidden = ()
        seen_clear = clear(row, person)
        if not seen_clear:
            if slot not in partly or not clear(row, person, PARTLY):
                continue
            # In front: the body whose feet are nearer the camera.
            hidden = [
                o["box"]
                for o in row["players"]
                if o is not person and o["box"][3] > person["box"][3]
            ]
        look = {name: patch_colour(image, person, name, hidden) for name in PATCHES}
        left, top, right, bottom = (int(v) for v in person["box"])
        crop = picture[max(0, top) : bottom, max(0, left) : right]
        usable = crop.shape[0] >= 16 and crop.shape[1] >= 8
        yield slot, look, (crop if usable else None), seen_clear, person


# Grouping ------------------------------------------------------------------


def vectors(rallies, use=EVIDENCE):
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
    trend = np.polyfit(sizes[:, 0], np.log(sizes[:, 1]), 2) if len(sizes) >= 3 else None
    for rally in rallies:
        for track in rally["tracks"]:
            parts = []
            if "size" in use or "length" in use:
                size = np.array(
                    [(s[0], s[column]) for s in track["sizes"] if s[column]]
                )
                if len(size) >= 10 and trend is not None:
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
            track["whole"] = (
                np.array(track["reid"], float)
                if "reid" in use and track.get("reid")
                else None
            )


def split_two(pairs, rounds=20, centre=False):
    """Order each pair of vectors so the first members are alike.

    `pairs` is a list of (first, second) vectors whose order means nothing:
    the same two things each time, seen in either order. The midpoint of a
    pair does not depend on its order, so how much midpoints vary from pair to
    pair measures the noise in each feature, and features are weighed by it.
    The differences first minus second then point one way or the other along
    one line; the line of best fit gives a first ordering, which is refined by
    fitting the two things themselves. Returns per pair a sign (+1 keeps the
    order) and how many noise units separate the two orderings.

    With `centre`, the average difference is taken out before the line is
    fitted: the far and near side of a view look different because of the end
    itself (front or back of the shirt, light), and when that is larger than
    the side difference the line would find the end instead.
    """
    if not pairs:
        return np.zeros(0), np.zeros(0)
    first = np.array([a for a, _ in pairs])
    second = np.array([b for _, b in pairs])
    noise = np.nanstd((first + second) / 2, axis=0) * math.sqrt(2)
    noise = np.where(noise > 1e-6, noise, 1.0)
    first, second = first / noise, second / noise
    gaps = np.where(np.isnan(first - second), 0.0, first - second)
    if centre:
        gaps = gaps - gaps.mean(axis=0)
    _, _, axes = np.linalg.svd(gaps, full_matrices=False)
    signs = np.where(gaps @ axes[0] >= 0, 1.0, -1.0)
    margin = np.zeros(len(pairs))
    for _ in range(rounds):
        keep = signs[:, None] > 0
        one = np.nanmedian(np.where(keep, first, second), axis=0)
        two = np.nanmedian(np.where(keep, second, first), axis=0)

        def cost(left, right, one=one, two=two):
            return np.nansum(np.abs(left - one), axis=1) + np.nansum(
                np.abs(right - two), axis=1
            )

        margin = cost(second, first) - cost(first, second)
        updated = np.where(margin >= 0, 1.0, -1.0)
        if (updated == signs).all():
            break
        signs = updated
    return signs, np.abs(margin)


def agree(pairs, wholes, colour=AGREE_COLOUR, links=AGREE_LINKS):
    """Order each pair so the first members are alike, by comparing pairs.

    For every two pairs i and j, how much more alike they are kept as they
    are than crossed (first with second) is measured on the whole-person
    descriptions (cosine) and, at weight `colour`, on the other evidence
    (noise-weighted distance). Only each pair's `links` strongest comparisons
    are kept, so the ordering can follow a gradual change (a change of kit
    between games) instead of fitting one look per person to the whole match.
    The signs that agree best with all comparisons are the leading
    eigenvector, then refined one pair at a time. Returns per pair a sign
    (+1 keeps the order) and the share of the comparisons that back it.
    """
    count = len(pairs)
    if count == 0:
        return np.zeros(0), np.zeros(0)
    agreement = np.zeros((count, count))
    seen = np.array([a is not None and b is not None for a, b in wholes])
    if seen.any():
        first = np.zeros((count, len(next(a for a, b in wholes if a is not None))))
        second = np.zeros_like(first)
        for i, (a, b) in enumerate(wholes):
            if seen[i]:
                first[i], second[i] = a / np.linalg.norm(a), b / np.linalg.norm(b)
        middle = (first[seen].sum(0) + second[seen].sum(0)) / (2 * seen.sum())
        first[seen] -= middle
        second[seen] -= middle
        agreement += first @ first.T + second @ second.T
        agreement -= first @ second.T + second @ first.T
    if colour:
        first = np.array([a for a, _ in pairs])
        second = np.array([b for _, b in pairs])
        noise = np.nanstd((first + second) / 2, axis=0) * math.sqrt(2)
        noise = np.where(noise > 1e-6, noise, 1.0)
        first, second = first / noise, second / noise

        def apart(left, right):
            gap = np.nanmean(np.abs(left[:, None, :] - right[None, :, :]), axis=2)
            return np.nan_to_num(gap, nan=0.0)

        looks = apart(first, second) + apart(second, first)
        looks -= apart(first, first) + apart(second, second)
        looks /= max(1e-9, float(np.std(looks)))
        agreement += colour * looks * (float(np.std(agreement)) if seen.any() else 1.0)
    np.fill_diagonal(agreement, 0)
    if links and links < count - 1:
        strongest = np.argsort(-np.abs(agreement), axis=1)[:, :links]
        keep = np.zeros_like(agreement, bool)
        keep[np.arange(count)[:, None], strongest] = True
        agreement = np.where(keep | keep.T, agreement, 0)
    signs = np.where(np.linalg.eigh(agreement)[1][:, -1] >= 0, 1.0, -1.0)
    for _ in range(50):
        updated = np.where(agreement @ signs >= 0, 1.0, -1.0)
        if (updated == signs).all():
            break
        signs = updated
    # Share of the comparisons that back each pair's order, -1 to 1.
    support = signs * (agreement @ signs) / np.maximum(1e-9, np.abs(agreement).sum(1))
    return signs, support


def group(rallies, mode):
    """Name every track: a side (0 or 1) and, in doubles, a person 0 to 3.

    Singles persons are the sides. Tracks of a doubles end where only one
    partner was found keep their side but get no person.
    """
    # Sides: the players at the two ends of one view are different sides.
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
        signs, margins = split_two(means, centre=True)
    teams = defaultdict(list)
    for (far, near), sign, margin in zip(ends, signs, margins):
        for end, team in ((far, 0 if sign > 0 else 1), (near, 1 if sign > 0 else 0)):
            for track in end:
                track["team"], track["team_margin"] = team, float(margin)
                if mode == "singles":
                    track["person"], track["margin"] = team, None
            teams[team].append(end)
    if mode == "singles":
        return
    # Partners: within a side, the two at one end are different people.
    for team, members in teams.items():
        both = [end for end in members if len(end) == 2]
        looks = {id(t): t["vector"] for end in both for t in end}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            # A pair looks different from each end (front or back, light,
            # distance). Take out each end's average pair look, so that
            # difference is not read as one partner against the other.
            for place in (0, 1):
                here = [end for end in both if end[0]["slot"] // 2 == place]
                if here:
                    middle = np.nanmean(
                        [(looks[id(a)] + looks[id(b)]) / 2 for a, b in here], axis=0
                    )
                    for end in here:
                        for t in end:
                            looks[id(t)] = looks[id(t)] - middle
            pairs = [tuple(looks[id(t)] for t in end) for end in both]
            signs, margins = agree(pairs, [(a["whole"], b["whole"]) for a, b in both])
        for end, sign, margin in zip(both, signs, margins):
            first, second = (0, 1) if sign > 0 else (1, 0)
            end[0]["person"], end[1]["person"] = team * 2 + first, team * 2 + second
            end[0]["margin"] = end[1]["margin"] = float(margin)


def canonical_ids(rallies, mode):
    """Stable labels: side T1 is at the far end of the first view; in doubles
    P1 is the far-left player of T1's first view with both partners, P3 the
    far-left of T2's (by median foot position). Returns {internal: label}."""
    first_far = next(
        (
            t["team"]
            for r in rallies
            for t in r["tracks"]
            if t["slot"] // 2 == 0 and "team" in t
        ),
        0,
    )
    side = {first_far: 0, 1 - first_far: 1}
    if mode == "singles":
        return {person: f"P{side[person] + 1}" for person in (0, 1)}
    labels = {}
    for team in (0, 1):
        order = None
        for rally in rallies:
            pair = [
                t for t in rally["tracks"] if t.get("team") == team and "person" in t
            ]
            if len(pair) == 2:
                order = [t["person"] for t in sorted(pair, key=lambda t: t["foot_x"])]
                break
        if order is None:
            order = [team * 2, team * 2 + 1]
        for place, person in enumerate(order):
            labels[person] = f"P{side[team] * 2 + place + 1}"
    return labels


# Running on a video ------------------------------------------------------------


def manifest_entry():
    return json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))[MANIFEST_KEY]


def load_model(entry=None):
    """The pinned OSNet weights, checked against the model manifest."""
    import hashlib

    import torch  # noqa: F401  # initialize before threaded PyAV
    import torchvision  # noqa: F401

    from . import osnet

    entry = entry or manifest_entry()
    path = WEIGHTS / entry["name"]
    if not path.is_file():
        raise RuntimeError(f"Player re-identification weights missing: {path}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise RuntimeError(
            "Player re-identification weights do not match the model manifest"
        )
    return osnet.load(path)


def describe_views(views, decode, describe, progress=None, prepare=None):
    """Sizes, colours and whole looks of every slot of every view.

    `decode(frames)` yields (frame number, BGR image) for the requested frame
    numbers in order; `describe(crops)` returns one unit description per crop.
    `prepare()`, when given, runs once before decoding if any frame is needed
    (the model must be loaded before threaded decoding starts). Returns per
    view the probe-style tracks and per (view, slot) the best thumbnail
    candidate (largest clear crop) with its description.
    """
    per_view, plans = [], []
    needed = defaultdict(list)
    for number, view in enumerate(views):
        slots = view["slots"]

        def slot_of(person, slots=slots):
            return slots.get(person["chain"])

        tracks = view_tracks(view)
        chosen, partly = frames_to_look_at(view["rows"], slot_of)
        per_view.append(tracks)
        plans.append((slot_of, partly))
        for index in chosen:
            needed[view["rows"][index]["frame"]].append((number, index))
    sums, counts, best = {}, Counter(), {}
    batch, owners = [], []

    def flush():
        if not batch:
            return
        described = describe(batch)
        for (number, slot, candidate), vector in zip(owners, described):
            key = (number, slot)
            sums[key] = sums.get(key, 0) + np.asarray(vector, float)
            counts[key] += 1
            if candidate is not None:
                candidate["vector"] = np.asarray(vector, float)
        batch.clear()
        owners.clear()

    frames = sorted(needed)
    if frames and prepare:
        prepare()
    for done, (frame, picture) in enumerate(decode(frames), 1):
        image = cv2.cvtColor(picture, cv2.COLOR_BGR2LAB)
        for number, index in needed[frame]:
            slot_of, partly = plans[number]
            row = views[number]["rows"][index]
            for slot, look, crop, seen_clear, person in look_at(
                image, picture, row, slot_of, partly
            ):
                per_view[number][slot]["looks"].append(look)
                if crop is None:
                    continue
                candidate = None
                area = crop.shape[0] * crop.shape[1]
                key = (number, slot)
                if seen_clear and area > best.get(key, {}).get("area", -1):
                    candidate = {
                        "area": area,
                        "frame": frame,
                        "box": [float(v) for v in person["box"]],
                        "crop": thumbnail_crop(picture, person["box"]),
                    }
                    best[key] = candidate
                batch.append(crop)
                owners.append((number, slot, candidate))
        if len(batch) >= BATCH:
            flush()
        if progress:
            progress(done / max(1, len(frames)))
    flush()
    rallies = []
    for number, view in enumerate(views):
        tracks = per_view[number]
        by_slot = {slot: chain for chain, slot in view["slots"].items()}
        kept = []
        for slot, track in tracks.items():
            if not track["sizes"]:
                continue
            if counts[(number, slot)]:
                track["reid"] = [
                    round(float(v), 4)
                    for v in sums[(number, slot)] / counts[(number, slot)]
                ]
            track["chain"] = by_slot[slot]
            track["foot_x"] = float(
                np.median(
                    [
                        (p["box"][0] + p["box"][2]) / 2
                        for row in view["rows"]
                        for p in row["players"]
                        if p["chain"] == track["chain"]
                    ]
                )
            )
            kept.append(track)
        rallies.append({"view": view["view"], "tracks": kept})
    return rallies, best, len(frames)


def thumbnail_crop(picture, box):
    """The player's box with a small margin, clipped to the frame."""
    left, top, right, bottom = box
    pad_x = (right - left) * THUMBNAIL_MARGIN
    pad_y = (bottom - top) * THUMBNAIL_MARGIN
    height, width = picture.shape[:2]
    x1, y1 = max(0, int(left - pad_x)), max(0, int(top - pad_y))
    x2, y2 = min(width, int(right + pad_x)), min(height, int(bottom + pad_y))
    return picture[y1:y2, x1:x2].copy()


def choose_thumbnails(rallies, best, labels):
    """Per person label the clearest crop that looks most like them: among
    their views' largest clear crops, the one nearest their average look."""
    by_person = defaultdict(list)
    for number, rally in enumerate(rallies):
        for track in rally["tracks"]:
            label = labels.get(track.get("person"))
            candidate = best.get((number, track["slot"]))
            if label and candidate is not None and "vector" in candidate:
                by_person[label].append(candidate)
    chosen = {}
    for label, candidates in by_person.items():
        middle = np.mean([c["vector"] for c in candidates], axis=0)
        largest = sorted(candidates, key=lambda c: -c["area"])
        top = largest[: max(1, len(largest) // 2)]
        chosen[label] = max(top, key=lambda c: float(c["vector"] @ middle))
    return chosen


def without_overlaps(assignments):
    """One person's tracks of one run, cut so that their ranges do not overlap.

    Actor linking can join two tracker IDs of one window into one player when
    the tracker briefly gave the player a new ID and then the old one again
    (the two are never seen in the same frame, but the long track's range
    spans the short one; DShuttleNet match 52, tracks 2 and 38). A shorter
    track keeps its range; a longer one gives up the frames it shares with
    it, so those frames go to the track that was seen there.
    """
    groups = defaultdict(list)
    for item in assignments:
        groups[(item["run_id"], item["player_id"])].append(item)
    result = []
    for items in groups.values():
        taken = []
        for item in sorted(
            items,
            key=lambda a: (a["end_frame"] - a["start_frame"], a["start_frame"]),
        ):
            pieces = [(item["start_frame"], item["end_frame"])]
            for start, end in taken:
                pieces = [
                    piece
                    for low, high in pieces
                    for piece in ((low, min(high, start)), (max(low, end), high))
                    if piece[0] < piece[1]
                ]
            result += [item | {"start_frame": s, "end_frame": e} for s, e in pieces]
            taken.append((item["start_frame"], item["end_frame"]))
    return result


def build_document(mode, rallies, identity_run, labels, provenance):
    """The persons and TrackAssignment records of one video."""
    per_end = PLAYERS_PER_END[mode]
    count = 2 * per_end
    teams = {f"P{n + 1}": "T1" if n < per_end else "T2" for n in range(count)}
    person_of = {}
    for rally in rallies:
        for track in rally["tracks"]:
            label = labels.get(track.get("person"))
            if label:
                margin = track.get("margin")
                person_of[track["chain"]] = (
                    label,
                    None if margin is None else round(min(1.0, max(0.0, margin)), 3),
                )
    chains = chains_of(identity_run)
    assignments = []
    for track in identity_run["tracks"]:
        chain, _ = chains[(track["run_id"], track["track_id"])]
        if chain not in person_of:
            continue
        label, certainty = person_of[chain]
        assignments.append(
            {
                "run_id": track["run_id"],
                "track_id": track["track_id"],
                "start_frame": track["start_frame"],
                "end_frame": track["end_frame"],
                "player_id": label,
                "certainty": certainty,
            }
        )
    assignments = without_overlaps(assignments)
    assignments.sort(key=lambda a: (a["start_frame"], a["run_id"], a["track_id"]))
    # The same checks a reviewed identity map passes.
    validate_assignments(
        [{k: v for k, v in a.items() if k != "certainty"} for a in assignments],
        player_ids=set(teams),
        frame_count=identity_run["end_frame"],
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "persons": [
            {"id": label, "team": team, "thumbnail": None}
            for label, team in teams.items()
        ],
        "assignments": assignments,
        "provenance": provenance,
    }


def identify_persons(
    video,
    identity_run,
    player_runs,
    decode,
    describe,
    thumbnails_dir=None,
    thumbnail_prefix="",
    progress=None,
    provenance=None,
    prepare=None,
):
    """Group a processed video's player tracks into persons.

    `decode`, `describe` and `prepare` are as for describe_views.
    `thumbnails_dir`, when given, receives one JPEG per person, recorded in
    the document as `thumbnail_prefix` + file name.
    """
    began = time.monotonic()
    mode = video["mode"]
    if mode not in PLAYERS_PER_END:
        raise ValueError("Person identity needs a singles or doubles video")
    rows = player_rows(identity_run, player_runs)
    views = find_views(rows, mode)
    rallies, best, decoded = describe_views(views, decode, describe, progress, prepare)
    if rallies and any(t["sizes"] for r in rallies for t in r["tracks"]):
        vectors(rallies)
        group(rallies, mode)
    labels = canonical_ids(rallies, mode)
    named = [
        sum("person" in t for t in r["tracks"]) == 2 * PLAYERS_PER_END[mode]
        for r in rallies
    ]
    frames = Counter()
    for row in rows.values():
        for person in row["players"]:
            frames[person["chain"]] += 1
    person_chains = {
        t["chain"] for r in rallies for t in r["tracks"] if labels.get(t.get("person"))
    }
    summary = {
        "views": len(views),
        "views_all_named": sum(named),
        "decoded_frames": decoded,
        "player_track_frames": sum(frames.values()),
        "player_track_frames_named": sum(
            n for chain, n in frames.items() if chain in person_chains
        ),
        "elapsed_s": round(time.monotonic() - began, 2),
    }
    document = build_document(
        mode,
        rallies,
        identity_run,
        labels,
        {
            "method": METHOD,
            "recipe": RECIPE,
            "summary": summary,
            "certainty_meaning": "doubles: share of view-to-view comparisons "
            "backing the partner order (0 to 1, unvalidated as a probability); "
            "singles: null (sides only)",
            "meaning": "Unreviewed looks-only grouping; not verified identity. "
            "Sides and partners can be wrong; names are confirmed by a person.",
            **(provenance or {}),
        },
    )
    if thumbnails_dir is not None:
        thumbnails_dir = Path(thumbnails_dir)
        thumbnails_dir.mkdir(parents=True, exist_ok=True)
        chosen = choose_thumbnails(rallies, best, labels)
        pictured = {}
        for person in document["persons"]:
            candidate = chosen.get(person["id"])
            if candidate is None:
                continue
            ok, encoded = cv2.imencode(".jpg", candidate["crop"])
            if not ok:
                continue
            name = f"{person['id']}.jpg"
            (thumbnails_dir / name).write_bytes(encoded.tobytes())
            person["thumbnail"] = thumbnail_prefix + name
            pictured[person["id"]] = {
                "frame": candidate["frame"],
                "box": [round(v, 1) for v in candidate["box"]],
            }
        document["provenance"]["thumbnails"] = pictured
    return document


def source_decoder(video, root, times, gap_s=30.0):
    """Decode requested frame numbers by source PTS (video.iter_frames).

    Requested frames closer than `gap_s` are read in one pass; a longer gap
    starts a new read from the nearest keyframe before the next frame.
    """
    from .video import iter_frames

    def decode(frames):
        groups = []
        for frame in frames:
            if groups and times[frame] - times[groups[-1][-1]] <= gap_s:
                groups[-1].append(frame)
            else:
                groups.append([frame])
        for group in groups:
            wanted = set(group)
            for index, _, frame in iter_frames(
                video, root, times, group[0], group[-1] + 1
            ):
                if index in wanted:
                    yield index, frame.to_ndarray(format="bgr24")

    return decode


def document_folder(data, video_id, run_id):
    return Path(data) / video_id / "persons" / run_id


def reid_describer(entry):
    """(prepare, describe, device) for the pinned OSNet weights.

    Only a video with players to picture needs torch and the weights, so they
    load in `prepare`, which runs before any frame is decoded. `device()` is
    where the model ran, or None if it never loaded.
    """
    loaded = {}

    def prepare():
        from . import osnet

        loaded["model"], loaded["describe"] = load_model(entry), osnet.describe

    def describe(crops):
        return loaded["describe"](loaded["model"], crops)

    def device():
        if "model" not in loaded:
            return None
        return str(next(loaded["model"].parameters()).device)

    return prepare, describe, device


def run_stage(
    video,
    root,
    data,
    times,
    identity_run,
    identity_run_id,
    player_runs,
    output,
    progress,
):
    """The pipeline's persons stage: write the document, thumbnails and the
    stage record at `output` (runs/<run ID>.json)."""
    from .video import write_json

    entry = manifest_entry()
    prepare, describe, device = reid_describer(entry)
    run_id = Path(output).stem
    folder = document_folder(data, video["id"], run_id)
    player_runs = list(player_runs)
    document = identify_persons(
        video,
        identity_run,
        player_runs,
        source_decoder(video, root, times),
        describe,
        thumbnails_dir=folder,
        thumbnail_prefix=f"persons/{run_id}/",
        progress=progress,
        prepare=prepare,
        provenance={
            "model": {"name": entry["name"], "sha256": entry["sha256"]},
            "identities_run_id": identity_run_id,
            "player_run_ids": [run_id for run_id, _ in player_runs],
            "thumbnail_root": "the video's data folder",
        },
    )
    document["provenance"]["device"] = device()
    path = folder / "persons.json"
    write_json(path, document)
    write_json(
        output,
        {
            "schema_version": 1,
            "stage": "persons",
            "video_id": video["id"],
            "video_sha256": video["sha256"],
            "start_frame": 0,
            "end_frame": len(times),
            "method": METHOD,
            "document": path.relative_to(Path(data) / video["id"]).as_posix(),
            "document_sha256": _file_sha(path),
            "person_count": len(document["persons"]),
            "assignment_count": len(document["assignments"]),
            **document["provenance"]["summary"],
        },
    )
    progress(1)


def _file_sha(path):
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_document(data, video_id, checkpoint):
    """The persons document of a finished persons stage, hash-checked.

    `checkpoint` is the analysis plan's "persons" entry (run_id, sha256).
    """
    run_path = Path(data) / video_id / "runs" / f"{checkpoint['run_id']}.json"
    if _file_sha(run_path) != checkpoint["sha256"]:
        raise ValueError("Persons stage record changed since processing")
    run = json.loads(run_path.read_text(encoding="utf-8"))
    path = Path(data) / video_id / run["document"]
    if not path.is_file() or _file_sha(path) != run["document_sha256"]:
        raise ValueError("Persons document changed or is missing since processing")
    return json.loads(path.read_text(encoding="utf-8"))
