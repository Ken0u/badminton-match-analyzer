# Matches API

Upload a video (or give a YouTube link) with the player names, wait for one
job, confirm the names, then read the `MatchAnalysis` document
(`docs/MATCH_ANALYSIS_FORMAT.md`).
Code: `backend/badminton/matches.py` (record, names, swaps, job body) and the
`/api/matches` routes in `backend/badminton/api.py`. Types for the frontend
come from the generated contract in `backend/frontend/src/api/generated/`.

The match id is the video id (the first 16 hex digits of the file's SHA-256).
A match from a YouTube link has a link id (16 hex digits of the link's hash)
until its video is downloaded; then it becomes the video's match, and every
`/api/matches/{id}` route given the link id answers for the video's match
(`match_id` in the status is then the video id; clients switch to it).

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
   - Instead of `file`, send `url`: a public YouTube video link (`https`,
     `youtube.com/watch?v=`, `youtu.be/`, `/shorts/` or `/live/`; no
     playlist). Send exactly one of `file` and `url` (`422` for both or
     neither). The link is checked at once (`422` with a plain message, no
     job); the download itself runs inside the job as its first stage,
     Downloading the video, with the downloader's progress. `video_id` is
     `null` in the reply until then. If a video downloaded from the same link
     is already stored, it is reused and nothing is downloaded
     (`reused_video: true`, the match id is the video id at once). The link
     is kept as `source_url` in `match.json` and as `source.url` in the
     video's metadata.
   - A download that fails (private, unavailable, live, too large, or the
     downloader cannot read it) ends the job `failed` with the downloader's
     message in `error`; resume downloads again. Pausing during the download
     takes effect when the download has finished.
2. One job runs: the download (link matches only), ingest (new videos only),
   full-match processing
   (`pipeline.process_match`: camera cuts, automatic court detection, players,
   shuttle, contacts, rally proposals, strokes, actor linking, persons), then
   the `MatchAnalysis` build. Nothing needs a manual step; annotations are
   never read for values or edited.
3. `GET /api/matches/{id}` until `state` is `needs_names`:

   | Field | Meaning |
   |---|---|
   | `state` | `queued`, `running`, `needs_names`, `ready`, `failed`, `paused` |
   | `progress` | the whole job, 0..1, weighted by typical stage time |
   | `stage` | label: Downloading the video (link matches), Preparing the video, Scanning the video, Finding players, Tracking the shuttle, Reading strokes, Recognising players, Building the analysis (and Waiting to start, Pausing, Paused, Confirm the player names, Done, Failed) |
   | `error` | why it failed or paused, else `null` |
   | `warnings` | the document's warnings, e.g. identity weights missing |
   | `video_id` | the video id; `null` while a link match downloads |
   | `source_url` | the YouTube link a link match came from, else `null` |
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
finished match and reuses every finished stage (a link match whose download
did not finish downloads again). The old
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
ids, `source_url`), `match_overrides.json` (swaps) and `match_analysis.json`
(the document). A link match waits in `<data>/<link id>/match.json`; after the
download that record only points to the video (`moved_to`).
The persons document and pipeline artifacts are never edited.
