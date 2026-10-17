# Direct source-video recognition probe

Prepared October 17, 2026. The published-feature benchmark has now been followed
by an actual video -> YOLO pose -> TrackNet -> contact/recognition probe on a
6.52-second, 163-frame ShuttleSet source excerpt. It exposes missing evidence;
it does not certify source labels or direct-video accuracy.

## Source and alignment

The excerpt comes from [ShuttleSet match 1's source](https://www.youtube.com/watch?v=O669aZhH0LI),
with decoded parent presentation times 458.00–464.48 seconds at 25 fps. Its SHA-256
is `1ae761b4f2f46b0168ff0193a9ac79d2a98f6564a5d64e18ce2e9243285c3a79`.
The local derivation sidecar preserves each frame's parent PTS/time. The tracked
[alignment manifest](../data/manifests/source_alignment_pilot.json) still records
**zero verified contacts** and `needs_contact_adjudication`.

Published source frames 11496 and 11582 locate diagnostic windows, provisionally
at local frames 46 and 132. Visual inspection did not establish their exact
contact semantics: the serve reference appears earlier than the action, while
the return reference includes follow-through. Cached source MMPose sequences
resemble the corresponding YOLO pose windows near these locations, but pose
similarity and FPS agreement cannot certify contact times. No constant timing
correction was adopted.

The clip remains in a separate research catalog. The original two videos'
reviewed labels and the app catalog were not expanded or overwritten. A later
request for another excerpt encountered YouTube's sign-in gate; no authentication
bypass or cookie extraction was attempted.

## Actual CUDA results

Published court corners supplied conditional calibration; they have not been
independently measured here. All 163 frames were processed on the laptop GPU.

| Stage | Observation |
| --- | --- |
| YOLO11n pose, 1280 px | Two retained players on every frame; 6.532 s, 101.9 MB peak GPU allocation |
| TrackNetV3 | 28 visible outputs, no repaired points; 12.421 s, 430.3 MB peak allocation |
| Visual contact v2 | No proposals |
| Reference 46 | Abstains: 25/25 two-player pose frames, 0/25 shuttle observations |
| Reference 132 | 25/25 two-player pose frames, 17/25 shuttle observations; abstains at fixed 0.5 family threshold |

At reference 132, family mass is mixed: `other` 0.466, `clear` 0.243, `lift` 0.133.
Side remains unknown. These are uncalibrated outputs at an unadjudicated
timestamp, not independently scored errors. Preparation and a held shuttle also
make visible-output counts unsuitable as localization recall. Persistent player
identity was not scored.

The smooth flight apex does not create a motion-change suggestion. Missing
incoming/outgoing observations prevent the current rule from recovering the
opening exchange. **Published MMPose feature results do not establish recognition
performance on YOLO inputs.** Thresholds were not lowered to force a label.

Raw predictions, input run IDs, checkpoint hashes, and perception summaries are
in [the machine probe](direct-video-recognition-probe.json). With the local
source/catalog and perception artifacts present, reproduce using:

```powershell
.\.venv\Scripts\python.exe scripts/probe_recognition.py 1ae761b4f2f46b01 --data data/datasets/shuttleset/direct-video-v1 --players-run 2c03946740f443f4b237794c04a380a5 --shuttle-run f8de56b4b83f4fae8cbc56310fa4c540 --frames 46 132 --output .cache/direct-video-recognition-probe.json
```

The probe shares app processing admission, validates input lineage/source bytes,
and never creates reviewed events. Its output explicitly has no strict accuracy.

## Next evidence to collect

Adjudicate source contact intervals before importing expert labels as exact local
events. Expand complete live development rallies with missed hits and difficult
visibility, then compare fixed recognition at adjudicated contacts using both
published MMPose and actual YOLO features. Use training and validation matches for
domain adaptation and keep final matches frozen. Optional
[audio support](AUDIO_CONTACT_REPORT.md) helps navigate missed hits in the
original samples, but this excerpt has no audio track and still needs stronger
visual contact/serve detection.
