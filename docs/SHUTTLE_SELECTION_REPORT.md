# Observed shuttle component selection

Task [#330](https://github.com/Ken0u/badminton-match-analyzer/issues/330), under
[localization roadmap #65](https://github.com/Ken0u/badminton-match-analyzer/issues/65).

Implementation and verification are in progress. No new scientific inference,
scorer training, held-out test or familiar-source scoring has started.
Application defaults and all existing neural checkpoint bytes remain unchanged.

The [frozen protocol](../data/manifests/shuttle_selection_protocol_v1.json)
compares the unchanged component selector with a learned observed-component
scorer and abstention rule for each of three fixed neural checkpoints. Owned
procedural groups use a new source namespace and separate training, validation
and test groups. All scorers and validation-selected thresholds must be sealed
before any new test group is generated. A subsequent diagnostic uses the
complete previously sealed familiar-source observations, retaining unknowns and
negative cases. Those familiar inputs are never used to fit or select a scorer.

The [capacity comparison](SHUTTLE_CAPACITY_CONTINUATION_REPORT.md) motivates the
selection hypothesis: an agreeing component can exist while the selected point
is wrong. Component selection cannot recover a shuttle absent from every
observed component. Generated success alone cannot establish real badminton
accuracy or justify installation of learned weights.

Actual results, failures, complete denominators and delivery evidence will be
recorded after the frozen stages execute. Complete scientific rally references
remain **0/2** and full-match annotation accuracy remains unproven.
