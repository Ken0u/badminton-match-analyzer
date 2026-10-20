# Published shuttle-coordinate supervision preparation

Owning task: [issue 143](https://github.com/Ken0u/badminton-match-analyzer/issues/143),
following [localization milestone 65](https://github.com/Ken0u/badminton-match-analyzer/issues/65)
and the negative [fixed-resolution comparison](SHUTTLE_RESOLUTION_REPORT.md).
Implementation checkpoint, October 20, 2026: no archive has been acquired or scanned yet.
This source preparation does not claim improved annotation accuracy.

The [public source manifest](../data/manifests/shuttle_supervision_sources_v1.json)
pins the separate archive supplier, creator documentation and exact download bytes.
The creator's SharePoint link currently redirects to Microsoft sign-in; no credentials
or access request were submitted. The separately supplied public archive remains a
mirror, without assumed creator authentication or dataset/media usage permissions.
Repository/model MIT does not establish dataset rights. Training, redistribution,
deployment and independent-test eligibility remain false in this task.

`scripts/prepare_shuttle_supervision.py` supplies `fetch` and `import` modes. Pin the
original root/data/weights before imports, retain the original shared Store, and use
exclusive ignored output paths. Native work must pass actual shared job admission.
Neither mode executes downloaded code, runs inference, trains or installs a model,
changes application annotations or assigns a fresh evaluation split.

The importer retains archive membership, source hashes, published raw rows and
visibility semantics, complete native PTS/geometry, unavailable cases and publication
match namespaces. Nominal FPS and score filenames never become exact source clocks,
contacts or rally boundaries. Full source identity, cross-corpus overlap, annotation
quality and appropriate future splits need independent evidence. Complete-file
checkpoints can be resumed only with a recorded terminal receipt hash, verified
consumer/runtime/source bindings, exited original process lifetime and matching
terminal shared Store registration. Interrupted artifacts are preserved.

Actual corpus, coverage and verification evidence will be recorded after the bounded
acquisition and complete source audit. Raw media, labels, archive and local receipts
remain ignored and are not supplied by a clone.

The acquisition checkpoint passes 37 generated regressions and 1,413 full-suite
tests, with four optional GPU skips. Checks include actual native VFR identity,
real shared admission, retained unknown/orphan cases, Windows ZIP original names,
exclusive interrupted writes, consumer changes during snapshot and Store admission,
and refusal to adopt another research folder or the shared cache root. Ruff,
formatting, dependency and diff checks pass. These are software checks; archive
contents, any supplied image-frame metadata and native corpus coverage remain pending.
