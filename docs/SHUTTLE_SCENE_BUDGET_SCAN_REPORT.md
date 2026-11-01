# Retained-output scan accounting

Owning software task: [#361](https://github.com/Ken0u/badminton-match-analyzer/issues/361).
The [original scene assessment](SHUTTLE_SCENE_FRESH_ASSESSMENT_REPORT.md) remains
incomplete. This change launches no scientific sessions or image transfers.

## Trigger and change

Every durable assessor output checks the retained-output allowance. The old
traversal queried the same entry repeatedly through `lstat`, `is_symlink` and
`is_dir`, plus repeated checks at each retained root. An earlier metadata-only
operational profile measured 117,766 queries and 15.258 seconds for one scan on
this workstation; its 164,159,370-byte total describes that earlier snapshot.
It is motivation, not a scientific result or current production measurement.

The scanner now classifies each entry from one fresh non-following `lstat`
result. It uses the mode for symbolic links/directories and the Windows reparse
attribute for junctions and other reparse points. Root links still fail;
interior links charge their own metadata without traversing targets. Files
remain charged per occurrence, including hard links. Ordinary directory metadata
is not charged. Every call enumerates both task-prefix cache roots and matching
worktrees again; growing files and new roots enter the next total.

Missing or unreadable entries and enumeration errors propagate, preventing a
partial total from authorizing a write. No cached sizes, skipped failures,
deleted fixtures, changed prefixes, output ceilings, write headroom or durable
write semantics are introduced. Traversal is not an atomic filesystem snapshot;
this change does not claim protection from arbitrary concurrent tree replacement.

## Generated verification

A generated tree with 1,201 files and 63 directories has an independently
computed total of **24,009 bytes**. Five scans of each source reproduce it:

| Source | Metadata calls per scan | Median elapsed seconds |
| --- | ---: | ---: |
| Baseline `0528ec6` | 3,800 | 0.173 |
| Candidate | 1,264 | 0.067 |

This is a 66.7% reduction in metadata calls on that generated tree. Timing is
machine-specific, includes measurement overhead and is not a production speed
guarantee. A separate 22-entry regression fails on the baseline's 68 queries
and requires exactly 22 fresh, non-following metadata queries after the change;
it does not assert wall-clock timing.

Generated controls independently verify totals across roots/worktrees, file
growth, newly added roots, hard-link occurrences, symbolic-link/reparse markers,
root-link rejection, interior target exclusion, disappearance, metadata denial
and directory enumeration denial. Two existing link controls now inject the
link marker at `lstat` metadata instead of intercepting `is_symlink`; their
original root-rejection and interior-no-traversal assertions remain. The first
metadata-call probe patched `os.stat`, which Python 3.10's pathlib accessor had
already captured, and counted zero calls. It was corrected to observe
`Path.stat`; the real baseline then records 68 queries. An adapted fixture's
temporary variable shadowing error is preserved separately from final results.

All 193 focused runner tests pass, including unchanged quota/collector,
ownership, budget, source identity, blind-stream, unknown and denominator
controls. Required full Python/frontend/browser/repository checks, terminal
process receipts, exact PR/main verification and public candidate delivery are
recorded on the owning issue. Private generated trees and failure receipts remain
under ignored `.cache/budget361-*` paths.

## Scientific boundary

The CLI remains bound to expired scientific task #359 and its unchanged
protocol, source hashes and eligibility. This code-only task cannot make any
assessment session eligible. Original videos, galleries, readings, frozen
consumers, Store records, deadlines and failed-attempt evidence are preserved.
No real application Store, private semantic labels, inference, training or
promotion is used. Any future image assessment needs its own authorized scope,
committed grant, prospective freeze and runtime. Independent complete-rally
references remain **0/2**; model improvement and full-match correctness remain
unestablished.
