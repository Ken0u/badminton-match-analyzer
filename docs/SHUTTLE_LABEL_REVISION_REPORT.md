# Pinned shuttle label revision accounting

Issue [#220](https://github.com/Ken0u/badminton-match-analyzer/issues/220)
compares preserved original Test CSV bytes with 29 immutable upstream corrected
objects. The [source manifest](../data/manifests/shuttle_label_revision_sources_v1.json)
pins the original archive/declaration/report, upstream commit/tree and all corrected
blob identities. Raw labels and process receipts remain private under `.cache/`.

The two-stage entry point is `scripts/compare_upstream_shuttle_revision.py`.
`metadata` verifies original-host hashes and terminal Store/process evidence,
reuses the safe archive census, freezes the complete literal identifier union,
and acquires only bounded public documentation and correction metadata. After
source/usage inspection, `compare --metadata-sha256 HASH` verifies the unchanged
runtime/input context and metadata gate, copies only Test label members, verifies
29 anonymous immutable corrected objects and invokes the existing
[comparator v1](SHUTTLE_LABEL_COMPARISON.md) unchanged. Both stages use real shared
Store admission. Interrupted acquisition is preserved and never retried implicitly.

All source bases are deliberately null. Filenames, correction code and creator
assertions do not independently bind labels to native source bytes and clocks.
Three upstream match1 filenames begin `2_` where the creator inventory cited `1_`;
the tool never aliases them. Missing/unmatched cases, unknown visibility and
inherited quarantine remain explicit. Every case conservatively retains the
inherited-quarantine restriction; this does not assert that every original CSV
was incomplete. Attributed native counts/tails stay separate from newly parsed
publication accounting. No native frame-pair visibility or coordinate score is
available under this protocol.

Limits are 48 requests, less than 4 MiB per response and at most 8 MiB total
network bytes, at most 8 MiB of combined private label copies, three hours from
the fresh grant and 256 MiB retained new outputs. Requests use exact allowlisted
HTTPS URLs, no authentication/cookies/proxy, redirects or automatic retry. Existing
outputs are never overwritten; complete files are flushed and published using
no-replacement hard links. Use a source checkout with the original virtual
environment and preserved local inputs. A clone alone does not supply the archive.

The first metadata attempt verified original inputs and eight public responses,
then stopped before label acquisition because the initial inventory selector
counted the separate `corrected_test_label/drop_frame.json` as a CSV. Its failed
Store record, original exited process and outputs are preserved. The bounded
repair excludes that pinned metadata object from the CSV denominator and uses
its actual subdirectory path. Explicit `--resume-metadata-from OLD_OUTPUT` reuses
complete prior responses without repeating requests; it verifies old runtime/input
bindings, original process absence, failed Store identity and preserved backend.
Incomplete requests remain terminal and cannot be resumed by this option.

## Actual private comparison, October 24, 2026

Producer `ca51050` verified the original 1,731,120,724-byte archive and pinned
declaration, aggregate report and terminal evidence on their original host.
Both original job lifetimes were absent and their shared Store/artifact bindings
matched. The successful metadata and comparison jobs are completed and their
original process lifetimes are independently observed absent. Before/after
reviewed-annotation and prediction/weight artifact metadata are unchanged.

The acquisition used **39 distinct requests / 303,883 network bytes**, including
the eight responses preserved from the first attempt; no request was repeated.
There are 342,498 combined private label bytes: 177,191 original and 165,307
corrected. All 29 corrected lengths and Git blob hashes match the pre-frozen
inventory. Five prior documents match exactly; the sixth, the public mirror
release metadata, differs only in its asset download counter. Its changed bytes
remain separate from the original declaration; no changed semantics are adopted.

| Published group | Cases | Original records | Revised records | Shared raw ordinals | Original-only / revised-only ordinals | Byte-equal cases | Native compared cases |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| match1 | 11 | 4,222 | 4,222 | 4,222 | 0 / 0 | 0 | 0 |
| match2 | 7 | 4,231 | 4,231 | 4,231 | 0 / 0 | 0 | 0 |
| match3 | 11 | 4,203 | 4,203 | 4,203 | 0 / 0 | 0 | 0 |
| Total | 29 | 12,656 | 12,656 | 12,656 | 0 / 0 | 0 | 0 |

The actual archive and corrected publication have the same 29 literal identifiers,
including the three `2_` match1 names. No aliases were needed or introduced.
Their disagreement with the earlier creator `1_` names remains unresolved; shared
archive filenames do not supply an independent native identity binding.

All 29 byte strings differ. Byte inequality includes serialization differences
and does **not** establish changed numeric values, corrected accuracy or model
errors. Both sides contain 12,656 parsed records, with no syntactically invalid,
duplicate or reversed ordinals and no unknown visibility flags. These are raw
publication counts, not native coverage or physical visibility findings. All
29 cases remain unscored; native missing/tail counts and visibility/coordinate
comparisons are null. Zero scored cases must not be read as zero annotation errors.

The earlier pinned report attributes 201 clips / 91,214 rows / 91,579 native
frames, with 25 incomplete CSVs / 12,235 quarantined rows / 365 unlabelled tail
frames. Its Test subset attributes 12,658 native frames, two more than the newly
parsed 12,656 published records, both in match2. Those prior native observations
were not decoded or re-certified here. All prior quarantine/tails remain intact;
the null-basis comparison cannot repair them or identify a new native denominator.

Source-code inspection also exposes an upstream visibility concern: the pinned
[correction UI](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/correct_label.py)
assigns visibility 1 for a click at `(0, 0)` and 0 otherwise, opposite to the
[creator description](https://hackmd.io/@TUIK/rJkRW54cU)'s stated convention.
The code's saved ordinal range and separate `drop_frame.json` metadata do not
prove source alignment. No inference is made about which rows used that UI path,
which labels are correct, or which source frames show a shuttle. No labels are
inverted, repaired or installed as truth.

The unchanged comparator protocol SHA256 is
`4bad27941508a2f8a3b7aeab9eb3950820e9be2721323cad81d2ceca8018115a`;
the frozen literal inventory is
`7f818af60e3744c782ebdfc364890f58f36b76345f1106f3af6c6a95250caf58`;
the inspected metadata gate is
`395ec73744be308efc20712c0eca454b3663694d89fd8ee174f5758c56315ef9`;
the aggregate comparison is
`64e0a9dbddd9151210451ea430960396933799ef427b2822cef25dc58aae655f`.
An independently implemented private CSV/ordinal census matches every reported
case, record count, ordinal union, hash and denominator. This arithmetic check
is separate from independent scientific assessment, which remains unavailable.

Generated focused tests and final project/PR/main/delivery checks are recorded
on the owning issue. They establish software behavior, not expert label truth,
native correspondence or badminton accuracy. The initial failed metadata attempt
is preserved and was not converted into a success receipt.

Training, independent-test, deployment and redistribution eligibility remain
false. Public access, code MIT and intended research use do not grant dataset or
media rights. No media, models, predictions, consumed holdout, image assessor,
inference, training, model promotion or application annotation changes are part
of this task. Full-match automatic correctness and complete-rally references
remain unresolved.

## Complete case inventory

Every row below has null native bases and remains unscored with inherited
quarantine restrictions. Counts are publication records/shared raw ordinals;
neither side has an exclusive raw ordinal. No case has an unknown record count.

| Case | Original records | Revised records | Shared raw ordinals | Byte equal |
| --- | ---: | ---: | ---: | --- |
| match1.1_05_02 | 517 | 517 | 517 | No |
| match1.1_05_03 | 395 | 395 | 395 | No |
| match1.1_06_03 | 349 | 349 | 349 | No |
| match1.1_07_03 | 687 | 687 | 687 | No |
| match1.1_07_04 | 215 | 215 | 215 | No |
| match1.1_07_06 | 343 | 343 | 343 | No |
| match1.1_09_06 | 133 | 133 | 133 | No |
| match1.1_09_07 | 681 | 681 | 681 | No |
| match1.2_02_07 | 155 | 155 | 155 | No |
| match1.2_03_08 | 146 | 146 | 146 | No |
| match1.2_03_10 | 601 | 601 | 601 | No |
| match2.1_03_03 | 439 | 439 | 439 | No |
| match2.1_04_04 | 298 | 298 | 298 | No |
| match2.1_11_11 | 717 | 717 | 717 | No |
| match2.1_13_12 | 653 | 653 | 653 | No |
| match2.1_19_15 | 735 | 735 | 735 | No |
| match2.2_02_05 | 774 | 774 | 774 | No |
| match2.2_08_12 | 615 | 615 | 615 | No |
| match3.1_02_00 | 707 | 707 | 707 | No |
| match3.1_03_02 | 466 | 466 | 466 | No |
| match3.1_05_02 | 779 | 779 | 779 | No |
| match3.1_05_03 | 214 | 214 | 214 | No |
| match3.1_06_05 | 246 | 246 | 246 | No |
| match3.1_06_06 | 341 | 341 | 341 | No |
| match3.1_08_08 | 288 | 288 | 288 | No |
| match3.1_08_09 | 230 | 230 | 230 | No |
| match3.1_09_12 | 336 | 336 | 336 | No |
| match3.1_09_15 | 247 | 247 | 247 | No |
| match3.1_10_16 | 349 | 349 | 349 | No |
