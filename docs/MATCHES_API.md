# Matches API

Upload a video with the player names, wait for one job, confirm the names,
then read the `MatchAnalysis` document (`docs/MATCH_ANALYSIS_FORMAT.md`).
Code: `backend/badminton/matches.py` (record, names, swaps, job body) and the
`/api/matches` routes in `backend/badminton/api.py`. Types for the frontend
come from the generated contract in `backend/frontend/src/api/generated/`.

The match id is the video id (the first 16 hex digits of the file's SHA-256).

## Flow

1. `POST /api/matches` (multipart): `file`, `mode` (`singles`/`doubles`),
   `team1` and `team2` (repeated form fields: one name per team in singles,
   two in doubles; partners go in the same team). Names are 1 to 100
   characters and must differ. Returns `202` with `match_id`, `video_id`,
   `job_id` and `reused_video`.
   - Uploading a video that is already stored reuses it (the duplicate file is
     deleted), so every finished processing stage is reused; a new POST starts
     the names over. A video stored with the other mode gives `409`.
   - Only one job runs at a time across the app (shared Store admission):
     `409` while another runs.
2. One job runs: ingest (new videos only), full-match processing
   (`pipeline.process_match`: camera cuts, automatic court detection, players,
   shuttle, contacts, rally proposals, strokes, actor linking, persons), then
   the `MatchAnalysis` build. Nothing needs a manual step; annotations are
   never read for values or edited.
3. `GET /api/matches/{id}` until `state` is `needs_names`:

   | Field | Meaning |
   |---|---|
   | `state` | `queued`, `running`, `needs_names`, `ready`, `failed`, `paused` |
   | `progress` | the whole job, 0..1, weighted by typical stage time |
   | `stage` | label: Preparing the video, Scanning the video, Finding players, Tracking the shuttle, Reading strokes, Recognising players, Building the analysis (and Waiting to start, Pausing, Paused, Confirm the player names, Done, Failed) |
   | `error` | why it failed or paused, else `null` |
   | `warnings` | the document's warnings, e.g. identity weights missing |
   | `names_confirmed`, `job_id`, `mode`, `name` | as named |

   Processing works in 60 s windows, so the label cycles Finding players,
   Tracking the shuttle, Reading strokes once per window.
4. `GET /api/matches/{id}/players`: each person (`id`, `team`, `name`,
   `name_source` `guessed`/`confirmed`, `thumbnail_url`) and the names as
   entered (`teams`). The guess puts team 1's names on `T1` (`P1`, `P2`) and
   team 2's on `T2`. `thumbnail_url` is
   `/api/matches/{id}/players/{person}/thumbnail` (JPEG), served only from
   inside the video's data folder.
5. `PUT /api/matches/{id}/players` with `{"names": {"P1": "...", ...}}`: every
   person gets one of the entered names, each name once, doubles partners on
   one team (`422` otherwise). The document is rebuilt with the names and
   `state` becomes `ready`. It can be sent again later.
6. `GET /api/matches/{id}/analysis`: the document (also at
   `GET /api/videos/{id}/match-analysis`).
7. `GET /api/matches/{id}/stats`: whole-clip statistics of the stored
   document (`docs/CLIP_STATS.md`; also at `GET /api/videos/{id}/match-stats`),
   computed on request and kept while the document is unchanged; 404 until
   the document is built.

`GET /api/matches` lists matches, newest first.

## The swap

`POST /api/matches/{id}/rallies/{rally_id}/swap` with
`{"persons": ["P1", "P2"]}` swaps the two persons for that rally's frames
(every hitter, server, player position and track sample). It returns
`applied`, the rebuilt `rally` and all `overrides`. The same swap again undoes
it (`applied: false`); `DELETE` on the same path removes every swap of the
rally. Swaps are kept in `<data>/<video id>/match_overrides.json` and applied
by the builder on every rebuild, so they survive reprocessing. Allowed only in
`needs_names` or `ready` (`409` otherwise).

## Pause and resume

`POST /api/matches/{id}/pause` asks the running job to stop at its next check
(`stage` shows Pausing, then `state` `paused`); finished stages are kept.
`POST /api/matches/{id}/resume` starts the job again for a paused, failed or
finished match and reuses every finished stage. The old
`/api/videos/{id}/analysis/{job_id}` and `/pause` endpoints work on the same
job, which is an ordinary `analysis` job.

## Identity weights

If `models/weights/reid/osnet_doubles_ft1.pth` is missing or does not match
the model manifest, the job still finishes: the persons stage is skipped, the
document uses per-view ids (`identity.persistent: false`) and the status
carries a warning. After installing the weights, resume runs just that stage.

## Files

Per video, in the data folder (never inside the package, so perception cache
keys are unaffected): `match.json` (mode, entered names, confirmed names, job
ids), `match_overrides.json` (swaps) and `match_analysis.json` (the document).
The persons document and pipeline artifacts are never edited.
