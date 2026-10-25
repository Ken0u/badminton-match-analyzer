# Bug review and implementation progress

The [native-clock evaluation repair](EVALUATION_CLOCK_REPORT.md) addresses a
generated API/CLI failure in which a frame-5 proposal claims frame 15's time and
receives contact and drive-classification F1 1.0. Contact and recognition
evaluation now compare declared representative and optional interval times to
the registered native source clock before scoring. Invalid clocks or inconsistent
times are rejected; compatible pure calls without a clock report unavailable
validation. All 650 focused and 3,834 full Python tests pass, with four optional
skips, plus Ruff lint/format, dependencies, repository and whitespace checks.
Final executable/test bytes remained unchanged and recorded process lifetimes
were checked after exit. Final review also restored source-hash rejection before
clock parsing; the first verification round and temporary draft fence remain
recorded. Scientific complete references remain 0/2; this protects software
measurements without establishing full-match annotation accuracy.

The [evaluation source-hash repair](EVALUATION_SOURCE_REPORT.md) rejects
contact and shuttle artifacts whose explicit source hash conflicts with the
registered video or is malformed. Generated API/CLI reproductions previously
scored these artifacts at F1 1.0. Legacy artifacts without a hash remain usable
with explicit unavailable provenance; valid matches keep their metrics and
denominators. All 328 focused checks pass, including existing camera, recognition
and rally evaluation tests. Final verification passes 3,393 Python tests with
four optional skips, plus Ruff lint/format, dependencies, repository and whitespace
checks. The initial fixture setup and pre-pytest formatting failures are preserved.
Scientific complete references remain 0/2; this validates software provenance,
without establishing annotation accuracy.

The [contact evaluation context repair](CONTACT_EVALUATION_CONTEXT_REPORT.md)
corrects a generated frame-19/frame-20 match across a known camera cut that
previously reported contact F1 1.0 and credited recognition family/hitter/complete
events. Evaluation now separates known camera views, retains missed/false
denominators and explicitly excludes proposal intervals or evidence crossing
cuts or review gaps. Recognition uses the same eligible IDs so exclusions cannot
reappear as false classifications. Generated verification and the remaining
scientific-reference limits are recorded in the report. Final local checks pass
3,343 Python tests (four optional skips), including 139 focused tests, plus Ruff,
formatting, dependencies, repository and whitespace checks. The first full run's
source-timing limitation and initial CLI-fixture assertion failure are preserved;
the final run verified unchanged source and terminal process lifetimes.

The [saved boundary evaluator](RALLY_EVALUATION_REPORT.md) adds separately
declared serve/ending review coverage and guards against treating contact
completeness or uncertain boundary intervals as exact timing truth. It binds
saved proposals to source clocks and current context, keeps gaps/cuts separate,
preserves exclusions and distinguishes representative-time scores from possible
interval support. The editor includes rally inputs in report ownership and
clears obsolete results/downloads without another evaluation request. Generated
verification includes 114 pure evaluator and 25 API/CLI cases; final full
verification passed 3,240 Python tests (four optional skips), 180 frontend tests
and all 17 generated editor browser groups. Entry-point review also reproduced
an absent shared video ID escaping as a key error and an identical numeric hash
being accepted; explicit identity/digest validation and 14 regressions correct
both cases. Final verification includes these added cases, with complete cleanup.
Type/contract/build/stage, Ruff, formatting, dependencies and repository checks
pass. Scientific limits are recorded in the report; no new source assessment,
inference or model promotion is involved.

Current status reviewed October 24, 2026 (UTC). Historical measurements and failures remain below; their test counts describe those increments, not today's suite.

