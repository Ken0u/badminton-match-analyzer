# Native source-only shuttle review packets

Completed source preparation on October 21, 2026, for [issue 160](https://github.com/Ken0u/badminton-match-analyzer/issues/160), under [localization milestone 65](https://github.com/Ken0u/badminton-match-analyzer/issues/65). Both complete selected video streams and all **248,100 native frames** are sealed. The fixed packet retains **128 cases / 640 requested context memberships / 632 unique PNGs**. Every review label remains unknown; no model, label accuracy or improved automatic annotation is established. Independent PR review, controller integration, exact-main and complete public delivery remain pending at this report revision.

## Selected streams and native coverage

The [source declaration](../data/manifests/shuttle_review_sources_v1.json) pins two official BWF TV broadcasts and [the protocol](../data/manifests/shuttle_review_packet_protocol_v1.json) was committed before acquisition. Both returned official channel `UChh-akEbUM8_6ghGVnJd6cQ`, public availability and video-only AVC format 137 at 1920x1080 / metadata 30 fps. No alternate source or format, account, cookies or access-control bypass was used. These are complete selected video-only streams with no audio, rather than original all-stream archives.

| Canonical YouTube ID | Source bytes | Decoded native frames | Cases | Context memberships | Unique PNGs |
| --- | ---: | ---: | ---: | ---: | ---: |
| `go2uajSiBnE` | 1,135,039,222 | 129,600 | 64 | 320 | 316 |
| `H1setLK1tig` | 1,137,172,263 | 118,500 | 64 | 320 | 316 |

[Singles go2uajSiBnE](https://www.youtube.com/watch?v=go2uajSiBnE) reports Naraoka/Lanier at the 2026 World Championships; [doubles H1setLK1tig](https://www.youtube.com/watch?v=H1setLK1tig) reports Kim/Seo versus Alfian/Fikri at the 2026 Japan Open. Titles, category and original-match identity remain metadata assertions. The short 483-second `kEQBaobDUFY` highlights candidate was rejected during planning. Whole selected-stream coverage does not certify semantic full-match completeness, camera context, live/replay content or badminton annotations.

Both native clocks begin at source time zero. Last native PTS values are 4,319.966666666666 seconds for singles and 3,949.9666666666667 for doubles. Every ordinal, PTS, time base, orientation, source/display geometry and corruption flag is retained; both complete censuses report no issues. No nominal-FPS reconstruction, repaired frame or missing-frame deletion was used. A complete second decode checks every native identity before finishing each packet, while selected images apply the original display orientation without interpolation.

Source seals are public reproducibility identifiers; raw media, censuses, PNGs and editable templates remain ignored:

- `go2uajSiBnE` source: `708a6f1732204e2446d27bb7093c8af1c393deebc0391b67a678e0e72f7b34d9`; native census: `f1cf689916f85716fddb692f5bb9118812a4f4c66f211ed4b9de7e7c6fb3965f`; packet: `31ce7994f18b4f8fe79e7146e2a4d720b678c97e0485f5bc2d4efc94c452415b`.

- `H1setLK1tig` source: `49485613fd93210c5c739f7f1e07948ac558691719e9315772d6f213b3273623`; native census: `867467f96a9bedecff035053d765e368d70abcde13d79dc4830b4c24fe87d5b0`; packet: `73db8fc5da12da63fdf94820dfa2ea5ee90b765bad445c11abe06d00e69d7056`.

## Fixed sampling and unknown labels

For each source with `N >= 64`, exactly 64 centers use `floor(j * (N - 1) / 63)` for `j = 0..63`, including both endpoints. Each center retains offsets `[-2, -1, 0, 1, 2]`, clamped to valid native ordinals with explicit membership identities. Each source has 320 requested memberships and 316 unique stored images; four repeated edge memberships remain in the denominator. All 632 selected images are available and hash-verified. Deduplication affects image storage only.

A separate editable template retains all 128 cases, with visibility, difficulty and scene `unknown`, coordinates `null`, and `reviewed: false`. Unknown is neither absence nor a negative label. Models, detections, heatmaps, calibration, interpolation, scores and inferred labels play no role in selecting or decorating these inputs. Reviewed labels, source metadata, packet provenance and future predictions remain separate. Nothing was registered into application truth or installed as a model/default; existing datasets, annotations and predictions were preserved.

All four flags are false in declarations, packets, templates and result evidence: `training_allowed`, `independent_test_allowed`, `model_deployment_allowed` and `dataset_redistribution_allowed`. Public access and recent titles/upload dates establish neither permission nor independent-test eligibility. Original-match overlap, upstream checkpoint membership, semantic completeness, camera context, category support and media rights remain unresolved.

A pre-acquisition exact-ID search checked only the tracked public `shuttle_supervision_sources_v1.json` declaration and the supervision, corpus diagnostic and visibility aggregate reports. Neither canonical ID appears in those four descriptors. This narrow string audit cannot rule out a different encode, alternate URL, original-match overlap or upstream membership. Consumed holdout63 inputs, predictions, protocols, private membership and artifacts were never inspected.

## Frozen execution and preserved failure

Successful producer code is [a4598f403fd19a8a34cc96043cd49e0dbf87d26d](https://github.com/Ken0u/badminton-match-analyzer/tree/a4598f403fd19a8a34cc96043cd49e0dbf87d26d), published in the [pre-data checkpoint](https://github.com/Ken0u/badminton-match-analyzer/issues/74#issuecomment-6308161061). All 56 frozen consumer/declaration files were copied and verified against that commit; the final report changes documentation only. Context SHA-256 is `94f24bbc864f054283e9d7a8e2eb393191ebfa9ea4c508e86cbabae82c949669`. Declaration SHA-256 is `0267138a519668369f5a2b0054822456c51257b244989c71c131c7f6cbd0ead7`; protocol SHA-256 is `76ba01d7e13b5cf5e050c4a0ae5c243066cc88307b8debf05eaeeb98f27487a3`.

The first admitted worker exited with code 1 after 4.625 observed seconds, before transferring video bytes. Its Store job failed and both original worker/observer lifetimes exited. Returned metadata matched the selected ID, channel, format, size and geometry, but the code incorrectly rejected `was_live`, an ended livestream archive. The repair accepts `not_live` and `was_live`, while rejecting live, upcoming and unfinished streams. Metadata, frozen context, admission, terminal and external exit evidence from that attempt remain intact.

The repaired attempt uses a new lineage and verifies the original exit SHA, sibling start record, matching terminal/Store ownership and exited process lifetime, plus unchanged source declaration/protocol. It carries the original 4.625 seconds, 871,620 output bytes and zero downloaded bytes forward. There was no restart from a timeout or lost observation handle, and no executed consumer changed while work was live.

The successful worker used the real original application's shared Store through `run_local_job`, under the actual data-resource reservation. External observation verified its actual PID, creation time, cwd, command and matching running Store job. It exited with code 0; its Store job completed and both worker/observer lifetimes exited. Private process details and receipts stay ignored.

Combined selected video bytes are **2,272,211,485**, within 3 GiB total and 2 GiB per source. Scientific output including the preserved failed attempt totals **2,979,318,337 bytes**, within 6 GiB. Retained software-check artifacts add approximately 161 MB and also keep total task output below that limit. Internal cumulative worker time is 722.469 seconds; the more conservative sum of both external observed lifetimes is **723.671 seconds**, below 7,200 seconds and within the four-hour task. Failed attempts count toward these budgets. Every output publishes exclusively, and no pending transfer/output files remain.

Recorded runtime: Python 3.10.5, PyAV 16.1.0, NumPy 2.2.6, Pillow 12.3.0, psutil 7.2.2, Torch 2.8.0+cu126, torchvision 0.23.0+cu126 and yt-dlp 2026.8.19. Existing environments were preserved. Torchvision initializes before threaded PyAV; native FFmpeg logging is restored before opening and closing media. No model/GPU inference or training was run.

## Reproduction and verification

Use [prepare_shuttle_sources.py](../scripts/prepare_shuttle_sources.py) from a frozen task checkout with the original application's existing environment and genuine data-resource grant. The launcher pins original root/data/weights before configuration imports, loads its own checkout backend, and removes GitHub, Project and OpenAI token variables. An isolated research Store cannot admit competing work.

```powershell
$appRoot = 'C:\path\to\original\badminton-match-analyzer'
$checkout = 'C:\path\to\frozen\task-checkout'
& "$appRoot\.venv\Scripts\python.exe" "$checkout\scripts\prepare_shuttle_sources.py" `
  --root "$appRoot" --output "$appRoot\.cache\shuttle-source-packets-new-lineage"
```

On POSIX use the original `.venv/bin/python`. An interrupted retry additionally requires `--prior-exit` and `--prior-exit-sha256`, naming the durable external `.exit.json` and its actual SHA-256; its sibling `.started.json` must identify the same original worker and output. Verify real process/Store/terminal evidence before retrying. Fresh clones do not supply these private local artifacts. Console output contains only a completion status or redacted exception type.

All **1,548 Python regressions passed**, with four existing optional GPU skips. The 56 focused source tests cover real VFR/rotation/native pixels, fixed sampling and clamped edges, unknown/unavailable/corrupt support, source/context tampering, exclusive outputs, byte/wall limits, HTTP range continuity/truncation, metadata changes, ended archives, credential refusal, actual Store admission/process evidence and cumulative prior-attempt guards. Ruff, formatting, dependency, diff and text/JSON/link checks pass. All 12 hosted verification jobs pass at the frozen producer revision.

A separate author-side artifact audit recomputed both raw hashes, native clock seals, all 56 consumer Git hashes, every PNG hash/geometry, exact sampling identities, all 128 cases/640 memberships, unknown templates, eligibility flags, budgets, Store and external exit evidence. Audit receipt SHA-256 is `708de500b0068eb0083a9dabb210ca48a0edb86f19dfd403fd20c23bf21def86`. This audit is separate from the required fresh independent PR review; it does not replace that review.

Fresh independent exact-head approval, final CI, controller integration, exact-main and complete public delivery remain pending. Green software checks and complete packet coverage do not establish reviewed match completeness, balanced visibility/occlusion support, independent labels, localization quality or full badminton annotation accuracy. Parent 65 and the full application goal remain open. Independent source-only labeling and a separately frozen improvement experiment require subsequent bounded tasks.
