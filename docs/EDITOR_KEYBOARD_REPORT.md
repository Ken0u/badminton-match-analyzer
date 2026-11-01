# Editor keyboard ownership

Owning task: [#362](https://github.com/Ken0u/badminton-match-analyzer/issues/362).

## Reproduced behavior

The global editor keyboard handler intercepted Space while Save annotations or
Select 4 corners had focus. A mounted React editor using generated media shows
zero native button clicks and playback starting instead. Save's persisted
revision did not advance; Calibrate did not enter corner-selection mode. Enter
activated each button normally. This confirms the earlier isolated handler probe
in the actual editor rather than relying on that probe alone.

The existing transport contract is deliberate: Space on Next frame toggles
playback, while Enter steps a frame. Arrow keys, background event-marking keys
and Ctrl/Cmd-S also remain review shortcuts.

## Change

The global handler now defers to native interactive controls and their nested
targets. Buttons, inputs, selects, textareas, links, summaries, editable content
and common interactive ARIA roles retain their keyboard events. An already
prevented event stays consumed by its existing owner.

The three existing transport buttons (Previous frame, Play and Next frame) keep
their shortcut behavior only inside the transport area. Other buttons keep native
Space/Enter activation. The handler does not synthesize clicks or save on focus.
Ctrl/Cmd-S remains available through the existing save path, and existing export
and mini-court event ownership remains intact. The effect's subscription and
cleanup lifecycle are unchanged.

## Verification and limits

The mounted browser regression independently records native click counts,
playback state and persisted revision changes for Enter/Space on Save and
Calibrate. It fails on the unchanged handler for both Space cases. Additional
controls cover native event-mark buttons, non-transport arrow/number ownership,
nested event targets, background review shortcuts, repeated Space keydown and
video changes without duplicate saves. Existing input, transport, Ctrl/Cmd-S,
export and mini-court checks remain required. A unit control limits the transport
exception to the three named buttons, excluding form controls and unrelated IDs.

The first generated fixture reused a frame for two shots and correctly failed
save validation; it was corrected to choose unused frames. An initial background
shortcut assertion read React state before its scheduled update; the test now
waits for the intended state and focus update. Those failed receipts remain
separate from the actual before-regression and final-source checks.

Required final software/frontend/browser checks, process-cleanup receipts,
exact-head CI, controller integration, merged-main verification and public package
delivery evidence belong on the owning issue. Generated fixture data and browser
logs stay ignored. The task does not open the real application Store, transfer
scientific images, restart an assessment, infer or train models, or edit actual
reviewed annotations. This repairs review interaction; it establishes no model
improvement, badminton accuracy, general screen-reader or WCAG conformance.

The incomplete [scene assessment](SHUTTLE_SCENE_FRESH_ASSESSMENT_REPORT.md) and its
original evidence remain unchanged. Complete independent rally references remain
**0/2**, and reliable full-match automatic annotation remains unproven.
