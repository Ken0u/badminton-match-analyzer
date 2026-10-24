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

Generated focused verification passes 74 tests, including the unchanged comparator
suite. Actual acquisition/comparison and final integration/delivery are pending
at this producer checkpoint. Software tests establish tool behavior, not expert
label truth, native correspondence or badminton accuracy.

Training, independent-test, deployment and redistribution eligibility remain
false. Public access, code MIT and intended research use do not grant dataset or
media rights. No media, models, predictions, consumed holdout, image assessor,
inference, training, model promotion or application annotation changes are part
of this task. Full-match automatic correctness and complete-rally references
remain unresolved.
