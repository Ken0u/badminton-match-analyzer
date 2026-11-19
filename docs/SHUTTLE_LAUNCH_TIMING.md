# Shuttle launch timing (local revamp)

The 3D fitter used to start the drag trajectory on the frame of the largest image turn. A frame can contain the end of the incoming flight rather than the beginning of the outgoing one. We now look for the intersection in time of a short incoming image track and a decelerating outgoing track. Both sides of the sampled turn are considered. The fit uses actual detection timestamps; it never inserts a detection at the inferred contact. A gap, camera change, ambiguous intersection or weak speed evidence can prevent a launch reading. The raw model estimate is diagnostic, not necessarily reportable. No minimum speed by stroke or player is used. Speed at +100 ms is a different quantity. In Watch, the number now appears immediately instead of counting up from zero over 420 ms.

## Controlled comparison

Run `python tests/test_shuttle_speed_clock.py` with the project environment (`backend` on PYTHONPATH). The 18-case check varies launch direction, speed, drag, 25/60 fps, subframe phase and timestamp spacing. Detections include seeded image noise. This isolates timing with known geometry; it does not test tracking on real matches. Baseline uses the integer-turn clock and the former early-speed rule on the same inputs. No shots are dropped from the overall denominator.

| Metric | Integer frame | Subframe |
| --- | ---: | ---: |
| Raw fitted speed: mean absolute error, all 18 (km/h) | 65.71 | 25.17 |
| Raw fitted speed: signed mean error (km/h) | -65.69 | -13.85 |
| Launch estimate reportable | 2/18 | 5/18 |
| Mean absolute error on reportable shots (different subsets, km/h) | 1.95 | 4.83 |
| Mean absolute error on the **same two** reportable shots (km/h) | 1.95 | 4.47 |

This is evidence of less systematic underestimation in the raw fit and increased coverage here, not improved precision on every displayed speed.

## External and local checks

Eric Collet's *Shuttlecock velocity decay after smash and slice shots in badminton* (Zenodo record 18142286, Figure3.txt, SHA-256 `dc3283ca127dcb7126c354b5f0954a069c98aedc1c1c5b649c10c36b8ed6aee9`) supplies measured horizontal distance, altitude and velocity after a single smash. Its first nonempty speed is 379 km/h, not a synchronized radar measurement at contact. For a partial reality check we projected the measured outgoing positions into the synthetic broadcast camera from `test_shuttle_flight.py` as `(3, 11 - distance, altitude)`, sampled the original time column by linear interpolation through 0.30 s and placed impact midway between frames 6 and 7. The approach was simulated with velocity `(-5, 8, -2)` m/s and hitter feet at `(3, 11)`; neither is measured in this source. At 60 fps the raw fit changed from 194 to 385 km/h. At 30 fps both gave 104 km/h. Neither new result passed the launch display gate. These are two samplings of one trajectory, not two independent trials or an end-to-end video validation.

A read-only replay of the first ten continuing shot pairs from each of the two development clips listed in `CONTINUING_FLIGHT_NET_QUALITY.md` gave **0/20 reportable launch estimates**. Of the doubles pairs, six had a supported later speed, three had no reportable speed, and one had no fit. Of the singles pairs, eight had a supported later speed and two had no reportable speed. These shots have no independent speed labels; this measures availability only. Neither prior analyses nor reviewed labels were changed. New estimates require recomputing outcomes, not just re-exporting old results. Match accuracy needs independent, synchronized per-shot reference measurements.

## What was adopted

Adopted: the sub-frame contact clock in the fit, so every newly fitted `initial_speed_kmh` uses it. Not adopted as a display rule: the strict "reportable launch" gate. With it, the app and statistics would have shown a launch speed for almost no shot (0 of 20 above) and fallen back to the speed at +0.1 s, which drag caps near 120 km/h, so smashes would look slow. Displayed and aggregated launch speeds therefore stay the fitted `initial_speed_kmh` of `good` fits, and `speed_bound` fits stay "too fast to measure". `launch_supported`, `early_speed_kmh` and `settled_supported` are kept in the document as diagnostics only. `launch_bound` (the fit reached the 450 km/h bound before the receiver prior pulled it down) is folded into `speed_bound`. Effect on the two supplied videos: `docs/CLIP_STATS.md`, "On the supplied videos".
