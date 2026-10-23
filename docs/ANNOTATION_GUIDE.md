# Annotation guide, version 1

For the source-only complete-rally pilot, follow the prospective
[rally protocol](../data/manifests/rally_reference_protocol_v1.json).
Five-second overview frames propose the earliest warranted provisional slot;
they cannot certify its completeness. Review every native frame of that slot,
including four-second context on each side, in two independent source streams
with separate fresh source adjudication. Retain the original streams and their
own continuity notes across overlapping chunks. Record source actors independently
of tracker IDs, unknown identity links, camera transitions, replay/unknown context,
unresolved contacts and start/end censoring. Use inclusive native contact and
terminal uncertainty intervals separately. Stopped play alone does not establish
the exact terminal moment. A failed slot stays failed; do not select an easier
replacement. Unknown family/side stays unknown even when contact enumeration is
complete. Agent agreement does not establish expert gold truth or eligibility
for training, independent testing, deployment or redistribution.

Target families: **clear, lift, net, drop, smash, drive**, each with a separate forehand/backhand label. Other visible actions use `other`; unresolvable actions use `unknown`. Half smash is outside the target taxonomy.

## Source time and event boundaries

Use the exact source-frame viewer, not a rounded playback timestamp. Frame numbers start at zero. A shot event belongs on the racket–shuttle contact frame; at 25 fps, use the nearest observable frame and explain uncertainty in notes. The application computes seconds from the source presentation timestamp.

A `serve` event is the opening contact and starts a rally. It has a hitter and stroke side, and no shot-family value. Do not add a second shot event for the same opening contact. Add a `rally_end` at the observable terminal moment, such as ground contact or an unreturned net fault. Do not use the final racket contact as the rally ending.

Keep the same rally ID for its serve, subsequent shots, and ending. A cut-off rally may have no serve or no ending. Do not fabricate missing events. When an end is occluded, use **Rally end timing uncertainty** with inclusive earliest/latest source frames containing the navigation frame. These persist as `terminal_start_frame` and `terminal_end_frame`, separately from racket-contact intervals. The navigation frame is not an exact terminal timestamp. Clear the bounds with **Use exact rally-end frame** only after adjudicating the terminal moment. Include the visual evidence and uncertainty in notes.

For an occluded **contact**, use the editor's **Contact timing uncertainty** bounds. Both are inclusive, and the event's navigation frame must lie within them. Suggestions supported across a short gap populate those bounds automatically. Inspect the entire interval, preserve uncertainty when the actual contact is hidden, and clear it with **Use exact contact frame** only once the source evidence supports a point annotation. Changing event kind clears the editor's timing fields so a contact interval cannot silently become terminal timing; the change is saved only after updating and saving the event.

## Stroke families

| Family | Working convention |
| --- | --- |
| Clear | Usually overhead contact with an upward/deep flight toward the rear court. |
| Lift | Low/underhand contact sending the shuttle up toward the rear court. |
| Net | A forecourt touch intended to travel close over the net and remain short. |
| Drop | Usually an overhead stroke from farther back, directed short with reduced pace. |
| Smash | An attacking overhead stroke with a downward outgoing trajectory. |
| Drive | A fast and comparatively flat exchange. |

Use contact mechanics and outgoing flight together. A shot retains its family when intercepted or when it lands out; do not infer the family solely from where the shuttle finally lands. Defensive blocks, pushes, and net kills need explicit future mapping decisions; use `other` rather than squeezing them into a target label.

Forehand/backhand describes the stroke mechanics relative to the player's handedness, including body rotation. Screen-left/screen-right is not the definition. An around-the-head forehand remains a forehand. Leave side or handedness unknown when the evidence is inadequate.

## Players and court

Singles has two persistent players, A and B, one per team. Doubles has four persistent players, A/B on T1 and C/D on T2 by default. Names, teams, and handedness are editable. Player IDs must persist when ends change. A tracker ID is a temporary model association. In **Assign tracks to players**, map it to a player only for the interval you inspected. Mappings belong to one run and do not propagate into other runs, across unreviewed crossings, or across end changes. Two simultaneous tracks cannot map to the same player in one run. Already saved event identities require their own correction if a mapping changes.

