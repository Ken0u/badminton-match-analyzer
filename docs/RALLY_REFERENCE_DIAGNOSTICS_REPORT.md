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

## Completed original-host census

The [prospective issue seal](https://github.com/Ken0u/badminton-match-analyzer/issues/238#issuecomment-6386604477)
at October 24, 2026, 16:23:36 UTC precedes execution. Tested consumer
`9b667d7ffe3d31b829a9c9c952ac74f46cfe4c8f` ran from a separate clean snapshot.
Context SHA256 is
`e0a4b3579d53a7c5927df892c1e4c3d62cfc47be790fb9f255975bf48cd54547`;
protocol SHA256 is
`000ed041e6e12c1a2fbec3fb295f04287a825930169bbb5519bf0f07a65d1a11`.
The configured-owner frozen-scope decision used the owner's explicit delegation
while away; no personal human PR review is asserted.

The real shared Store admitted and completed the metadata job. The observed
wrapper, virtual-environment launcher and actual Store owner are independently
absent, with matching terminal, job and artifact seals. Global provenance
verified all 1,014 historical execution identities, all 256 validated targeted
references and 8,177,560,145 historical attempted image bytes before scientific
comparison. This run added **zero scientific sessions and zero image payload**.
No source was viewed, decoded, prepared or transmitted. Private output accounting
at the independent audit was 27,471,435 new bytes and 2,393,981,817 cumulative
retained bytes, within both bounds.

Unchanged acceptance exactly reproduces **0/2 complete references** and **0/2
fully supported observed-contact label slots**, with the same reasons and all
four eligibility flags false. Target coverage remains 991/991 singles and
541/541 doubles. Private aggregate SHA256:
`826270e19a43e92986afcd5464231632ddb3edbe028799823f1bb8cce37e37d1`;
private ledger SHA256:
`cdb6a7f59417a0a17eee3313619b3c77e37357b9d64e2a28107e3be9dac92b33`.
Neither file, original labels nor per-contact intervals are redistributed.

## Frame and source-context support

All three singles streams inspect 991 unique native frames in 1,333 memberships
each; each has 342 repeated overlap observations. All three doubles streams
inspect 541 unique native frames in 707 memberships each, with 166 repeated
observations. Every stream retains its complete native denominator and zero
uninspected source frames. A/B are exhaustive original streams; resolution is
the separately executed targeted adjudication stream, which happened to require
every native frame for these sources.

| Source / stream | Conflicting frame variants | Possible-contact frames | Unknown-contact frames | Gap-covered frames | Unknown-scene frames |
| --- | ---: | ---: | ---: | ---: | ---: |
| Singles A | 12 | 102 | 20 | 991 | 958 |
| Singles B | 18 | 94 | 13 | 991 | 987 |
| Singles resolution | 33 | 111 | 32 | 991 | 958 |
| Doubles A | 6 | 17 | 5 | 541 | 1 |
| Doubles B | 9 | 19 | 8 | 541 | 0 |
| Doubles resolution | 18 | 16 | 16 | 525 | 1 |

Each count is a unique-frame union over its own recorded category. Categories
can overlap when observations conflict and must not be summed into a partition.
Singles resolution records zero live-scene frames and 33 non-play frames;
doubles resolution records 247 live and 303 non-play frames, with conflicting
variants retained. These are recorded judgments, not new source review. A
known camera-view string and uncensored document flags do not establish live
play, complete boundaries or a known absence of contact. In particular,
`none_observed` records remain inside unresolved gaps rather than becoming
negative ground truth.

## Event repetition, identity and boundaries

| Source / stream | Raw event occurrences | Distinct signatures | Repeat excess | Distinct contact keys | Overlapping distinct-key pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| Singles A | 43 | 41 | 2 | 7 | 0 |
| Singles B | 40 | 40 | 0 | 9 | 1 |
| Singles resolution | 47 | 45 | 2 | 11 | 1 |
| Doubles A | 6 | 6 | 0 | 1 | 0 |
| Doubles B | 9 | 9 | 0 | 1 | 0 |
| Doubles resolution | 8 | 8 | 0 | 2 | 0 |

All four excess repeated occurrences are across documents; there are no within-document
signature repeats or conflicting same-kind/same-interval signatures. Singles
resolution still has an intersecting pair of distinct contact keys, separate
from its two repeated signatures. Deduplicating exact signatures does not remove
that pair. The census cannot decide whether intersecting uncertainty intervals
describe one or several physical contacts, and changes no interval or event.

| Source / stream | Actor ID groups / conflicting definition groups | Locally unsupported contact occurrences / all contact occurrences |
| --- | ---: | ---: |
| Singles A | 7 / 7 | 8 / 8 |
| Singles B | 8 / 7 | 9 / 9 |
| Singles resolution | 5 / 5 | 11 / 11 |
| Doubles A | 45 / 22 | 1 / 1 |
| Doubles B | 44 / 27 | 1 / 1 |
| Doubles resolution | 10 / 8 | 2 / 2 |

Actor ID groups are strings used within a stream, never verified people or roster
counts. Conflicting definitions and local unsupported identity remain explicit;
a later description cannot retroactively support an earlier contact.

Singles resolution records one serve occurrence, ten shot occurrences, 36
unresolved-contact occurrences and no terminal event. Four contact occurrences
retain unknown side, and eight shots retain unknown family. Doubles resolution
records no serve, two shots, five unresolved contacts and one `stopped_play`
ending; stopped play does not locate the terminal moment. One shot retains
unknown side. These partial judgments cannot supply complete rally references
even where a family label is present.

## Verification and next evidence

Final generated verification passes **431 focused and 2,776 full tests, with
four optional skips**, plus Ruff, formatting, dependency, repository/JSON/link
and whitespace checks. All 190 recorded final test lifetimes are independently
absent. An earlier 2,771-test suite passed before unused-import cleanup and added
guards; another 2,775-test suite passed before correcting accounting of pytest
directory links. Initial lint and accounting failures and every earlier output
remain preserved. The final accounting counts nested link metadata without
traversing targets and rejects linked task roots. Generated native Store tests
exercise both completion and failure; they are distinct from the actual run.
Only this report changes after the tested consumer; executable, test and protocol
bytes remain identical. Exact PR/main CI, normal controller integration and
independent complete public delivery remain required at this report revision.

A separately specified temporal-context review must address live/scene support,
the unresolved contact regions, locally supported actor identity and original
opening/terminal evidence, preserving occurrence provenance and inclusive native
intervals. It must distinguish repeated mentions from distinct contacts and
define any cross-chunk identity links prospectively. This metadata census cannot
establish why source assessors left unknowns or resolve them without new source
evidence. It supplies no new source-review allowance or acceptance criterion.

Agent judgments remain development evidence, not expert gold or demonstrated
automatic match accuracy. All four eligibility flags remain false;
#62/#66/#67/#71 remain incomplete. No training-ready rows or promoted model result
from this completed diagnostic execution.
