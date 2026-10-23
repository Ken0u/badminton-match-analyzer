# Private Project state-reader repair

Owning task: [#202](https://github.com/Ken0u/badminton-match-analyzer/issues/202).
Prepared October 23, 2026. The Project is a private status dashboard;
`codex/coordination` remains the authority for ownership and integration.

## Incident and reproduction

The Contents API returned a 1,050,479-byte `state.json` as `encoding: none`
with empty content, at blob `469908320c4b96b420fa849c05e32cee0d4baa0f`.
The old reader required inline base64 and refused this response. GitHub
[documents this behavior above 1 MB](https://docs.github.com/en/rest/repos/contents#get-repository-content).
This was a reader limitation, not evidence of a credential failure.

The failed Project steps remain preserved in controller runs
[39889417252](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/39889417252),
[39889447727](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/39889447727),
[39889827486](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/39889827486)
and [39890026611](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/39890026611).
Their integration steps succeeded; the separate projection failed. Revalidation
at coordination commit `adb0ccd93fa70060135abd0ba3c7bceef9dce533` found the same
response shape for a 1,090,534-byte file, blob
`92671732fa3900b65c87c682de3b0ebf628244e7`.
Sanitized local receipts retain metadata and historical log hashes/counts;
private Project contents and credentials are not published.

## Reader behavior

The reader resolves the configured branch once, then reads that immutable
commit, its root tree and the single regular `state.json` blob. All endpoints
are constructed within the configured repository. API-provided download URLs
are unused. The [Git blobs API](https://docs.github.com/en/rest/git/blobs#get-a-blob)
provides base64 file contents independently of the Contents inline limit.

The reader verifies object identities, a complete tree, regular-file mode,
matching declared and decoded sizes, base64 encoding and the Git blob hash.
Files must be nonempty and at most 16 MiB; larger files fail explicitly before
the blob request. Encoded input is separately bounded. Invalid UTF-8/JSON,
duplicate keys, unsupported schemas and unknown or malformed statuses fail
before Project writes, with sanitized CLI errors. A branch move during a read
cannot mix two snapshots. A later ordinary projection can reflect newer state.

Existing managed-task status projection, historical-card preservation,
credential isolation and transient retries remain in place. Retries still use
the original two delays and re-inventory state/cards before writing, preserving
the ambiguous-write recovery from [#170](https://github.com/Ken0u/badminton-match-analyzer/issues/170).
There is no coordination-state mutation or history compaction.

## Verification and limits

The 81 focused tests cover small files, exact historical/current incident
sizes above 1 MiB, branch movement, malformed or mismatched object chains,
truncation, size limits, invalid JSON/schema/status and zero writes on refusal.
They also retain the existing status/history, credentials, transient exhaustion
and ambiguous-add recovery tests. These are generated software checks, not
badminton accuracy measurements.

An anonymous read of the actual public coordination branch through the repaired
reader verified the complete object chain and all 67 tasks, with four GET
requests, no account credentials and no Project access or writes. A separate
authenticated read-only baseline confirmed the configured Project remains
private; its historical-card hashes are retained locally for comparison after
trusted-controller synchronization.

The full local suite passes 2,154 tests with four optional skips. Ruff, format,
dependency health and diff checks pass. Exact PR/main CI, controller integration,
complete public package/image delivery and actual private Project parity are
tracked on the owning issue. A local passing test does not establish those
remote outcomes.
The 16 MiB application limit is deliberately below GitHub's documented 100 MB
blob limit; unsupported growth remains visible rather than silently truncating
history. No application, model, dataset or research process is changed.