Select court corners in perimeter order: far left, far right, near right, near left. The calibration range includes its start frame and excludes its end frame. Apply it only to the camera segment where that geometry is valid. Moving cameras and cuts need new ranges. Use the outer court corners for the target playing area; singles side boundaries can be derived later.

## Edited highlights

Both supplied samples contain close-ups, alternative camera angles, and replay sequences. Treat them as edited highlights, not continuous full-match recordings. The first tracking experiments use short manually inspected full-court windows. Do not count a replay as a new live rally. Automatic replay classification and continuous full-video rally detection are not implemented in this first increment.

## Review quality

Review contact times before family labels. Inspect uncertain strokes at slow speed and frame by frame. Record visibility, motion blur, and uncertainty in notes. Save changes before exporting. Another window's conflicting revision is rejected so it cannot erase reviewed work.

Before labeling a large dataset, have a knowledgeable second annotator review a subset. Resolve systematic disagreements and add reference clips to this guide. Never reuse final-test examples for tuning models or labeling conventions.

## Contact suggestions

Track the shuttle in a continuous full-court window, then request contact suggestions. These combine trajectory changes with nearby player boxes/wrists. A suggested track ID is not a confirmed player identity. Ranking scores are heuristic, and the suggestions can include false hits or miss real hits.

Selecting a suggestion prepares a shot event with unknown hitter/family/side. Inspect adjacent frames, set the correct rally and labels, then add and save it. The original run and candidate ID remain attached to the event. Suggestions never replace reviewed annotations automatically. Do not treat a trajectory apex, bounce, occlusion, or camera cut as a racket contact without visual evidence.

If its tracker has a reviewed mapping at that frame, a suggestion preselects that player as a hint. Verify it before adding the event. Shot family and side remain unknown until reviewed.

## Exhaustive review and evaluation

Use **Reviewed clips & accuracy** to define a nonoverlapping source-frame interval. Its end frame is excluded. Check **Every contact in this clip is labeled** only after inspecting every frame, including intervals without proposals. A partial rally can still have exhaustive contact labels inside its reviewed interval; it does not need an invented serve or ending. Incomplete clips are useful saved work but cannot establish contact recall.

Set footage to live, replay, or unconfirmed based on the source context. Record the evidence if inferred. Contact metrics include only complete live clips fully covered by the evaluated run. Replays and unconfirmed scenes are excluded, and the report lists why. A null metric means insufficient eligible evidence, not zero accuracy.

For shuttle localization, mark the center of the observed shuttle or blur streak on the exact source image. Marking a visible shuttle hides the model overlay. Use **Shuttle not visible** only after inspecting the image; a missing model detection is insufficient evidence. Leave an ambiguous frame unlabeled. Include easy and difficult visible examples plus invisible frames in the eventual evaluation sample, selected independently of predictions.

A complete clip containing a reviewed contact interval is excluded from strict timing metrics until the contact timing is adjudicated. Proposal navigation-time scores and one-to-one interval containment are separate report fields; an interval containing a true hit is useful for review but is not evidence of an exactly timed detection.

Save annotations, then choose **Measure saved labels**. Default contact matching is one-to-one within 120 ms, with a 40 ms comparison in the downloaded report. Shuttle localization uses 0.5% of the source-frame diagonal (about 7.34 px for these samples). A wrong localization counts as both a false detection and a miss. Four easy positive frames cannot establish general shuttle accuracy. The current assistant-reviewed pilot needs knowledgeable human adjudication before use as a trusted benchmark or training set.

With a recognition run loaded, the same action measures independently entered
family/side labels. Events carrying classification provenance, including corrected
model drafts, are excluded from these accuracy metrics. Build evaluation labels
without consulting the classifier; keep model-assisted review work for a separate
annotation workflow. Unknown truth remains excluded, whereas missing predictions
and abstentions count as unanswered. A full six-family macro F1 is available only
when every requested family has labeled support. Complete-event scoring also
requires known hitter and stroke side, and does not accept unresolved prediction
timing as an exact contact. These measurements remain conditional on input
contacts and reviewed identity mappings, as recorded in the report.

