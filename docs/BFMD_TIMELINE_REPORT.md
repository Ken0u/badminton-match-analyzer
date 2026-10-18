# Broadcast timeline supervision

The optional `import-bfmd` command normalizes a pinned local BFMD reference
snapshot for future contact, rally and scene work. Actual import preserves
**34,020 source records across 19 matches**, including seven doubles matches.
No source media are decoded, no app annotations are edited, and **zero records
are training-ready** until source alignment and review are completed.

## Source and reproduction

The [official repository](https://github.com/Ning-D/BFMD/tree/c7c7e8e4c815085dda42746f16e07f1172503312)
and [dataset page](https://ning-d.github.io/BFMD-Dataset/) identify the author-linked
annotation folder. The packaged `bfmd_manifest.json` pins 35 reference files,
14,709,189 bytes, by size, SHA-256, original path and public file ID. Source videos,
inferred tracks, captions, weights and executable helpers are not required.
The dataset restricts use to non-commercial academic research and prohibits
redistribution. Normalized data remain local and ignored; they are not included
in the wheel or treated as unrestricted deployment assets.

Obtain the permitted reference files from the author-linked source, preserving
either the published directory paths or the flat `download_name` entries in the
manifest. Run:

```powershell
.venv/Scripts/python.exe -m badminton.cli import-bfmd C:/data/BFMD-reference-files --output data/datasets/bfmd/v1
```

Every pinned file is verified before normalization and rechecked before writing.
Both local layouts are accepted; conflicting duplicate copies fail rather than
falling back to a different version. The importer never follows video paths from
the source task JSON. Output must be outside the source directory. An exclusive
output lock prevents simultaneous imports. Byte-identical repeats return the
same result; modified, partial or differently versioned outputs are preserved
and require a new destination.

## Preserved evidence and exclusions

| Source evidence | Actual count |
| --- | ---: |
| Singles / doubles matches | 12 / 7 |
| All normalized source-result ranges | 34,020 |
| Published generic hit markers | 16,751 |
| Published rally intervals, including predictions | 1,688 |
| Published replay intervals | 795 |
| Manual-origin / prediction-origin results | 34,015 / 5 |
| Conflicting point-type frames | 451 |
| Partial doubles choice records, including 17 empty labels | 943 |
| Metadata rally intervals / metadata-only intervals | 1,058 / 4 |
| Weak contact-label-eligible records | 16,503 |
| Weak family-label-eligible contacts | 10,850 |
| Side-label-eligible / training-ready records | 0 / 0 |

The five prediction-origin results are **rally intervals inside the annotations
container**. Thirty-seven manual hit markers lie only inside those inferred
intervals. There are 211 hits outside every published rally interval, but
**248 outside active manual rally support**. The importer retains every record
while preventing inferred intervals from certifying live context for those hits.
Container membership is not sufficient evidence of manual provenance.

Conflicting family markers are collected by exact published point ordinal. Their
candidate labels survive, but no family is selected. A separate, valid manual hit
marker can retain weak contact eligibility despite that family ambiguity.
Only generic hit records receive family targets, avoiding duplicate supervision
from the parallel family-marker layer. Unknown labels cannot be hidden by a
known label at the same point. Source-result type/value mismatches, duplicate or
nonpoint contacts, and contacts outside manual rally support are quarantined.

The partial doubles `choices` layer retains point/action intervals and raw
choices without pretending its intervals are exact contacts or complete labels.
Metadata are preserved separately, including the singleton-list wrapper and four
intervals absent from manual timeline exports. Backup metadata and the index's
`TOTAL` row are not additional matches or manual rallies. Predicted, cancelled,
missing and malformed source records are not silently promoted or dropped.

The six requested families map directly; `net_shot` maps to net. Serves remain
separate, and net kills, pushes, presses and blocks retain their source labels
under other. No half-smash class is introduced. Structured forehand/backhand and
persistent individual identities remain unknown.

All published ranges and raw results survive without changing their endpoints.
The documented 30 fps convention does not establish the actual video clock or
zero/one ordinal base. Publisher `VERIFIED` video-index status is retained as a
source claim, not promoted to verified local alignment. No seconds, exact rally
endings, automatic live/replay negatives or application truth are fabricated.
Positive-length source live/replay overlaps are explicitly excluded if present;
none occur in this pinned snapshot. Original-broadcast/cross-corpus grouping is
still unreviewed and all learning splits remain unassigned.

## Output and verification

The local index contains `events.jsonl`, `matches.json`, preserved source task
headers, raw metadata, separate metadata-rally records and source indexes.
`manifest.json` records output hashes, provenance, counts, eligibility, issues,
rights and unresolved alignment. This is research supervision preparation,
not a new model or improved annotation accuracy.

The final suite passes **745 tests with four optional GPU skips**; all 38 BFMD
tests pass. They cover provenance separation, ambiguous families without erasing
contact support, inferred rally containment, interval/type errors, partial choice
layers, source mutation, immutable outputs, locks and the actual offline CLI.
Ruff check/format covers 109 files, dependency consistency and whitespace checks
pass. The built 0.25.0 wheel contains all 72 expected package files, matching the
worktree byte-for-byte. Its actual CLI imports all 35 source files without loading
Torch, and reproduces identical normalized bytes. The
[machine receipt](bfmd-timeline-verification.json) pins the evidence.

The separate frozen 75-rally R2/R3 evaluation continues with unchanged source,
models, thresholds, native runtime and denominators. BFMD records do not enter it.
Next verify original media clocks and source overlaps, independently review the
timeline and semantic targets, then develop contact/rally/scene and doubles models
on declared development sources. Deployable complete-match correctness remains
unestablished.
