# First reviewed development pilot

Prepared October 17, 2026. This increment adds a reproducible review/evaluation loop and reviewed player identities. It does not establish release accuracy or train a shot classifier.

## Saved review data

The source-only visual audit inspected every frame of two short partial rallies. Singles contact neighborhoods were also inspected at the original 1280x720 resolution. The assistant knew the model suggestions and selected windows, so these are development labels, not a blinded or independently adjudicated benchmark. A knowledgeable human second review remains necessary.

| Source | Reviewed interval, end excluded | Contacts | Reviewed identity mappings | Shuttle points |
| --- | --- | --- | --- | --- |
| Singles | frames 2000-2100, 80.00-84.00 s | 2007 B, 2039 A, 2048 B, 2077 A | Track 1 to A, Track 3 to B | Four visible source frames |
| Doubles | frames 602-650, 24.08-26.00 s | 607 B, 618 C, 632 B, 643 D | Tracks 1/2/3/4 to A/B/C/D | None yet |

Events and mappings are saved at annotation revision **2** in each video's real local database. The previous calibration-only revisions remain available. Singles A is the near red player; B is the far yellow player. Doubles A/B are initially near left/right; C/D are initially far front/back. Identity mappings are limited to the inspected ranges and original player runs. They do not assert continuity through later crossings or end changes.

Contact timing uncertainty is approximately one to two source frames (40-80 ms). Every shot family and stroke side remains `unknown`; player handedness is also unknown. Both reviewed intervals start and finish within an exchange, so no serve or rally-ending event was invented. These are exhaustive contacts within partial rallies, not complete rally labels.

The [tracked pilot manifest](../data/manifests/pilot_review.json) preserves source hashes, visual evidence, uncertainty, and review limits. Its conservative scene labels are unknown. The imported singles scene uses an explicit **live-play inference**: the surrounding highlight progresses from a 12-11 exchange through a player close-up to a new 12-12 exchange. This inference and its basis are recorded in the saved review notes. Doubles live/replay status remains unconfirmed and is excluded from contact scoring.

## Initial measurements

The cached detector was evaluated unchanged against the new labels. Matching maximizes the number of one-to-one matches within tolerance, then minimizes total absolute source-time error. Proposals outside the reviewed interval are excluded rather than labeled false.

| Measurement | Result | Sample and interpretation |
| --- | --- | --- |
| Singles contact precision | 50.0% | One correct proposal and one false proposal |
| Singles contact recall | 25.0% | One of four reviewed contacts found; three missed |
| Singles contact F1 | 33.3% | Same result at 120 ms and 40 ms tolerances |
| Singles shuttle localization | 4/4 within 7.34 px | Deliberately selected, clearly visible positive frames; mean error 1.41 px |
| Doubles contact/localization | Unscored | Scene unconfirmed; no shuttle point labels |

The only matched singles proposal is frame 2007. Frame 2060 is a false suggestion near a flight apex; the source-frame review instead places that player's preceding contact at 2048. Contacts at 2039 and 2077 were also missed. This establishes a concrete failure of the current heuristic on this development clip. It is too small a sample to estimate general performance or justify class-specific conclusions.

The failure diagnosis identifies an upstream gate: every missed contact's seven-frame motion window contains missing raw shuttle observations. Frame 2039 is followed by missing detections 2040-2043; contact 2048 falls inside a 2047-2048 gap; frame 2077 is followed by missing detections 2078-2079. Nearby fully visible windows do not contain the hit's motion change. The false proposal at 2060 passes the current angle threshold at 37.3 degrees despite a smooth arc, with a broad player-proximity fallback. Thresholds and predictions were left unchanged. The next detector should represent uncertain contact intervals supported by pose around short gaps, while preserving missing raw shuttle points, and distinguish smooth flight curvature from abrupt contacts.

The four shuttle labels are frames 2003, 2004, 2056, and 2059, each with about 3 px visual uncertainty. They contain no invisible frames and were selected for clarity. Their result checks coordinate alignment and localization on those examples; it cannot estimate whole-video visibility recall, false-positive rate, or robustness to occlusion.

Full reproducible outputs: [singles evaluation JSON](pilot-singles-evaluation.json) and [doubles evaluation JSON](pilot-doubles-evaluation.json). Each records video SHA-256, run IDs, annotation revision, coverage, excluded evidence, tolerances, and matching details. Raw model artifacts remain unchanged when identities are applied.

## Reproduce and extend

With the original registered sources and cached player runs available:

```powershell
# Preview the merge; nothing is saved.
.\.venv\Scripts\python.exe scripts/import_pilot_review.py --accept-inferred-live

# Save append-only revisions, preserving existing edits. Repeating this is a no-op.
.\.venv\Scripts\python.exe scripts/import_pilot_review.py --apply --accept-inferred-live

.\.venv\Scripts\python.exe -m badminton.cli evaluate 970dbd8adfe548d8 --contacts-run 70357b1ea6ca48288dacfea0a02c65ba --shuttle-run ad0696c19b4b4be0beddf592a641cca0 --output .cache/singles-evaluation.json
```

The importer verifies source hashes and refuses conflicts instead of replacing saved labels. Omit `--accept-inferred-live` on a fresh import to retain the manifest's unknown singles scene; its contact metrics will then be null. On an already imported document, use the viewer to change the scene, because the importer deliberately refuses conflicting edits. Run IDs refer to these cached local experiments, so a fresh model run needs its own reviewed mappings.

In the viewer, expand **Assign tracks to players** and **Reviewed clips & accuracy**. Add missed contacts, review scene context, and mark independent shuttle frames, then save and measure. Evaluation never turns predictions into labels automatically. Synthetic browser-test labels remain in the separate port 8001 QA database and are not included here.

## Work that follows from this evidence

1. Diagnose missed contact windows and motion-apex false proposals; improve contact evidence without tuning thresholds to these four examples alone.
2. Label complete rallies with observable serves/endings and adjudicated hitter/family/side labels. Expand shuttle sampling to blurred, occluded, far-court, and invisible cases.
3. Confirm doubles scene context and inspect longer crossings before extending identity ranges. Persistent identity recovery still needs an automatic method and explicit switch evaluation.
4. Evaluate on additional reviewed development rallies, reserving separate original matches for a final test. Only then train the six-family/forehand-backhand classifier and build automatic rally boundaries.
