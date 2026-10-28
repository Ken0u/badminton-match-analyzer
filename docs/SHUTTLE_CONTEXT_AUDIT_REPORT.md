# Frozen shuttle source-context audit

The archived familiar comparison was unavailable because **neither frozen
source snapshot contains any reviewed scene ranges**. All 50 views and 60 cases
for each of control, decoder and convolution lack verified live-scene coverage.
Camera metadata and source identity are present and consistent. The original
guard correctly refuses to assume that unlabelled footage is live play.

This is a metadata diagnosis for [issue #337](https://github.com/Ken0u/badminton-match-analyzer/issues/337),
following the [archived comparison](SHUTTLE_SELECTION_CONTINUATION_REPORT.md).
It adds no accuracy measurement, source annotation or usable learned prediction.
Complete independent rally references remain **0/2**. Full-match annotation
correctness remains unproven, and all four eligibility flags remain false.

## Retained denominators and findings

The same original cases occur under each method; counts across methods are
repeated observations, not 180 independent cases. Diagnostic flags can overlap
and must not be added to estimate a case denominator.

| Method | Views retained | Cases retained | Eligible views | Eligible cases | Cases without live context |
| --- | ---: | ---: | ---: | ---: | ---: |
| control | 50 | 60 | 0 | 0 | 60 |
| decoder | 50 | 60 | 0 | 0 | 60 |
| convolution | 50 | 60 | 0 | 0 | 60 |

Source-level counts below apply separately to every method.

| Original source | Views | Cases | Annotation revision | Scene ranges | Cases without live context |
| --- | ---: | ---: | ---: | ---: | ---: |
| Supplied singles, `970dbd8adfe548d8` | 25 | 35 | 0 | 0 | 35 |
| Supplied doubles, `c406a1187130b845` | 25 | 25 | 0 | 0 | 25 |

The corrected audit finds zero missing/malformed runs, missing/malformed camera
metadata, uncovered/ambiguous camera coverage, malformed scene metadata,
ambiguous live coverage, source mismatches or missing/ambiguous view membership.
There are also zero explicit replay, non-play or unknown scene exclusions in
these snapshots. An empty scene list is present, valid metadata with **no live
coverage**; it is different from a missing list and supplies no scene label.
It cannot establish whether any actual footage is live, replay, non-play or
unresolved. No source image or original visibility/coordinate label was opened
to make this diagnosis.

This identifies absent scene-review support as the immediate prerequisite.
It provides no evidence of an original producer/consumer schema defect and no
reason to weaken the archived `eligible_segments` or `excluded_scene` guards.
Those consumers, the archived unavailable result and its missed delivery
deadline remain unchanged.

## Frozen provenance and reproducibility

The [public protocol](../data/manifests/shuttle_context_audit_protocol_v1.json)
was committed at `09d9828ebb7e4f9d7d3c185574c4738b610dd6ca` before the first
original context projection. Its SHA256 is
`4b174c0a9ada57232df4b671da10417e824452cb83398059883b2ea05920e759`.
It fixes the projection whitelist, classification flags, all denominators,
five archived consumer/producer file hashes and both context-function hashes.
The original source revision is
`7bc86dad931e4d9dc35178a2b189ef78dfadc1e2`.

| Frozen input | SHA256 |
| --- | --- |
| Original experiment, hash only | `be75300db6e3d12568f3a2195ffe699ab5e47c600f7e995f38a5c1eea3988044` |
| Sealed familiar result, hash only | `0bfeec21581f436ca830edf6d9dfacc7989962925ccf6eaa5471cd644a76b971` |
| Original public protocol, hash only | `834891e59c851f3841e7e6e0037d8181691cab5f6a6122a61fe9d0c0f4bbf005` |
| Original source packet | `3b22c07a3592728b6aa17e7d7c28f0089a8820b1373ace1289796d2e99e5466d` |
| Baseline context container | `915f678fa2b5577dff37811ba92ff9077c300eefc788fcab2873c12c2ffc6f64` |
| Raw-index view inventory | `a0a383d3df756f0095d0025b414385d8294aa77df5fb286d69a174d377daa4df` |

The corrected metadata consumer was pinned at
`906170c4f4854f75ac3544b6a78dc5804d59cba0` before its run:

- Consumer SHA256: `f9506df041625bfea3178aae1278441fea9391c3132c7690915ca795c8456a2b`.
- CLI SHA256: `b965871dc0de71e3effc460ac04f079029771a92173b89b34230a09a9a32166e`.
- Aggregate output SHA256: `6d1392403fe478b534159200d469a93d28f81e6ac24c58f8e26875467d2c764e`.
- Private diagnostics SHA256: `9a088cc000e140a5769ba50c3e81182508a35e6ce293946f13f659a65f0ee831`.
- Completion receipt SHA256: `1a5473e74cdae0d562d7b3205f6bae81bce86fcaf4e5d41bb649d0de42ccb8eb`.

The run binds 306 JSON files, including hash-only containers, run descriptors and
receipts. It writes 214,834 bytes in a new private output directory. All six
original frozen inputs and the pinned implementation remained byte-identical
before and after execution. The JSON container decoding needed for the allowed
projection does not consume original scientific rows: only case IDs/source/frame,
view membership, run source/camera/cut metadata and baseline source/revision/scene
metadata feed the audit. Original coordinates, scores, components, poses,
contacts, shots and visibility labels are discarded rather than inspected.
There is no model/media loading, Store access, fitting, inference or evaluation.

The reproducible command is:

```sh
python scripts/audit_shuttle_context.py --root ORIGINAL_NAMESPACE --protocol data/manifests/shuttle_context_audit_protocol_v1.json --bindings PRIVATE_BINDINGS.json --output NEW_PRIVATE_DIRECTORY
```

`PRIVATE_BINDINGS.json` maps the six protocol input names to original paths
within `ORIGINAL_NAMESPACE`; input bytes must match the frozen hashes. Raw-index
descriptors locate the original receipt/run files. A clone does not contain
these private artifacts. The tool refuses existing output, root escapes,
symlink/reparse metadata, changed hashes, source mutations and changed consumers.
It preserves unavailable inputs and all declared cases/views; it never creates
missing context. Per-case diagnostics stay local. Public output contains only
aggregate counts, hashed source groups and provenance.

## Audit implementation corrections and verification

A generated regression first caught final verification ordered incorrectly:
an input could change during the last consumer check and still be published.
The final input verification now follows that check, with additional protocol,
binding and implementation mutation guards. The failed generated attempt is
preserved.

The first real metadata projection conservatively marked a source mismatch
because the new audit expected an embedded annotation `video_id`. The actual
`Annotations` schema has no such member: the catalog binds the document to its
source. The correction retains catalog/video/run ID and source-hash parity,
exact annotation revisions, and rejection of any explicitly conflicting
annotation source ID. A regression uses the real annotation schema. The first
output is retained separately; it is not the corrected receipt listed above.
No archived scientific consumer, original annotation or protocol changed.

All 30 focused generated tests pass, including 360 combinations compared to
the exact archived guard on generated metadata. Regressions cover missing and
malformed context, half-open intervals and cuts, overlapping live/camera ranges,
explicit scene exclusions, source/revision conflicts, ambiguous membership,
unknown-source denominators, private-field suppression, forbidden-container
hash-only binding, source mutation and exclusive CLI output. These establish
software behavior and diagnostic provenance, not badminton accuracy. Full
software checks and exact PR/main/public delivery evidence belong on the owning
issue; they do not turn metadata into independent scene review.

## Next prerequisite

Freeze a separately scoped, source-only scene-review protocol for the original
windows, preserving native frames, PTS/orientation, detected cuts, exclusions and
uncertainty. Independently review live/replay/non-play/unknown ranges, recording
unresolved intervals as unknown. Produce a new immutable context revision with
its own evidence; preserve this frozen baseline and every original prediction.
Only then consider a new, separately frozen familiar-source comparison with
complete denominators. This metadata audit does not authorize that comparison,
change old research clocks, or establish a fresh held-out test. Unseen full
singles/doubles match correctness and both independent rally references remain
open.
