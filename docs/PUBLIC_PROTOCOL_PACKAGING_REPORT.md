# Public protocol files in source distributions

[Issue #275](https://github.com/Ken0u/badminton-match-analyzer/issues/275)
repairs a reproducibility gap in the public source archive. Candidate
`40167963093`, source `0e5a17c278e050e41c7993677c7cd8a43ca957eb`, included
tests and documentation that require public protocol JSON files but omitted all
45 tracked files under `data/manifests/`. Its source archive SHA-256 was
`154bcffe6eaff7745f3569da00f4b11fbd3ee46b624dd303c8a1b40d6b308733`.
For example, the distributed CLI contract test opens
`data/manifests/rally_review_contract_v1.json`, which was absent.

Earlier successful package checks verified backend, frontend and lock parity;
they did not require these protocol files. Those successful checks and the
original deficient archive remain preserved as separate evidence.

## Inclusion and verification

`MANIFEST.in` now names each of the 45 existing public JSON files explicitly.
It introduces no data-directory wildcard and changes no protocol contents.
New local JSON files, raw datasets, annotations, media, weights and cache state
are outside this inclusion list. Wheel runtime contents remain unchanged.

The existing package verifier derives the expected public JSON paths from Git
and checks their exact source-archive membership, size and bytes. Missing,
changed, duplicate, unsafe or nonordinary members fail verification. Extra
files under `data/` also fail, including untracked JSON beside public protocols.
Source symlinks and Windows reparse points cannot redirect these reads.
When another public protocol is added, package verification requires its
source-distribution inclusion as well.

These checks preserve existing backend wheel/source parity, frontend build and
dependency-lock checks, private-state/media exclusions and installed HTTP
verification. The manifests remain source-distribution materials; they do not
become runtime model assets or reviewed application annotations.

## Verification and remaining limits

All **50 focused package/environment tests and 4,181 full Python tests**
pass, with four optional full-suite skips. Ruff lint/format, dependency consistency,
repository UTF-8/LF/JSON/local links and whitespace checks pass. The original-base
suite passed 4,179 tests before the nonoverlapping #271 main update; the final
suite above checks the combined source. Executable/test bytes remain stable.

Actual wheel/source builds verify all 45 public manifests, 93 runtime files and
five frontend files. Two seeded generated private canaries are excluded, with
zero extra data files. A disposable locked install serves five frontend assets
and three SPA routes with authentication and owned-server cleanup. Existing
environments are preserved. The first build/HTTP consumer succeeded, then its
monitoring wrapper raced process exit before saving a complete final receipt;
that failed wrapper and original logs remain separate evidence. The corrected
wrapper passed with 24 independently terminal observed lifetimes. Final source
build and lifetime receipts, exact PR/main checks, controller integration and
independent public delivery remain tracked on the owning issue.

The repair copies or hashes already public tracked bytes for packaging only.
It interprets no scientific record and opens no original private source, label,
image, prediction or holdout. New scientific sessions and image payload bytes
remain zero. Complete scientific references remain **0/2**, with all four
eligibility flags false. Reproducible source archives and successful software
checks do not establish correct automatic annotations throughout a match.