The application, React review/export tools and resumable full-source processing are delivered. Automatic full-match annotation correctness remains unproven. [Both host pilots and active rollout](https://github.com/Ken0u/badminton-match-analyzer/issues/80#issuecomment-6268644934) are complete, using GitHub Free controller enforcement. Candidates match the public repository; the Project stays private. [Latest verified assessment delivery](https://github.com/Ken0u/badminton-match-analyzer/issues/242#issuecomment-6389782093) covers source `9668be831014820e0a4e620f3c277032a04a39c5`, all 12 exact PR/main jobs on first attempts, 89 runtime files with package/source/frontend/lock parity and both anonymous public image manifests/configs. Descriptor HEAD availability does not prove image layer bytes, runtime behavior or image/source parity. Nothing automatically upgrades a running app or certifies badminton accuracy.

## Current failures and verified repairs

| Finding | Evidence and resulting status |
| --- | --- |
| A replacement analysis could retain provisional actor hints after its identity result disappeared. | Generated reproductions in [#254](https://github.com/Ken0u/badminton-match-analyzer/issues/254) load an identity-linked analysis, then a replacement with absent or empty identity metadata while reusing a player run. The previous actor label remained eligible for the overlay. Actor hints now derive from the current successful identity response and clear when no usable identity run is supplied or its context is stale. Valid current results, stable polls, reviewed assignments and source/view ownership remain intact. All 174 frontend tests pass, including missing/stale identity results, valid replacements and delayed success/error across source/view changes; type, contract, production-build and staged-asset checks pass. The first generated browser run timed out at initial navigation before editor interaction. A minimal local comparison received zero requests inside the network sandbox and loaded in 178 ms outside it; original failure and terminal-process evidence remain preserved. Full checks, the unchanged browser suite with local network access, exact PR/main CI and public delivery are recorded on the owning issue. This repairs provisional display state; it does not change identity matching or establish identity accuracy. |
| The editor could display and download an evaluation for obsolete input runs or another analysis window. | Three generated reproductions in [#252](https://github.com/Ken0u/badminton-match-analyzer/issues/252) retain the old report after a completed shuttle-run replacement, a delayed evaluation response following replacement, and a seek into another analysis core. Reports now belong to the selected source, saved annotation revision, current review view and evaluated contact/shuttle/recognition runs. Input, draft or view changes clear completed reports and fence late responses, including transports that ignore cancellation and inputs that change away and back. Mismatched response source/revision/run identities are rejected. Identical polling, unrelated run changes and ordinary same-core frame ticks retain valid reports; evaluation POSTs are never retried automatically. All 161 frontend tests and 17 generated editor browser groups pass, including removal of an obsolete report and download without another POST. Full verification passes 3,101 Python tests with four optional skips, type/contract/build/stage, Ruff, formatting, dependency and repository checks. The first browser attempt exposed an unchanged test oracle that arbitrarily chose red over green for yellow; decoded RGB 217/218/28 reproduced its failure. After an accepted path reservation, the test checks both yellow channels above blue and rejects swapped or incorrect colors while retaining orientation, proxy tolerance, PTS and geometry checks. Original failed artifacts and independently verified terminal fixture lifetimes remain preserved. This repairs report ownership and a generated test oracle; backend metrics, annotation truth and model accuracy remain unchanged. Exact PR/main checks and public delivery are tracked on the owning issue. |
| A transient job-list failure stopped polling known active media exports indefinitely. | Generated fake-timer regressions in [#248](https://github.com/Ken0u/badminton-match-analyzer/issues/248) reproduce the lost timer after both a network failure and HTTP 503. Known queued/running cards now retain their state and permit at most three additional GET list reads per consecutive retryable episode at the existing polling interval. A current successful read resets that budget and clears its own read error while preserving failed-start and saved-revision/dirty/saving errors. Manual Refresh remains available; POSTs are never retried. Authentication/client/conflict, malformed/protocol and cancelled reads stop automatic recovery. Selection, overlapping reads, pending starts, disposal and download validation remain fenced. All 49 export regressions and 123 frontend unit tests pass, together with type, contract, production build and staged-asset checks. The generated export browser suite also passes after its admission fixture reuses the existing process-ownership verifier for Windows venv launcher/worker lifetimes; the first failed attempt and its independently verified terminal processes remain preserved. These are software checks, not badminton accuracy measurements. |
| Same-size replacements with preserved modification times could bypass source, clock and playback cache invalidation. | Generated-only reproduction in [#243](https://github.com/Ken0u/badminton-match-analyzer/issues/243) accepted changed source bytes, returned stale timestamps and reused a changed proxy's old hash. Reads now bind bounded cache entries to opened-file identity and change metadata, verify the pathname and metadata again, and reject observable concurrent changes. Windows requires handle ChangeTime plus an independently queried [file-journal USN](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-fsctl_read_file_usn_data); unavailable metadata disables reuse and verifies the result with a second read. Handle observations are compared with a newly opened pathname handle, avoiding Python 3.12 Windows path/handle ctime differences. The first PR revision failed hosted Windows CI: rapid writes retained identical ChangeTime and valid generated media encountered the ctime mismatch. Those failures are preserved; the repaired revision adds journal/fallback and metadata-comparison regressions. Regressions cover replacement, in-place edits with restored timestamps, unchanged-file reuse, unavailable metadata, concurrent readers and actual generated playback invalidation. This depends on the filesystem reporting changes; it does not certify annotation accuracy or detect changes hidden from filesystem metadata. Existing research images, labels and predictions remain untouched; [#243 completion](https://github.com/Ken0u/badminton-match-analyzer/issues/243#issuecomment-6388278334) verifies exact PR/main checks and public delivery. |
| Shuttle component recall remains inadequate. | [Source visibility audit](SHUTTLE_VISIBILITY_REPORT.md): 14/25 known visible cases localized, 10 missed and 1 displaced; 7 negatives include 3 false observations, and 28 unknowns remain in the 60-case cohort. [Higher resolution](SHUTTLE_RESOLUTION_REPORT.md) still localizes 14/25 and is rejected. [Heatmap capture](SHUTTLE_HEATMAP_REPORT.md) reproduces the baseline without changing its threshold/default. Eleven visible cases have no agreeing observed component; selection alone cannot fix them. |
| A lower component threshold adds distractors as well as recovered locations. | The [fixed 0.25 experiment](SHUTTLE_THRESHOLD_REPORT.md) increases selected localization from 14/25 to 17/25, displaced visible outputs from 1/25 to 2/25 and false observations from 3/7 to 4/7. It fails the frozen disposition rule and is rejected. All 60 cases and 28 unknowns remain; the application stays at 0.5 with no second cutoff, relabeling or model promotion. |
| Familiar-corpus agreement does not resolve development failures. | [Supervision preparation](SHUTTLE_SUPERVISION_REPORT.md) retains 201 clips / 91,214 rows / 91,579 frames. [Fixed diagnostic](SHUTTLE_CORPUS_DIAGNOSTIC_REPORT.md) localization F1 is 0.975836 on 78,979 eligible published rows, with 12,235 incomplete-file rows quarantined and 365 unlabelled tail frames retained. Exact upstream/pretraining membership, original-match overlap and dataset/media rights remain unresolved; familiar-source agreement does not establish independent truth or deployment eligibility. Training-ready rows remain zero. |
| Upstream byte/ordinal accounting is complete; native correspondence remains unresolved. | [Actual #220 comparison](SHUTTLE_LABEL_REVISION_REPORT.md) verifies 29 immutable corrected objects against the preserved archive: 29 literal cases / 12,656 records per side, matching raw ordinal sets and 29 unequal byte strings. Byte inequality does not prove numeric changes or corrected truth. All native comparisons remain unscored with null bases and inherited quarantine. Three shared archive/upstream `2_` names still conflict with the creator's `1_` inventory; no aliases were guessed. The pinned correction UI's visibility inversion is a source-code concern, not proof about affected rows; no labels were inverted. Source/media rights, independent native identity/clock binding, original-match overlap and checkpoint membership remain unresolved. The [eligibility audit](SHUTTLE_ELIGIBILITY_REPORT.md) remains applicable: all four flags false and zero training-ready rows. [Completed delivery](https://github.com/Ken0u/badminton-match-analyzer/issues/220#issuecomment-6385528052) does not resolve those scientific limits. |
| Additional broadcast evidence confirms missing/displaced outputs. | [Source assessment](SHUTTLE_SOURCE_ASSESSMENT_REPORT.md) completes 128 centers and 80 required adjudications; incomplete #163/#164 attempts remain preserved. [Unchanged-tracker diagnostic](SHUTTLE_BROADCAST_BASELINE_REPORT.md) completes 128 windows / 8,192 rows. Of 37 localizable references, 16 agree, 6 are displaced and 15 missing; 1 unlocalizable, 5 negatives and 85 unknowns stay distinct. All outputs are available; the five negatives have no false observations. Agent agreement and center-only scenes do not establish expert labels, continuous live context or independent accuracy. All four research eligibility flags remain false. |
| Complete source inspection still leaves contacts and rally boundaries unresolved. | The [completed rally assessment](COMPLETE_RALLY_REFERENCE_REPORT.md) retains both sources and all 1,532 native frames, with 512 original successes and 256/256 validated targeted references including 21/21 recovery sessions. Target-frame coverage is 991/991 singles and 541/541 doubles. Unchanged acceptance returns **0/2 complete references** and **0/2 fully supported observed-contact label slots**. Singles retains overlapping contacts; both retain unresolved source evidence and unsupported opening/terminal boundaries. Unknowns, earlier failed outputs/clocks and all four false eligibility flags remain. #62/#66/#67/#71 stay incomplete; completed software delivery authorizes no further image pass, weaker criterion or accuracy claim. |
| Repeated mentions and conflicting source judgments cannot certify physical contacts. | [Delivered #238 diagnostics](RALLY_REFERENCE_DIAGNOSTICS_REPORT.md) preserve every native frame and occurrence variant without new source assessment. Singles adjudication records 47 occurrences / 45 distinct signatures, including two repeated signatures and one overlapping pair of distinct contact keys; deduplication does not resolve that pair. Singles lacks a terminal event; doubles lacks a serve and has only a stopped-play ending. Every adjudicated contact occurrence lacks locally supported actor identity. No label or scientific acceptance was changed; references remain 0/2. |
| Sparse scene agreement leaves native contact and continuous identity evidence missing. | [Completed #242 context readings](RALLY_TEMPORAL_CONTEXT_REPORT.md) use six fresh sessions / 34,040,436 new image bytes on five unchanged galleries, with zero replacement or retry. Known A/B scene equality is 32/34 singles and 18/19 doubles samples. Unknowns and unresolved actor transitions remain; all 1,479 unsampled native frames remain unreviewed in this sparse pilot, separate from the earlier exhaustive assessment. Same-model agreement is not expert truth or accuracy. No exact contact, precise boundary, continuous identity, family/side or complete-reference claim follows; 0/2 references and all four false flags remain. This completed allowance authorizes no new image pass. |
| Sparse player evidence exposes motion/occlusion misses and extras. | [Mac CPU runtime](MAC_PLAYER_RUNTIME_REPORT.md) runs both installed models on 50 frames each without selecting a winner. [Source audit](MAC_PLAYER_AUDIT_REPORT.md) matches 20/22 people against 23 predictions over 11 frames; 2 people and 3 predictions are unmatched. Fourteen eligible sampled transitions retain IDs; 10 ineligible transitions are retained. Independent automated assessments are not human gold labels; unsampled switches, doubles and cross-camera identity remain open. [Final integration/delivery receipt](https://github.com/Ken0u/badminton-match-analyzer/issues/183#issuecomment-6328133046) supersedes the report's pending final checks. |
| Native playback failure could strand a pending exact-frame seek. | [Exact-frame recovery](EXACT_FRAME_RECOVERY_REPORT.md) is integrated and [delivered](https://github.com/Ken0u/badminton-match-analyzer/issues/158#issuecomment-6306464552). It handles the pending seek and retains an already loaded exact image after a failed Play. The earlier passing CI retry did not itself fix this product bug. |
| A completed import could remain absent after a failed or superseded library read. | The [#215 / PR #217 repair](https://github.com/Ken0u/badminton-match-analyzer/issues/215) is delivered at `3fb8d80a88e016f673a688795b01c97ca1403fe3`. Only a successfully committed current library read acknowledges the import fingerprint; failed or superseded reads leave the refresh pending for polling. Generated race/read-failure checks and exact PR/main/public delivery pass. This repairs library synchronization, not annotation accuracy. |
| A Windows venv wrapper could be confused with its server lifetime. | [Fixture ownership repair](FRONTEND_FIXTURE_PROCESS_REPORT.md) authenticates the listener and verified descendants, checking identity before every signal and preserving cleanup receipts. [Completion](https://github.com/Ken0u/badminton-match-analyzer/issues/181#issuecomment-6331555600) verifies original-venv browser checks, merged main and public delivery. |
| JSON staging ownership and Windows sharing require distinct handling. | [Publisher/report](WINDOWS_JSON_PUBLICATION_REPORT.md) uses owned same-directory temporaries and narrowly bounded retries. Original #186 main failed a Windows concurrency test because repeated readers could deny replacement beyond that bound. #190 repairs only the test assumption; production retry limits remain unchanged. Its prospective share7 comparison also failed and its exact error remains unknown. Both failures remain preserved in the [repair handoff](https://github.com/Ken0u/badminton-match-analyzer/issues/190#issuecomment-6332507417). |
| Linux fixture shutdown observation could reject metadata loss before reaping. | [Subsequent repair](FRONTEND_FIXTURE_PROCESS_REPORT.md#subsequent-shutdown-observation-repair-192) reproduces this observation gap on frozen generated records, retains structured observations and separates shutdown polling from full signal authorization. [#192 completion](https://github.com/Ken0u/badminton-match-analyzer/issues/192#issuecomment-6353942809) verifies all 12 main jobs and public delivery; fresh actual Linux receipts pass all 18/8/13 browser groups and independently observe three original lifetimes absent. Original historical mismatches and their unknown terminal states/causes remain preserved; this reproduction does not establish their cause. The standalone POSIX process regression is not invoked by current CI. |
| Live status could accompany empty shutdown metadata; an empty cwd could resolve to the observer directory. | [#197 follow-up](FRONTEND_FIXTURE_PROCESS_REPORT.md#incomplete-live-status-observations-197) allows bounded observation of the matching authenticated lifetime while rejecting malformed or conflicting fields. Complete fresh identity remains required for every signal, and empty paths cannot authorize escalation. The frozen comparison improves from 12/18 to 18/18; 72 local process tests pass with one POSIX-only skip. All 12 PR/main jobs and public delivery pass on first attempts. New Linux receipts prove complete cleanup but did not naturally repeat the live-status shape; the original hosted lifetime remains unknown. |
| Slow Ubuntu package downloads exhausted the repaired main's job limit. | #192's Python 3.10 and browser jobs timed out during system-package installation before their tests/fixtures started; nine other main jobs passed and the dependent gate failed. One explicitly authorized unchanged-source failed-job retry passed all 12 jobs. [Incident #195](https://github.com/Ken0u/badminton-match-analyzer/issues/195#issuecomment-6353942996) is closed, public delivery is verified and the queue resumed through its documented request. Original logs remain preserved; checks, timeouts and retry policy were unchanged. |
| Repeated Ubuntu package downloads blocked documentation CI before project tests. | [CI bootstrap repair](CI_BOOTSTRAP_REPORT.md) validates and preserves signed Ubuntu sources, routes recognized runner/Azure URIs through the official HTTPS archive, probes native tools/libraries and installs missing original packages only. All 12 PR/main jobs pass first attempt; codec preparation takes 22–36s in these runs. [Complete delivery](https://github.com/Ken0u/badminton-match-analyzer/issues/200#issuecomment-6356150840) verifies source `0eaad954a7d58ead646973eda02a8401c2f78351`. Both original documentation-PR attempts remain preserved; no historical cause or general speed guarantee is inferred. Checks, timeouts, retries and policy are unchanged. |
| Project projection rejected coordination state above the Contents API inline limit. | [Delivered repair #202 / PR #206](https://github.com/Ken0u/badminton-match-analyzer/issues/202) preserves the original 1,050,479-byte failure (`encoding:none`, empty inline content) and reads large state through verified Git blobs. Source `38af56364dace02b0762a325bd71dee376b27c78` passed exact PR/main CI and complete public delivery. Its final projection audit matches all 67 then-managed statuses, preserves all 33 historical cards and keeps the Project private. Historical failures remain preserved; the dashboard is never an ownership grant. |

The #242 implementation passed 459 focused and 2,941 full local tests with four optional skips, required static/dependency checks and all 12 exact PR/main verification jobs; its [completion receipt](https://github.com/Ken0u/badminton-match-analyzer/issues/242#issuecomment-6389782093) verifies delivery separately. Its fixed epoch-type and frozen-subprocess-import bugs have generated regressions; this does not establish scientific label quality. Earlier interrupted tests and failed attempts remain preserved. The [current project plan](../PROJECT_PLAN.md#current-evidence-and-remaining-work) next requires a separately frozen temporal/native contact, actor and boundary review, and supported source/clock correspondence plus applicable usage/provenance. Only then can eligible shuttle, identity, doubles and unseen complete-event/correction-time evaluations proceed; #62/#65/#66/#67/#68/#71 remain incomplete. No research is recomputed, no consumed holdout is reopened and no model is promoted by this documentation update.

## Earlier audits and their dated evidence

The October 19 [frozen holdout recovery](HOLDOUT_RECOVERY_REPORT.md) fixes unsafe one-shot restart assumptions after 67 completed rally input chains. The resumable CLI preserves original receipts and ordinal 67's player run, verifies native recipe/source context, uses real shared admission and completes all 75 audited inputs before frozen CPU heads. Independent preflight caught incomplete saved-summary metric checks and missing between-rally input revalidation; corruption/change regressions cover both repairs. Actual full-source execution retains 860 rows / 677 eligible per task. R3 strict conditional family/side accuracy is 0.421 without confidence abstention and 0.143 with unchanged validation thresholds; requested-family failures prevent promotion. Software checks pass (950 tests / four optional skips, plus all 12 implementation-head CI checks); they do not establish annotation accuracy.

The [autonomous DevOps review](AUTONOMOUS_DEVOPS_REPORT.md) adds atomic task/resource reservations, stale ownership/review fencing, journalled merge recovery, failed-main repair and private publishing completion checks. Independent review found gaps in cross-host recovery, malformed-command handling, closed task eligibility, Windows executable resolution and privileged-entry-point classification; focused regressions cover their fixes. GitHub Free uses controller-enforced CI/review/conversation checks without requiring paid branch protections; GitHub cannot prevent direct writes or manual bypasses. Its original bootstrap checkpoint awaited owner credentials and pilot activation; the verified current active state is recorded above. These software checks do not establish badminton accuracy.

The [direct-video learner review](VISUAL_EVENT_LEARNING_REPORT.md) checks source clock/cut isolation, missing context, changed cache receipts, mixed encoder runtimes, held-out normalization leakage and altered validation selections. Generated-data tests verify fast/window equivalence and refuse changed weights or thresholds. Runtime inspection caught a copied research launcher using an isolated default data root; the existing worker was adopted into the real app's job lock without re-inference. All 800 source caches and the camera refactor now pass independent integrity/equivalence audits. The fixed 100-epoch experiment and 200-clip test are complete; independently recomputed contact F1 0.159 and full tuple F1 0.028 expose severe recognition/generalization failures. No model is promoted. The software suite remains 707 passed / four optional GPU skips; those tests do not establish annotation accuracy.

The [follow-up source audit](FOLLOWUP_SUPERVISION_REPORT.md) identifies conflicting family labels, inferred results inside annotation containers, missing time fields, retained flawed rows and known cross-corpus match overlaps. These sources remain separate from the completed RGB experiment. All 75 original ShuttleSet holdout clips are recovered and clock-verified. Review of all 26 detected cuts finds close-ups and lingering wipes: a cut does not certify an immediately usable live-court view. The [subsequent frozen evaluation](HOLDOUT_RECOVERY_REPORT.md) is complete with unsupported cases retained; its recognition failures and conditional source assumptions remain explicit.

The [AI CUP contact-supervision audit](AICUP_CONTACT_SUPERVISION_REPORT.md)
identifies a different 1/2 backhand convention, numbered clips lacking original
match IDs and incomplete preprocessing in a published visual detector. The new
importer retains contact ordinals and unknown alignment/splits, verifies all
media/label bytes and rejects archive/source conflicts before writing an index.
Review also caught a missing-frame value hiding a reversal between the known
contacts on either side; that full sequence is now quarantined and regression-tested.
It imports all 7,845 published contacts and preserves 169 unlabelled clips.
687 Python regressions pass with four optional GPU skips; existing saved events
and model predictions remain unchanged. Broader aligned supervision is now
available for the next model improvement; this is not improved detector accuracy.

The [player tracking study](PLAYER_TRACKING_RECOVERY_REPORT.md) catches our
detector gate disabling weak association, but also rejects the direct fix after
new source breaks and rejects a motion-tracker replacement after a doubles ID
swap. The current candidate corroborates short joins while retaining baseline
observations and rejecting conflicting branches. It also invalidates remote
identity evidence after scene edits, restoring baseline IDs before reviewed
names are applied. Native and regression evidence is recorded in the report;
complete player identity remains unproven.

The [actor-continuity work](ACTOR_CONTINUITY_REPORT.md) removes automatic-ID
discontinuity at overlapping processing windows. Co-present tracks cannot merge,
ambiguous correspondence stays unresolved and camera cuts remain separate.
Review caught a gap leak in the new hints; exact eligible observation ranges now
prevent labels appearing over weak or excluded frames. The UI also replaces its
own stale queued notice on completion while preserving newer messages. Full
regression passes 633 tests with four optional GPU skips; generated and cached
native browser checks pass. Verified person identity across cuts remains open.

The [FineBadminton source audit](FINEBADMINTON_REPORT.md) catches a misleading
`kill` translation, contact-frame fields omitted from the larger release and
one side label missing from that release. The adapter verifies both publications,
keeps action intervals separate from contact times, and preserves omissions and
malformed rows. Native inputs and a controlled training comparison are recorded;
the new model fails the promotion comparison and remains outside the app.
All 611 standard checks pass, with four optional GPU skips; the packaged CLI
also reproduces the complete normalized index.

The [full-match processing work](FULL_MATCH_PROCESSING_REPORT.md) fixes cancellation
being lost to older progress snapshots and preceding detected cuts disappearing
at new processing windows. Cached native output now requires complete source
frame/PTS coverage, and damaged checkpoint bytes cannot be silently reused.
Generated interruption, registration-recovery, context and ownership checks pass.
Both complete supplied videos now pass CUDA processing and independent checks
of all 92 registered artifacts. A cache-only resume reuses every stage without
importing Torch or changing artifact bytes or annotations; native browser review
passes for singles and doubles. These are coverage and integrity checks, not
full annotation accuracy.

The [automatic court increment](AUTOMATIC_COURT_REPORT.md) removes the manual-corner
dependency for supported visible courts and fixes stale court filtering being
reused for contact/recognition suggestions. Current manual edits invalidate
affected inputs and new saved proposals; geometry is never auto-saved as reviewed
truth. Actual CUDA checks retain unknown closeup geometry and reset at cuts.
581 tests pass with four optional GPU skips; development evidence does not
establish unseen or full-match correctness.

The [finite-wrist correction](FINITE_WRIST_REPORT.md) fixes a reproduced NaN
distance bypass that could propose a contact despite a distant player box.
Coordinates and confidence must now be finite before supplying wrist evidence;
missing/invalid wrists retain the existing appropriate fallback. Ten generated
regressions cover the failure and valid other-arm behavior. Six complete native
candidate lists and an actual cached-input API check remain unchanged, with no
saved-label edits. This numerical fix does not establish full contact accuracy.

The [observed-flight study](OBSERVED_STROKE_CONTEXT_REPORT.md) adds source-guarded
stroke context and fixes an input-aliasing bug that could mix later court/video
edits with earlier body features. A 60 fps regression also verifies lineage from
additional flight samples. All 1,270 retained default vectors match the frozen
experiment exactly. Validation family F1 improves modestly, but joint recognition
and several families still fail; no new model is installed. The independent
source has a red court and a source-verified cut at 24, so previous green-only
research assumptions are explicitly inapplicable. The later public-media recovery
and [frozen full-source scoring](HOLDOUT_RECOVERY_REPORT.md) are complete; conditional
recognition failures remain explicit and no model is promoted.

The [first raw-video learning evaluation](R2_LEARNING_REPORT.md) has completed
all 203 corrected native cases and both frozen held-out learners. Contact weak
F1 is 0.790, while conditional family macro F1 is 0.498; drop, net, drive and
clear remain concrete failures. Validation abstention precision also does not
transfer uniformly. Neither learner is installed as the default. Source-control
evaluation correctly rejected old player artifacts missing source provenance;
fresh source-hashed small-pose controls complete without bypassing that guard
or changing saved annotations. Future tuning needs another source holdout.

The October 18 [wrist-reach regression](WRIST_REACH_REPORT.md) removes a
source-inspected floor-bounce proposal that player-box proximity incorrectly
supported despite repeated distant wrists. Both arms need complete temporal
evidence before excluding a hitter; missing pose preserves the fallback and
other players remain eligible. Five cached comparison excerpts are unchanged,
and the real cached-input API preserves saved labels. This is a development
negative control, not full contact accuracy. The shared feature-preparation
banner also no longer incorrectly describes every preparation job as side-model
training.

An October 18 source audit found a real close-up-to-court edit at frame 14 that
the detector suppressed during startup. The corrected scanner and a real CUDA
rerun now separate tracker IDs, calibration and shuttle context at that cut.
Temporal descriptors also include velocity lookback and transitive component
history in their evidence ranges. [The camera-context report](EARLY_CAMERA_CUT_REPORT.md)
records the regression checks and source review. Model trainers stopped before
using the affected inputs; corrected extraction is running with verified reuse.

The terminal-action increment removes an incorrect in-court-only ending gate:
a true shuttle can settle beside a sideline. The bounded surround retains every
existing motion, visibility and quiet-player requirement. The public development
excerpt now proposes end 319 [316,330], with line call and exact landing unverified;
original first views and partial pilots are unchanged. [The report](TERMINAL_ACTION_REPORT.md)
records 481 passing standard tests, real cached-input API and generated browser
checks. Missing contacts, faults and the original doubles ending remain open.

The shuttle-selection increment fixes a verified jump to a stationary court-logo
component even though the true shuttle is present as a smaller observed blob.
Source-time reachability selects a unique plausible alternative while retaining
all raw component evidence. Full transitive history now controls scene exclusions
and downstream contact/rally/recognition inputs. [The report](SHUTTLE_LOCALIZATION_REPORT.md)
records the 353-to-1-pixel development example, unchanged original excerpts,
460 passing standard tests, a real GPU API check and generated browser coverage.
The missing contacts and outside-sideline ending remain open.

The contact-timing increment fixes a sampled-frame assumption that rejected
between-frame transitions, and short gaps no longer require consecutive immediate
observations on both sides. Profiled proposals carry uncertain timing and leave
ambiguous hitters unknown. [The report](SUBFRAME_CONTACT_REPORT.md) records actual
one-to-six public-rally output, controlled negatives, remaining misses and the
unvalidated accuracy limits. Source/scene guards also cover complete evidence
windows in the editor, recognition and evaluation. Excluded context does not
erase valid gold events from metrics. 439 standard tests pass, plus real-sample
and generated-media browser checks; no reviewed main labels were changed.

The doubles source audit found a concrete normalization bug: a one-stroke serve
fault carries terminal phase 3, but the existing importer rejected that serve.
Mapping version 2 preserves the serve and terminal roles, recovering 17 otherwise
eligible ShuttleSet rows without changing old indices or models. The new doubles
importer also handles nine such rows and preserves unknown timing/side semantics.
[The audit](S2_DOUBLES_REPORT.md) records the pinned labels and an actual public
source excerpt. At that increment, v2 native contact inference found only one
proposal against 13 published references; timing is not yet adjudicated. Missing
observations and the abrupt-fit gate are concrete next targets, alongside out-shot endings.
Current checks: 400 standard tests passed with four unchanged opt-in GPU tests
skipped, plus actual CUDA processing of the new 390-frame source excerpt and
both real label-import CLI paths. The new wheel preserves existing tracking,
decoder and model-asset bytes; source/mapping/split overwrite guards are tested.

The rally increment adds experimental serve/end proposals and pinned standard/
lightweight pose selection. [The report](RALLY_PROPOSAL_REPORT.md) records actual
outputs and missing boundaries. A variable-rate timing regression caught a
pose-lag lookup that shortened quiet-motion windows; source PTS now controls the
lag. Isolated shuttle jumps cannot supply sustained launch evidence. Scene,
camera and court edits invalidate proposal context, including unsaved drafts;
new player runs preserve court snapshots and reject stale geometry. Current
checks:379 standard tests passed,4 optional CUDA checks passed separately,
plus generated-media boundary browser checks. Real labels remain unchanged.

The preceding native run found a decoder-shutdown deadlock after its final frame.
Two native traces confirmed a main thread waiting for FFmpeg teardown while a
decoder worker waited for the Python logging callback's GIL. Torchvision can
install that callback during lazy initialization. Managed media contexts now
restore FFmpeg's native callback before opening/closing; player tracking finishes
vision-library initialization before any decoder starts. This preserves threaded
source decoding and prevents this callback/teardown cycle.

[The decoder report](DECODER_SHUTDOWN_REPORT.md) records the reproduced failure,
completed 114-frame CUDA rerun, and actual full-view perception findings. Current
checks: **340 standard tests passed**, two optional GPU tests skipped and passed
separately, plus fresh generated-media browser checks. Native diagnostic/error
behavior and repeated threaded seek/early-close have bounded subprocess
regressions. The opt-in recognition fixture now compares candidate IDs/counts
with actual in-range shot targets, preserving newly saved serves/endings.

The latest source audit exposed an annotation gap: an occluded rally ending could
only be saved as an exact frame plus free-text notes. The editor and contract now
preserve separate inclusive terminal bounds for rally endings. Those bounds
survive reload, edits, history, and JSON/CSV export; invalid/mixed contact and
terminal intervals are rejected. Changing event kind clears draft timing so a
racket-contact interval cannot silently become terminal timing.

[The boundary report](RALLY_BOUNDARY_REPORT.md) records four source-only opening/
ending intervals, with unresolved timing and human adjudication pending. It does
not certify every intervening contact or an automatic rally detector. Current
standard checks: **338 tests passed**, with the two optional CUDA checks skipped;
this increment changes annotation contracts/UI and no model inference math.
Generated-media browser checks exercise terminal add/reload/clear/history/kind
changes and duplicate-import preservation.

The reviewed-scene increment adds editable camera corrections and half-open
live/replay/non-play/unknown ranges. [The scene report](SCENE_REVIEW_REPORT.md)
records the source-verified 250-frame intro review and an isolated real CUDA
override probe. Raw model artifacts and reviewed events remain intact. Changed
effective boundaries require new tracking; masked scenes suppress contact and
recognition suggestions and conflicting exhaustive evaluation windows.

The bug review fixed two reversible-view issues: applying a review twice could
clear an already-stale tracking flag, and removing a scene override could discard
the original scene evidence. Staleness now remains latched until tracking is
rerun, and removing an override restores its original scene value. Benchmark
helpers now use the same scene masks and stale-input guards as the app. Browser
fixtures regenerate proposals to avoid depending on a previous test's filters.

Current standard checks: **329 backend tests passed**, two opt-in GPU tests
skipped and passed separately. Camera/scene browser checks cover draft masks,
overlap validation, save/history/export preservation, stale-input rejection,
and editing/removing corrections. The source scenes are a first visual pass,
not adjudicated event truth. Automatic live/replay classification, full-rally
evaluation, and full-match correctness remain unproven.

The preceding increment adds queued full-video camera scans and separates new
tracking runs at detected edits. [The camera report](CAMERA_BOUNDARY_REPORT.md)
records 65/69 candidate cuts on the samples, six inspected transition pairs, and
an 80-frame CUDA probe across two edits. ByteTrack IDs no longer collide after
reset, TrackNet backgrounds/windows stay within each detected view, and stale
court calibration expires. Contacts now honor player-run cuts as well as shuttle
cuts. These are camera/timestamp boundaries, not replay or rally labels.

Browser inspection found a source-review mismatch while seeking: the old image
could remain visible with the newly selected frame number. A loading cover now
hides that stale view until the requested exact source image arrives. A delayed
request regression checks both the pending and loaded states.

Current local checks: **313 backend tests passed**, two opt-in GPU tests skipped
in the standard suite and passed separately. Browser checks include full-video
boundary navigation and generated two-view upload media for CI. Source hashes,
VFR timestamps, incomplete decoding, artifact lineage, shared job admission,
tracker reset, short temporal segments, and calibration renewal are covered.
Independent cut accuracy, scene corrections/live-replay recognition, and the full
automatic match pipeline remain open.

The preceding increment probes the actual public-source video through YOLO,
TrackNet, and recognition. Both diagnostic windows abstain, and contact alignment
remains unverified; the cached-feature benchmark must not be presented as
raw-video accuracy. [The direct-video report](DIRECT_VIDEO_REPORT.md) records
the source lineage, timing ambiguity, and actual CUDA artifacts.

An opt-in audio/vision contact aid adds uncertain intervals containing the two
previously missed singles pilot labels, with no reviewed labels changed.
[The audio report](AUDIO_CONTACT_REPORT.md) records the four-contact development
comparison, tighter timing results, doubles false-positive concern, and why audio
remains default-off. Duplicate sounds near the same shuttle gap now share one
proposal; conflicting hitter evidence cannot replace the visual hint. Audio
decoding preserves the video's time origin and splits missing/discontinuous PTS.
Missing audio falls back to visual suggestions; changed source bytes still fail.

Previous increment's checks: **299 backend tests passed**, two opt-in GPU tests skipped
in the standard suite; both pass separately. The new source probe ran on CUDA;
all four browser suites pass, including the optional audio request and review
intervals. Source timing, complete-rally labels,
YOLO-domain recognition quality, and full-video correctness remain open.

The preceding increment trains and packages an experimental forehand/backhand head
from pinned published MMPose features. [The side report](STROKE_SIDE_REPORT.md)
records its 12,520 usable clips, frozen split/selection protocol, confidence
coverage, rare-class gaps, and much lower conditional family/hitter/side result.
The editor preserves an existing manual side even when the model disagrees and
does not apply another hitter's side suggestion. Family logits are unchanged by
descriptor capture; all seven cached singles family outputs matched exactly.

New regressions cover archive traversal/links, altered feature bytes, duplicate
joins, match leakage, train-only normalization, nonfinite inputs, partial model
installs, and checkpoint-pointer traversal. Training now writes a versioned model
before committing its metadata pointer and shares processing admission with the
app. A packaged CPU-loadable 161 KB head makes new installations usable without
requiring the full training dataset.

Previous increment's local checks: **269 backend tests passed**, two opt-in GPU tests skipped
in the standard run; both real GPU checks passed separately, and all four browser
suites passed. Direct-video alignment and YOLO-domain recognition accuracy remain
unverified; these checks do not establish full-match correctness.

The data/evaluation increment adds a source-verified ShuttleSet label index and
recognition metrics that exclude classifier-assisted labels. Tests cover the
risk of accepting a model draft and then reporting it as correct ground truth;
that event is now explicitly excluded from recognition accuracy. Abstentions
remain misses in supported-class and complete-event metrics. Unrepresented
families never receive an invented six-class macro score. Published known-error
records quarantine whole affected rallies; original labels remain intact.
The source snapshot contains both 25- and 30-fps evidence, so the importer keeps
source frame/time references and leaves media alignment unverified. See
[the data report](STROKE_DATA_REPORT.md) for counts, conventions, and remaining work.

Latest local checks: **259 backend tests passed**, with two optional GPU tests
skipped; all four local browser suites passed, including recognition metrics and
exclusion of classifier-assisted labels. The previous increment's real GPU
inference checks remain applicable; this change adds no model/inference math.

The first family-model increment added an experimental singles baseline through
the CLI, API, and explicit review UI. [The recognition report](SHOT_RECOGNITION_REPORT.md)
records the source mapping, seven-target CUDA smoke run, abstention behavior,
and missing accuracy evidence. That original version predicted family only;
doubles recognition remains unsupported.
New regressions cover mismatched input lineage, missing context/cuts, duplicate
targets, invalid classification provenance, and stale scores after contact/label
changes. Hitter views now use the current reviewed identity mapping instead of
retaining an old recognition hint. Video switching immediately disables the
recognition button until the selected video's runs load. Existing manual
forehand/backhand values survive loading a suggestion; raw artifacts and real
pilot annotations are unchanged.

Current local checks: **237 backend tests passed**, two optional GPU tests skipped
in the standard run; both opt-in CUDA tests passed separately. All three existing
browser suites and the new real-model recognition browser suite pass. Lint,
formatting, dependency consistency, and the built wheel's model/license/UI contents
were checked. Container checks remain part of the feature PR's CI.

Source-contract review also caught inconsistent hitter hints when the highest
individual source class belonged to a different family than the winning summed
family. Hitter court end now uses probability mass within the selected family;
tied court ends remain unknown. A targeted regression covers that disagreement.

The input/deployment increment adds bounded file uploads, YouTube imports, single-user authentication, persistent container configuration, and CI. [The import verification report](IMPORT_VERIFICATION.md) records an actual BWF YouTube-to-frame/playback API test. Import regressions caught a content-ID overwrite risk from publisher metadata and provenance loss on local-path re-import; publisher metadata is now nested and re-import retains it. Duplicate imports preserve reviewed revisions and do not accumulate duplicate source files. Shutdown admission failure also releases its job claim.

Additional input bugs fixed: rotated phone footage now uses one display orientation for browser-aligned review and CV coordinates; source bytes and timestamps remain unchanged. Download progress accumulates small updates until a visible update is due instead of staying at zero. Generated MP4 orientation tests and a Chromium comparison cover the rotation path. CI also exposed fresh-checkout directory and installed-package root assumptions; fixture paths and test setup now make those boundaries explicit.

Latest increment: reviewed identity mappings, clip completeness, manual shuttle labels, and contact/localization evaluation now work through the UI and API, with a CLI evaluator. Eight visually reviewed development contacts and six identity mappings are saved at annotation revision 2 across the two samples. See [the pilot report](PILOT_REPORT.md) for measured failures and remaining labeling work.

Two additional artifact bugs were found and fixed during this increment: player assignments could accept an artifact whose internal video or stage contradicted its completed job, and evaluation could return a server error for that mismatch. Both now return actionable validation errors. The editor also preserves `corrected` status across repeated edits.

Review/evaluation milestone checks: **84 standard backend tests passed**, with one optional GPU test skipped and both original browser suites passing. Subsequent import and contact increments add their focused regressions and CI checks; see their reports for current evidence.

Contact detection now handles supported short gaps as uncertain proposals and rejects smooth apex curvature. Timing bounds persist through review/export, and unresolved reviewed intervals cannot be used as exact evaluation labels. [The contact report](CONTACT_DETECTION_REPORT.md) records the unchanged pilot comparison: the false apex is removed, one additional hit is covered by an interval, and two hits remain missed.

| Confirmed issue | Resulting fix | Verification |
| --- | --- | --- |
| CLI analysis and web jobs used different admission controls, allowing concurrent workers. CLI ingestion was also uncoordinated. | All CLI/web processing uses an atomic SQLite job claim shared by project instances. | Two competing stores admit exactly one worker. |
| Constructing another app instance marked live jobs as interrupted. | Recovery checks the worker PID and process creation time; live workers survive another instance starting. Recovery updates run inside a transaction. | Live-worker recovery and stale process-lifetime regression checks. |
| Job updates used `INSERT OR REPLACE`, changing row order whenever progress changed. | Updates preserve the original job row, so the newest run means the newest submitted run. | Shared-job workflow exercised through CLI, API, and browser. |
| The calibration flag was true whenever any calibration existed, even outside the selected window. | Results count calibrated frames inside the processed range and report complete coverage only when all processed frames are covered. | A clip outside an existing calibration reports zero calibrated frames. |
| Replacing a video after ingestion could silently misalign saved frames and tracks with different footage. | Source hashes are checked and cached against file size/mtime; changed sources return a clear conflict before playback/frame extraction/processing. | Changed-file API regression checks. |
| Nonfinite CLI times could create empty or invalid analysis ranges. | CLI and API ranges use shared timestamp-based validation; NaN/infinite CLI arguments are rejected. | Finite-range and VFR checks. |
| A pending save could respond after a video switch and affect the newly loaded document. | Switching waits for an in-flight save to finish. New edits made during the save remain unsaved and preserved. Tracking-result responses also check the selection generation. | Browser delayed-save/switch and delayed-response checks. |
| Duplicate serve/shot contacts or the same accepted proposal could be saved more than once. | Contact-frame uniqueness and proposal provenance are validated. | Schema regression checks and browser proposal acceptance/export. |
| Ingestion wrote timestamp JSON directly, allowing a reader to encounter a partial file. | Timestamp maps and result artifacts are replaced atomically. | Ingestion, re-import, and frame-access workflows pass. |
| A completed job with a missing run file returned an internal server error. | Run and contact endpoints return a recoverable not-found response and a rerun instruction. | Missing-artifact API regression check. |

Player-model cleanup now runs on failures as well as success. Media responses infer the container MIME type. Unsupported/missing video frames display an actionable viewer error.

## New processing capability

Added the official TrackNetV3 model architecture and checkpoint, with the upstream MIT license, pinned source commit, and SHA-256 provenance. The adapter uses actual source timestamps, a bounded background sample, eight-frame overlapping windows, and raw shuttle heatmap observations. Missing positions remain null. It does not interpolate or repair trajectories.

| Inspected window | Source frames | Visible detections | Processing time | Throughput | Contact proposals |
| --- | --- | --- | --- | --- | --- |
| Singles, 80Ã¢â‚¬â€œ90 s | 250 | 227 | 30.449 s | 8.21 frames/s | 8 |
| Doubles, 24Ã¢â‚¬â€œ34 s | 250 | 211 | 28.819 s | 8.67 frames/s | 9 |

The model used CUDA with float16 inference and peaked at approximately 385 MB of PyTorch-allocated GPU memory; this excludes driver/library memory. The timings cover background estimation, decoding, inference, and processing-loop progress writes, and exclude loading the model. These are measurements of the selected local windows.

The visible counts are **model outputs, not localization accuracy**. Sampled annotated frames were inspected visually. Some fast or occluded shuttles are missed. The sparse visual inspection is not a labeled evaluation dataset.

Contact suggestions combine changes in shuttle motion with nearby player boxes/wrists. Track IDs are hints, with persistent hitter identity and stroke labels left unknown. Scores are heuristic ranking scores, not calibrated probabilities. False proposals and missed hits remain possible. The viewer requires explicit review/add/save before a suggestion becomes an annotation; its source run and candidate ID remain in JSON/CSV exports.

## Checks completed

- 17 standard backend tests pass.
- The opt-in real-GPU API test passes, including a five-frame clip shorter than the eight-frame model window, exact source timestamps, padding, and no automatic annotation edits.
- Browser checks pass for video/frame review, saved edits, conflict-sensitive workflows, court calibration, singles/doubles switching, and contact proposal review/export. The optional proposal check uses cached real analysis runs when available.
- Both full 250-frame shuttle experiments completed on the local GPU. Player and shuttle overlays and the proposal panels were inspected visually.
- Python lint, frontend formatting, and dependency consistency checks pass.

The first small partial-rally pilot, evaluator, and reviewed player-to-track assignments are implemented. Contact recall on that singles pilot is poor, so the next milestone is better contact detection plus a larger, independently reviewed set of complete rallies. A pretrained singles family baseline now exists, but held-out family evaluation, automated serve/end detection, stroke-side prediction, doubles recognition, automatic identity recovery, and full-highlight replay/camera segmentation remain pending. All real pilot family/side labels remain unknown.

