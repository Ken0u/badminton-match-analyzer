# Recognition priority for reviewed contact uncertainty

Task [#393](https://github.com/Ken0u/badminton-match-analyzer/issues/393) extends
the existing priority of reviewed shot contacts to their complete possible
contact intervals. The selector previously compared a proposal only with each
reviewed shot's navigation frame.

For example, a saved shot at frame 30 can have inclusive possible contact bounds
`[28,34]`. Proposals `[26,28]` and `[34,36]` overlap that saved uncertainty even
though neither contains frame 30. Both previously produced additional recognition
targets. The selector now gives the saved shot priority at either shared endpoint.
An adjacent disjoint proposal `[35,36]` still receives its original target and ID.

Reviewed and corrected shots retain their original target, player, event ID and
uncertainty. A legacy shot or proposal without an interval is a single-frame
contact. Priority is applied before requested navigation-frame range filtering,
so a saved shot outside a processing window can still reserve overlapping
possible contact times inside it. All reviewed shots remain separate, including
two saved shots with overlapping uncertainty.

This chooses which competing hypotheses to classify. Interval overlap does not
prove two physical contacts are identical or resolve their exact timing. Original
proposal artifacts and saved annotations remain intact; no reference is removed
from evaluation. `include_reviewed=False`, predicted labels, serves, rally endings,
scene/calibration guards, target ordering and disjoint target IDs retain their
existing behavior. No classifier, feature, threshold or model weight changes.

## Generated verification

On unchanged production source, **40 regressions fail and 13 controls pass**.
The failing cases cover either endpoint, nested intervals, point proposals,
reviewed/corrected shots, singles/doubles, an outside navigation frame, separate
saved shots and the actual saved API/CLI paths. After the minimal selector repair,
all **53 new checks and 141 focused checks pass**.

The API and CLI checks use content-addressed generated source bytes, native-frame
timestamp metadata, validated saved annotations, actual Store admission and
separate recognition output artifacts. Only neural execution is replaced with
an explicit abstaining fixture. They verify the chosen event/proposal identities,
saved output, unchanged source bytes, timestamps, original run files and saved
annotation revisions. They do not decode original match videos, load a neural
checkpoint or measure badminton accuracy.

The full Windows Python 3.10 suite passes **6,179 tests**, with
4 optional GPU checks skipped. Executable and test bytes match the
completed run. Ruff, formatting, dependency health, tracked UTF-8/LF, strict JSON,
local documentation links and whitespace checks pass. Clean source/wheel and
installed HTTP checks verify 113 package files,
62 public manifests, 5 frontend assets,
3 SPA routes and authentication. These are software checks.

A separate generated orchestration receipt uses 100 encoded 640x360 frames at
25 fps, explicit PTS and the same saved Store/API/CLI checks. The source digest
is `2f0eac461a38a0c1ebf06aa5642df135d246a6c554f11c0405d0e92c2a6c1b44`. Both paths preserve original source,
timestamp, proposal and saved-annotation bytes and produce only the reviewed
shot plus the disjoint proposal. The actual unchanged pinned BST checkpoint
digest `5291095b880088ebb9aa5ec8a868ba1e0ced0cd57285b508feb495d94582cbe0` is verified without loading
or executing it. No original match is decoded and no neural inference runs;
this is target-selection and artifact-preservation evidence, not accuracy.

The first full-suite launch stopped during collection because the workstation's
editable installation resolved the old checkout. Its log is preserved. The
successful isolated run explicitly pins this worktree's backend import path;
no production code change or test weakening was used to resolve that launch.
Exact-head CI, controller integration, merged-main checks and complete public
delivery remain separate requirements recorded on the owning issue.

The completed [static/temporal pose comparison](AICUP_POSE_LEARNING_REPORT.md)
remains negative for advancement, with neither model installed. This repair
supplies no new source assessment, independent reference or model improvement.
Complete accepted rally references remain **0/2**, and automatic full-match
annotation accuracy remains unproven.
