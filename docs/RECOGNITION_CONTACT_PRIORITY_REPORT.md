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

Full regression, required tooling checks, clean packaging/installed HTTP checks,
exact-head CI, controller integration and public delivery remain required;
the owning issue records each result as it completes. A source/model/code-bound orchestration receipt must
state the generated-only evidence and absence of neural inference explicitly.

The completed [static/temporal pose comparison](AICUP_POSE_LEARNING_REPORT.md)
remains negative for advancement, with neither model installed. This repair
supplies no new source assessment, independent reference or model improvement.
Complete accepted rally references remain **0/2**, and automatic full-match
annotation accuracy remains unproven.
