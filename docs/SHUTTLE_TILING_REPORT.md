# Fixed overlapping-tile shuttle development comparison

Owning task: [issue #299](https://github.com/Ken0u/badminton-match-analyzer/issues/299),
under [localization roadmap #65](https://github.com/Ken0u/badminton-match-analyzer/issues/65).
The experiment is being prepared. No native result or accuracy improvement is
claimed at this checkpoint. The application default remains full-frame 512x288.

The [public protocol](../data/manifests/shuttle_tiling_protocol_v1.json) fixes one
candidate: resize source RGB and the complete-view native median background to
768x432 using the existing adapter, crop four 512x288 tiles at (0,0), (256,0),
(0,144) and (256,144), and max-fuse model heatmaps before the unchanged temporal
ensemble and observed-component selection. The model, threshold 0.5, length-eight
sequence and CUDA float16 execution remain fixed. Cropped context may introduce
false observations or harm localization. No other variant follows from a result.

Both variants retain all 50 original complete target camera/background views and
13,499 native view rows. All 60 familiar development cases remain: 25 localizable,
seven confirmed negatives and 28 unknown. Unknowns, unavailable outputs, original
uncertainty and overlapping source/difficulty/selection groups remain explicit.
These source labels are agent assessments, not expert truth or an unseen test.

The default control must reproduce original physical observations before any
candidate execution or scoring. The frozen projection excludes exactly four new
dependency metadata fields from historical row comparison; it preserves every
other point/component/frame/PTS/camera field with confidence-only absolute
tolerance 0.00001. Current dependency provenance is separately validated by
replaying the actual selector from original observed components and scene resets.
The older resolution protocol retains its original strict comparison.

The runner is `scripts/compare_shuttle_resolution.py`, supplied with the new
protocol. It freezes input/model/code/runtime/view hashes, writes exclusive
ignored artifacts, uses the real shared Store admission, and refuses candidate
execution when the control is incompatible. Actual tile/model-call provenance
is checked separately from canvas dimensions. Process lifetimes, Store states
and artifacts must be verified before any resume; timeout never establishes exit.

No training, image transfer, source acquisition, weight installation, model
promotion or product option is included. Raw media, labels, predictions and
weights remain ignored. All four eligibility flags remain false, complete-rally
references remain 0/2 and #65 stays open. Software checks do not establish correct
automatic annotation throughout singles or doubles matches.

Local preparation validation: **4,605 full Python tests pass**,
with four optional skips; 171 focused tests also pass. Required Ruff, format,
pip, repository and diff checks pass. Independent observation confirms
1998 recorded process lifetimes are terminal. The generated null-layout
failure and correction remain preserved; no model was needed for that proof.
Initial import/unused-variable and regex-style lint findings were corrected.
Native results, exact PR/main CI and independent public delivery remain pending.
