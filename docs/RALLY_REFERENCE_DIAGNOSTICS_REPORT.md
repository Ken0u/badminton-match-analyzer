# Sealed rally-reference diagnostics

[Issue #238](https://github.com/Ken0u/badminton-match-analyzer/issues/238)
defines a metadata-only census of the completed [two-source assessment](COMPLETE_RALLY_REFERENCE_REPORT.md).
The [protocol](../data/manifests/rally_reference_diagnostics_v1.json) preserves
all 1,532 native frames, all unknowns, historical failures and the unchanged
**0/2 complete-reference result**. No additional source assessment is authorized.

The [command](../scripts/diagnose_rally_references.py) requires the original
host's private evidence and frozen checkouts. It replays the original global
metadata gates without calling the old audit that writes an aggregate. Only
after all 1,014 global execution identities and 256 validated targeted references
verify does it read validated scientific JSON. It calls the unchanged frozen
acceptance directly and requires exact parity with the sealed #228 result.
No failed scientific output is parsed for labels.

The [census](../backend/badminton/rally_reference_diagnostics.py) retains every
frame, actor and event occurrence with document/row provenance in a private
ledger. Unique-frame category counts are unions and may overlap when repeated
observations conflict. Event signatures follow the original acceptance fields;
free-text reasons remain in original occurrences. Repeated signatures,
conflicting same-interval keys and intersecting distinct contact keys are
separate counts. These groups do not establish the number of physical contacts.
`none_observed` remains a source judgment, not a known negative.

Execution requires a tested committed consumer, prospective owning-issue seal,
fresh committed grant, credential-free original roots and real shared Store
admission. It uses exclusive new outputs; any attempted run is preserved rather
than overwritten or implicitly restarted. The four-hour metadata interval does
not renew any historical source-assessment deadline. New task outputs are
limited to 1 GiB; cumulative retained scientific outputs remain below 8 GiB.
No new image payload, assessor, media decode, inference, model or training is
involved. Integrity hashes and original PNG format/header verification are
permitted without viewing images.

Actual census execution and final verification are pending at this prospective
implementation snapshot. Generated tests and processing coverage cannot
establish label truth, expert gold or automatic match accuracy. All four
eligibility flags remain false; #62/#66/#67/#71 remain incomplete. A later
temporal-context source review needs its own independent frozen specification;
this census neither relaxes the acceptance gate nor authorizes another image pass.
