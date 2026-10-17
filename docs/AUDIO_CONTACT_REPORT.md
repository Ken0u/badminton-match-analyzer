# Optional audio support for contact review

Prepared October 17, 2026. This experimental, default-off option supplements
visual contact proposals when the shuttle disappears near a moving wrist.
It does not establish exact contact times, serves, rally ends, or shot labels.

## Behavior

Select **Use audio support**, then **Suggest contacts**, after player and shuttle
tracking cover the same window. The API accepts `include_audio: true` on the
existing contacts request. Missing or undecodable audio leaves visual proposals
usable; the UI reports missing/unavailable audio explicitly. Silence adds no cues.

The decoder validates the original source hash and uses audio presentation
timestamps relative to the imported video's origin. It resamples to 24 kHz mono
without assuming that audio starts at the first video frame. Missing PTS,
backward timestamps, and discontinuities split analysis spans rather than
concatenating them into synthetic sound events.

Positive spectral flux above 2 kHz supplies acoustic navigation cues with a
fixed median-plus-six-MAD threshold. A new proposal additionally requires a nearby
raw shuttle observation, a shuttle gap, and a confident moving wrist. Fully
observed flight cannot become a new hit from audio alone. Marked cuts,
replays, frame gaps, and timestamp gaps reject the context. Both perception runs'
cut metadata are honored. No repaired shuttle coordinates are used.

The review interval brackets +/-120 ms using actual source timestamps. This is
an engineering review range, not a calibrated confidence interval: AV offset and
sound propagation delay remain unmeasured. Sounds associated with the same
shuttle gap do not create duplicate events. Conflicting evidence is retained
without replacing a visual proposal's timing, score, or hitter. All scores remain
heuristic rankings. Inference never saves annotations.

## Unchanged development pilot

The same source bytes, perception runs, and revision-2 labels were used. See
[the machine report](audio-contact-evaluation.json) for hashes, run IDs,
all cues/proposals, excluded footage, and one-to-one matching.

| Singles frames 2000–2100; four reviewed contacts | Visual v2 | Audio enabled |
| --- | --- | --- |
| Navigation-time matches within 120 ms | 2 | 4 |
| Unmatched suggestions in this reviewed window | 0 | 0 |
| Reviewed points contained in proposal intervals | 2 | 4 |
| Navigation-time F1 within 40 ms | 0.667 | 0.750 |
| Proposals over the mostly unreviewed 250-frame run | 5 | 8 |

New intervals 2036–2043 and 2046–2053 contain previously missed labels at
2039 and 2048. Their navigation frames are 2039 and 2050. **Four contained points
in a four-contact development example do not demonstrate perfect accuracy.**
Timing remains uncertain, labels need human adjudication, and proposals outside
the review window cannot be called correct or incorrect.

The doubles run increases from 7 to 12 proposals. Its review window has unknown
scene status, so strict metrics remain unavailable. An extra suggestion near 638
does not correspond to a current contact label. Keep the option default-off and
review false positives before wider adoption. Crowd sounds, shoe squeaks, and
other courts remain likely confounders.

Reproduce without modifying annotations:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_audio_contacts.py 970dbd8adfe548d8 --shuttle-run ad0696c19b4b4be0beddf592a641cca0 --players-run b8bdae17e8374a20bbf16f554c551f19 --output .cache/audio-singles-benchmark.json
```

Generated-media and synthetic regressions cover video-origin offsets, real PCM
resampling, silent video, timestamp discontinuities/missing PTS, source changes,
absent/unusable audio, invalid visual context, conflicting hitter hints,
duplicate sounds, opt-in API behavior, and annotation immutability. Browser QA
exercises the checkbox/request and interval review. Broader independent live
footage and AV synchronization checks are still needed.
