# Procedural synthetic shuttle adaptation

Owning task: [issue #305](https://github.com/Ken0u/badminton-match-analyzer/issues/305),
under the [localization roadmap](https://github.com/Ken0u/badminton-match-analyzer/issues/65).

This experiment is being prepared. No result or improved annotation accuracy
is established. The installed model and application defaults remain unchanged.

The [fixed protocol](../data/manifests/shuttle_synthetic_protocol_v1.json)
trains one final-decoder adaptation entirely on own generated footage. Complete
generated source groups are separated into training, validation and test. Four
epochs use only synthetic validation for selection; the synthetic test opens
after selection. Familiar real-source labels are diagnostic only and never
drive training, selection or tuning. All 60 familiar cases and 28 unknowns
remain; full control reproduction precedes candidate real inference.

Generated geometry is procedural truth, not expert badminton supervision.
Complete scientific rally references remain 0/2; source eligibility stays false.
Native execution, measured results, failures and delivery evidence are pending.

Preparation validation: **4,658 full Python tests pass**, with
four optional skips; 154 focused tests pass. Required Ruff, formatting,
dependency, repository and diff checks pass. 938 recorded process
lifetimes are independently terminal. The first local launcher named a
nonexistent legacy test file and stopped before tests; the corrected launcher
and all results are preserved. Generated tests used own procedural inputs
and random model parameters. No real checkpoint loading, research training
or native-source predictions have run yet.