Public labels in `data/datasets/` are separate source references. Their frame
numbers must be aligned to the actual downloaded video's timestamps and frame
origin before use in this editor or in model training. A terminal-stroke marker
does not establish the moment the rally ended.

For the separately authorized source-only follow-up #208, retain the original
failed first-300-second pilot and protocol v1 unchanged. Protocol v2 extends
the deterministic five-second native-PTS screening grid through 900 seconds
on the same originals. This is development informed by that pilot, not an
independent test. Sparse screening can propose bounds but cannot certify a rally.

Two actual independent dense streams must inspect every selected native frame.
Separately adjudicate all disagreements and unresolved contact, identity,
scene, boundary and chunk-join regions from original images. Resolve entire
inclusive contact intervals, not fragments. Consistent original regions do not
require a third exhaustive stream. Preserve both originals and fresh targeted
resolutions, including unknowns. Conflicting overlap states and duplicate events
within a chunk cannot disappear through set union or event deduplication.
Agent agreement is not expert gold truth; eligibility flags remain false.

### Reusing source-only preparation and validation

Use a current matching task grant, committed protocol and consumer context,
and a public prospective timestamp before preparing images. Archived #62/#208
contexts preserve evidence; they do not authorize another run or more time.
Create the private context with `consumer_context(checkout, protocol_path,
input_root, granted_at)` from `badminton.rally_source_reference`, using the
original committed grant time, and check it with `verify_context`. Never reset
the deadline when refreshing a context. Publish its SHA256 on the owning issue
and retain the actual GitHub comment URL/creation time as the prospective
timestamp; the private context itself is not a public artifact.

Pin the original shared root and data directory before application imports.
Use the fixed `.cache/rally<TASK>-source-only-v1/` lineage and a new exclusive
stage directory. The preparation entry point clears credentials and uses the
real existing Store:

```text
python scripts/prepare_rally_references.py --root SHARED_ROOT --output EXCLUSIVE_STAGE_DIRECTORY --context FROZEN_CONTEXT_JSON --context-sha256 CONTEXT_SHA256 --timestamp PUBLIC_TIMESTAMP_JSON --stage overview
```

After complete independent screening and fresh blind source adjudication, retain
and seal the exact earliest-candidate decision, including unresolved source slots.
A dense invocation uses `--stage dense --selection SEALED_SELECTION_JSON`; its
prospective timestamp must bind both the exact selection and consumer context.
Observe the actual Store owner and launcher ancestry while live, then independently
verify their original lifetimes are absent and the Store/terminal/artifact seals
match before consuming any packet. Outputs are exclusive and stay ignored.

Use `plan_chunks(packet, dense=True, overlap=2)` and
`payload_cost(chunks, streams=2, prior_bytes=ALL_PREVIOUS_IMAGE_BYTES)` from
`badminton.rally_source_reference` before dense assessment. Count every source,
overlap, failure and repeat; separately account for actual targeted adjudication.
The output budget also includes prior artifacts, worktrees and verification files.

Run every assessment in a genuinely fresh source-only session, preserving actual
invocation/thread/process/image/output receipts. Validate each original document
with `validate_assessment` against its native packet, assigned chunk, actual
receipt and its own previous-segment seal. A hand-written receipt or copied
assessment cannot stand in for another independent session. Supply no other
stream's labels, model outputs, predictions or application annotations.

Once both exhaustive dense originals are sealed and validated, call
`adjudication_targets` on their document/receipt pairs to derive disputed native
regions. Inspect every required region and whole intersecting contact interval
in separate fresh source-only sessions; preserve unresolved cases and original
documents. Validate those targeted chunks too, then use
`targeted_reference_status` with the full selected native membership and frozen
bounds. Its result is a calculation over original evidence, not a new assessor
or an expert gold label. Keep both source slots in the report, including slots
that could not be prepared or completed. No positive completeness or eligibility
flag may be inferred from software checks, dispatch acknowledgements or sparse
screening.
