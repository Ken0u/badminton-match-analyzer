# Gap-aware contact proposals

Prepared October 17, 2026. The second contact detector addresses two observed failures: requiring seven consecutive shuttle observations misses hits during occlusion, and smooth flight curvature can look like an impact. This remains an interpretable proposal baseline, not a trained stroke/rally classifier.

## What changed

Observed contacts compare a broken-line motion fit with a smooth quadratic fit to distinguish an abrupt change from a smooth apex. Short missing spans can produce a **possible-contact interval** when trajectory segments meet plausibly and a nearby tracked player's confident wrist shows movement. Long gaps, implausible jumps/speeds, inconsistent timestamps, explicit camera-cut flags, and insufficient pose evidence are rejected. Missing shuttle coordinates are never filled or repaired.

Each candidate records its evidence and inclusive `start_frame`/`end_frame` bounds. For an uncertain interval, `frame`/`time_s` are a navigation location, not an observed racket contact. The viewer opens the full possible range and keeps the interval when a reviewer adds it. An event's `contact_start_frame`/`contact_end_frame` are editable, validated, and preserved in JSON/CSV and annotation history. Use **Use exact contact frame**, then update/save, only after identifying the contact frame from source evidence.

The method honors supplied cut metadata; it does not automatically detect camera cuts or replays. Player hints still require confirmation. Ranking scores remain heuristic, not probabilities.

## Unchanged development pilot

The existing four contact labels in source frames 2000-2100 were evaluated without changing annotations or perception outputs. This small, assistant-reviewed pilot is development evidence and still needs human adjudication.

| Evidence | Previous detector | Updated detector |
| --- | --- | --- |
| Clearly matched observed contact at 2007 | Found | Found |
| Possible interval containing contact 2077 | Missed | Frames 2076-2080, navigation frame 2078 |
| Contacts 2039 and 2048 | Missed | Still missed |
| False apex suggestion at 2060 | Proposed | Rejected |
| Strict representative-time counts at 120 ms | 1 match, 1 false, 3 misses | 2 matches, 0 false, 2 misses |

The representative-time F1 moves from 33.3% to 66.7%, also at a 40 ms tolerance. **That is a proposal-navigation metric, not proof of two precisely observed hits.** One of the two new matches is an interval whose navigation frame is 40 ms after the reviewed point. Separate one-to-one interval containment covers two of four reviewed contact points. Across the full unreviewed 250-frame tracking window there are five proposals; three lie outside the reviewed interval and are excluded from scoring.

The remaining misses have inadequate evidence under the new rule. Around 2039 the visible pre/post trajectory segments do not meet plausibly within the gap. Around 2048 the sparse observations do not distinguish an abrupt contact from smooth flight. Thresholds were not loosened solely to force agreement with these four examples. The next detector work needs more independently reviewed trajectories and stronger racket/pose evidence, rather than treating every dropout as a hit.

The evaluator labels representative-time semantics explicitly and reports interval containment separately, without calling it exact timing accuracy. A reviewed event that still has a nonzero contact interval excludes its entire otherwise-complete review window from strict scores until timing is adjudicated. This prevents accepted uncertain suggestions from becoming false precision in later evaluation.

Full source/run/revision provenance and results are in [contact-v2-evaluation.json](contact-v2-evaluation.json). Reproduce with the cached local IDs:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_contacts.py 970dbd8adfe548d8 --shuttle-run ad0696c19b4b4be0beddf592a641cca0 --players-run b8bdae17e8374a20bbf16f554c551f19 --baseline-run 70357b1ea6ca48288dacfea0a02c65ba --output .cache/contact-benchmark.json
```

Synthetic regression cases cover abrupt turns, subframe timing, smooth arcs, short/long gaps, moving/static/distant wrists, tracker association, cuts, source-time discontinuities, raw-data immutability, interval persistence/export, and honest evaluation coverage. Browser checks exercise proposal review, invalid timing edits, saved uncertainty, adjudication gating, and clearing an interval in the isolated QA catalog.
