# Shuttle trails across source context boundaries

[Issue #266](https://github.com/Ken0u/badminton-match-analyzer/issues/266)
repairs misleading flight lines in the review editor. On source
`39bdbc6b5f38c3d9d3d0756e9617177de3ee14b3`, two visible observations on
consecutive frames were joined even when a camera cut, source-clock gap or
reviewed scene boundary separated them. Earlier trail segments could also
remain overlaid on a new camera view.

## Reproduction and behavior

A recording canvas executed the exact previous `Playback.draw()` body with
generated controller state. Frame 1 at native pixel `(10, 10)` and frame 2 at
`(90, 90)` produced `moveTo(10, 10); lineTo(90, 90)` in the continuous control
and in all four boundary cases: automatic cut, reviewed cut, timestamp gap and
reviewed scene start. No match footage, scientific labels or inference was
used. The original playback source SHA-256 was
`7b34baf9c26900674c7f6900fb5ed8821abf992d4b97b1c7c70bd2ab35100278`.
The local reproduction script and receipt are retained under
`.cache/goal-01a17154/`; these ignored artifacts are unavailable in a clone.

The editor now builds the recent path from observations within the current
camera, scene and time segment. It discards all history before the latest
applicable boundary, including when no observation exists on the boundary
itself. Missing, invisible and invalid coordinates break a segment. A visible
current observation still gets its native pixel marker; manual normalized
labels keep their separate marker and overlay controls retain their behavior.
No coordinates are interpolated or replaced with zero.

Camera and timestamp boundary handling is shared with court display. Current
reviewed cut additions/removals apply, while physical timestamp gaps cannot be
removed by a camera correction. Source-clock gaps use the existing frontend
threshold, greater than `max(0.1, 2.5 / fps) + 1e-8` seconds. This is boundary
detection on the timestamp table, not a replacement of native frame identity
with constant-frame-rate timing. Scene starts and exclusive ends also reset
the trail. Only the displayed 13-frame history needs an additional clock scan.

Legacy runs without boundary metadata retain continuous trails unless the
source timestamps or current annotations provide a boundary. Ordinary VFR
spacing below the existing gap threshold stays continuous. Original run
objects, saved predictions, annotations, models and processing defaults remain
unchanged. This display repair does not improve detector accuracy or certify
that camera/scene annotations are correct.

## Verification

- Twenty new generated cases cover automatic/raw/reviewed/preceding cuts,
  additions/removals, known and native-clock gaps, scene starts/ends, absent
  boundary observations, ordinary VFR and legacy continuity, invalid/missing
  positions, history length, source/run edges and unchanged inputs. All 200
  frontend tests pass, including the existing calibration and ownership tests.
- The generated editor browser matrix passes all 18 groups. Its new recording
  canvas case exercises the actual editor with continuous, camera-cut and
  scene-boundary responses. At frame 10, continuous footage retains earlier
  points and a line to `(300, 200)`; each new context draws only
  `moveTo(300, 200)`. Every case preserves the manual marker. Saved annotation
  JSON and original prediction-file hashes are unchanged.
- Type checks, backend OpenAPI contract parity, production build, staged asset
  parity, Ruff lint/format, dependency consistency, repository text/JSON/local
  links and whitespace checks pass. The first type check found an unused import;
  it was removed. An initial contract command lacked the explicit existing
  interpreter setting; selecting it allowed the unchanged contract to pass.
  Those failed attempts remain in the execution evidence.
- The initial full Python run finished with 3,826 passed, four skipped and eight
  failures in generated native-stub cases. Their deeply nested pending artifact
  filenames exceeded Windows path limits. No inference or real model ran.
  Extended-length paths also conflicted with SQLite URI parsing; a shorter
  system temporary directory lacked Git-ignored ancestry, while shorter folder
  names within this checkout were still insufficient. These attempts and an
  initial local-runner import-path collection error remain preserved.
  A disposable local runner uses short, uniquely numbered pytest temporary
  folders inside a fresh system-temp Git repository with a real ignore rule.
  It retains the actual Git checks and all assertions, restores the working
  directory import behavior of `python -m pytest`, and changes no tracked test
  or application code. All 102 cases in the two affected modules pass there.
  The complete unchanged suite then passes: **3,834 passed, four skipped**, in
  409.25 seconds, with one existing Starlette/httpx deprecation warning.

Browser receipts are retained under
`.cache/w266/.cache/evidence/frontend-editor-iVWEIF/`. They include the frozen
protocol/source hashes, generated case results, performance measurements and
fixture/static-server cleanup observations. Python logs are preserved in
`.cache/w266/.cache/pytest266*.log`; the local runner is
`.cache/goal-01a17154/short_tmp_pytest.py`. Those ignored files are local evidence,
not clone dependencies. Full Python checks and hosted integration/delivery are
recorded on the owning issue as they complete.

Software verification here concerns overlay continuity. Full-match automatic
annotation accuracy, exhaustive independently adjudicated contacts and
persistent identity remain separate release requirements. No new scientific
reference, data/model eligibility or deployment claim follows from this repair.
