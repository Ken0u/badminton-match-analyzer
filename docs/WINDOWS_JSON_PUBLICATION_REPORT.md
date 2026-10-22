# Windows JSON publication repair

Issues [#186](https://github.com/Ken0u/badminton-match-analyzer/issues/186) and
[main-verification repair #190](https://github.com/Ken0u/badminton-match-analyzer/issues/190),
October 22, 2026. This is generated software evidence, not badminton annotation
accuracy or a change to application predictions, annotations or models.

## Supported failure and change

The previous `video.write_json` staged every publication at
`path.with_suffix(".tmp")` and attempted one replacement. An actual Windows
`CreateFileW` reader allowing read/write sharing but denying delete sharing
reproduces `PermissionError`, errno 13, WinError 5 when replacing a generated
destination. Both transient and persistent readers leave the old valid JSON
and the old publisher's shared temporary file.

The repaired publisher serializes before staging, owns a unique temporary file
in the destination directory, closes its stream, then atomically replaces the
destination. Only Windows errors 5, 32 and 33 permit retries: at most six attempts
with 10/20/40/80/100 ms sleeps, totaling 250 ms. This bounds application retry
sleep, not filesystem-call or operating-system scheduling latency. Persistent
access denial, including ACL denial reported as error 5, still raises the final
original exception; unrelated errors and non-Windows errors are not retried.

Failure cleanup targets only the invocation's own temporary. Serialization,
opening, writing and replacement failures preserve the previous destination.
A failed stream open closes the raw descriptor. Cleanup errors cannot mask the
publication exception; an external denial of temporary removal can therefore
leave that owned file for diagnosis. Successful replacement consumes the
temporary. Existing serializer and UTF-8 bytes remain unchanged. Concurrent
publication remains last-successful-replacement wins; this is not a transaction
or durable-storage guarantee.

## Prospective generated comparison

The protocol and executable experiment were frozen and
[published before execution](https://github.com/Ken0u/badminton-match-analyzer/issues/186#issuecomment-6331604470).
Original and candidate receipts remain separate and unchanged locally.

| Controlled case | Original publisher | Initial candidate |
| --- | --- | --- |
| Reader released after 50 ms | WinError 5; old JSON and shared temporary retained | Success in about 78 ms; only new JSON remains |
| Reader held throughout publication | WinError 5; old JSON and shared temporary retained | Final WinError 5 in about 312 ms; old JSON retained, owned temporary removed |
| Two simultaneous writers and reader | Both writers succeeded; supported complete document observed | Both writers succeeded; supported complete document observed |

The two-writer experiment did **not** demonstrate an original collision. The
shared staging name is an ownership defect visible in the implementation;
dedicated staged concurrency tests verify distinct owned files for eight writers,
complete old/new reader documents and separate same-stem destinations. Neither
the controlled sharing failure nor a later passing browser run identifies the
exact cause of #181's earlier manifest replacement failure. No actual ACLs were
changed and no external antivirus/indexer involvement was established.

Frozen SHA-256 values:

- Protocol: `163af41b3b5241a0d521847bcb2fcf488143ec2e02eb7339e61d954f825d75bf`
- Experiment: `1ef9b36b95e34f000f2cbd8e79d144303e85c809bed8cc455cac2831e55db12d`
- Original `video.py`: `fb2e759a1a1f37dd644cf0957a03a672f51adc5e6747116b175d280b4871826b`
- Initial candidate `video.py`: `b2272a9a70b4e62bb955392bc4261fb53cfde06a4fb5b28c9ef9ed1321e1b24b`

The final implementation additionally hardens descriptor/error cleanup and sorts
imports. Its exact source is bound by the submitted Git revision and subsequent
CI and delivery receipts, rather than replacing the initial comparison receipt.

## Verification and reproduction

Initial #186 local verification passes 23 dedicated tests, the complete Python suite
(2,047 passed, four optional skips), Ruff check/format across 183 files, dependency
and Git whitespace checks. Both retained production browser runs pass all 18
groups; the final run exercises the descriptor/error cleanup revision. Independent
PID/creation-time checks establish both listener and wrapper terminal for each
run. Exact-head CI, merged-main checks and delivery remain separate gates.

### Failed main verification and test correction

PR #188 merged as `01d5e2874f8366d3e6e44edfbaef00624f1a7c7e` after all 12
exact-head verification jobs passed. Fresh detached-main checks also passed 23
JSON tests and all 18 browser groups. However, the
[merged-main Windows job](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/39716528536/job/119619887983)
failed the eight-writer concurrency test with final WinError 5: 2,032 tests passed,
15 skipped and one failed. The original log and GitHub failure artifact
`12399676286` remain preserved. The controller paused ordinary work and created
#190; the earlier passing runs do not establish completed main verification or
delivery.

That test repeatedly opened ordinary Windows readers, which can deny replacement,
while requiring every writer to succeed within the fixed retry period. Bounded
retries cannot guarantee progress under continuous sharing denial. A separately
frozen generated experiment tried holding a read/write/delete-sharing handle as
a positive comparison. It failed that success expectation: the destination still
contained old JSON. Its exact publication exception was not saved, so the report
does not assign a cause. The original experiment, files, freeze and failure record
are retained rather than rerunning it until it passes.

The repair adds a **test-only** Windows guard around each snapshot open/read/close
and the native replacement call. Eight writers still stage complete, closed,
distinct temporaries concurrently. POSIX native reader/replacement overlap stays
unchanged. Windows snapshot assertions verify complete old/new JSON without
assuming replacement succeeds while a reader is open. A new controlled actual
Windows test verifies that a complete new temporary can stage while a reader
holds the old destination, then publication succeeds after that reader closes.
The original actual transient/persistent denying-reader tests are retained.
This separates concurrency/ownership from sharing-denial behavior without
skipping checks or extending production retry bounds.

The production `video.py` bytes remain unchanged at SHA-256
`ae89d139b480eeb56b3e5d98d5682d4c62b8f19ec66a4d2eb137d2c2f667cf4a`.
The [original repair freeze](https://github.com/Ken0u/badminton-match-analyzer/issues/190#issuecomment-6332043509)
and [amendment before tracked edits](https://github.com/Ken0u/badminton-match-analyzer/issues/190#issuecomment-6332062919)
retain both the failed positive-sharing assumption and the revised protocol.
Repair integration, main verification and public delivery are separate gates
recorded on #190 and #186.

Final local #190 checks pass all 24 dedicated cases, the full suite (2,048 passed,
four optional skips), Ruff check/format across 183 files, dependency and whitespace
checks, and all 18 original-venv production browser groups. The browser listener
and wrapper are independently verified terminal. These checks do not replace the
new exact-head and merged-main CI gates or the original failed-main evidence.

The dedicated generated tests cover real Windows temporary/persistent sharing
denial, deterministic concurrent writers/readers, serialization and path errors,
partial-write disk exhaustion, unrelated/non-Windows errors, bounded synthetic
5/32/33 retries, descriptor closure, primary-error preservation and owned-file
cleanup. Both actual sharing regression tests fail against an isolated copy of
the original publisher. Those failures remain in local evidence. Actual handle
tests skip on other platforms; the portable tests still exercise publication
and error classification.

Use the project's Python environment, a disposable data root and fresh pytest
temporary directories. From this task checkout:

```text
python -m pytest -q tests/test_json_publication.py --basetemp .cache/json-check-new
python -m pytest -q --basetemp .cache/project-check-new
python -m ruff check backend tests scripts
python -m ruff format --check backend tests scripts
python -m pip check
git diff --check
node tests/frontend-delivery.mjs
```

For Python tests on this workstation, the task backend is pinned in `PYTHONPATH`
because the preserved original environment has an editable installation pointing
at the original checkout. The production browser directly uses the original
`.venv/Scripts/python.exe`, without that workaround or a base-interpreter
substitution, with existing pinned Node 24.22.0, FFmpeg 8.1 and Chromium tools.
Test launchers clear GitHub, Project and OpenAI credential variables and pin
`BADMINTON_ROOT`/`BADMINTON_DATA_DIR` before application imports. No environments
were replaced and no installations or downloads were needed.

Private logs, generated media and receipts under task `.cache/` paths are not
provided by a clone. Current integration, merged-main/public-delivery evidence,
process-lifetime and cumulative output checks are recorded on the owning issue.
The consumed holdout, real media/datasets/weights and research processes are
outside this repair. Complete automatic match annotation remains unproven.
