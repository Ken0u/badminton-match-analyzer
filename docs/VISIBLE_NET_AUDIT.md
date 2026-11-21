# Visible net check: local doubles broadcast

Question: is the saved camera putting the net high enough in the picture to
explain rally 25, shot 7? This is a diagnostic on one broadcast, not a
calibration benchmark. No new camera, fitted flight or label was installed.

Run `python scripts/audit_visible_net.py` in the project environment with the
original doubles source and processed analysis present. It validates source
identity, timestamps and display dimensions through `iter_frames` and writes
raw PNGs, overlays and enlarged paired strips to `.cache/visible-net/`.
Magenta is the projected nominal tape top (parabolic sag approximation);
orange shows the posts. Cyan marks the fitted crossing, not an observed bird.

The table is observed minus projected vertical image coordinate in native
pixels (positive = the real tape appears lower). The upper-edge estimate uses
the strongest rising red-channel edge over green court in a fixed raw-image
window at each of three columns. Allow roughly a pixel for edge ambiguity;
the decimal places describe geometry, not subpixel measurement accuracy.

| Native frames | View start | x=480 | x=765 | x=875 |
|---|---:|---:|---:|---:|
| 10405, 10459, 10489 | 10337 | -0.2 | +0.6 | +0.8 |
| 2494, 2551 | 2445 | +0.6 | +0.2 | +0.1 |
| 6122 | 6064 | -0.6 | +0.1 | +0.3 |
| 1874 | 1851 | +0.7 | +1.4 | +1.6 |

The posts bracket the visible net; the bases are wide fixtures, so they were
not used for point measurements. Near x=673 a player's foot complicates the
crossing frame; in the same view the unobstructed tape rises in brightness
around rows 280-281. The fitted crossing projects to (672.6, 285.9), versus
(672.6, 280.0) at the fitter's 1.53 m reference. These are projections at the
interpolated crossing time (418.3506 s), shown on the nearest frame (418.36 s).
The tape agrees much better than the crossing does. A global camera shift is
not supported. This does not independently measure shuttle depth or contact
time. Inspect native shuttle detections and test shot-specific depth/timing
fits before changing production behaviour.
