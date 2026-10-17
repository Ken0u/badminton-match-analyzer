# Annotation guide, version 1

Target families: **clear, lift, net, drop, smash, drive**, each with a separate forehand/backhand label. Other visible actions use `other`; unresolvable actions use `unknown`. Half smash is outside the target taxonomy.

## Source time and event boundaries

Use the exact source-frame viewer, not a rounded playback timestamp. Frame numbers start at zero. A shot event belongs on the racket–shuttle contact frame; at 25 fps, use the nearest observable frame and explain uncertainty in notes. The application computes seconds from the source presentation timestamp.

A `serve` event is the opening contact and starts a rally. It has a hitter and stroke side, and no shot-family value. Do not add a second shot event for the same opening contact. Add a `rally_end` at the observable terminal moment, such as ground contact or an unreturned net fault. Do not use the final racket contact as the rally ending.

Keep the same rally ID for its serve, subsequent shots, and ending. A cut-off rally may have no serve or no ending. Do not fabricate missing events. When an end is occluded, put the best observed frame in the event and describe the uncertainty in notes; structured uncertainty intervals are a later extension.

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

Save annotations, then choose **Measure saved labels**. Default contact matching is one-to-one within 120 ms, with a 40 ms comparison in the downloaded report. Shuttle localization uses 0.5% of the source-frame diagonal (about 7.34 px for these samples). A wrong localization counts as both a false detection and a miss. Four easy positive frames cannot establish general shuttle accuracy. The current assistant-reviewed pilot needs knowledgeable human adjudication before use as a trusted benchmark or training set.
