# Deploy the single-user application

The app supports a local workstation or a persistent, single-user container. It
uses one application process, one analysis worker, and a SQLite catalog. A public
multi-user service, distributed job queue, and per-user storage are not implemented.
Family/side suggestions are experimental and singles-only; complete automatic
match annotation remains unverified. Keep this distinction when sharing a demo.

## Build and run

Docker must be running in Linux-container mode. The default image includes CPU
tracking and singles recognition dependencies. External checkpoints are downloaded
into the persistent state volume; the small stroke-side head is packaged with the app.
Build `review` for playback, imports, annotations, and
evaluation without PyTorch, or `gpu` for the CUDA 12.6 build.

```powershell
docker build --target review -t badminton-review .
docker build --target cpu -t badminton-cpu .
docker volume create badminton-state
```

Set credentials in the terminal used to start the container. Use your own password
manager to supply a strong password; do not commit credentials or put them in an
image. The following avoids putting the password value in shell history:

```powershell
$env:BADMINTON_USERNAME = 'reviewer'
$env:BADMINTON_PASSWORD = [System.Net.NetworkCredential]::new('', (Read-Host 'App password' -AsSecureString)).Password
docker run --detach --name badminton --restart unless-stopped --publish 127.0.0.1:8000:8000 --mount type=volume,source=badminton-state,target=/state --env BADMINTON_USERNAME --env BADMINTON_PASSWORD --memory 8g --cpus 4 badminton-cpu
```

Open **http://127.0.0.1:8000** and sign in using the browser's authentication
prompt. Upload a local video or paste one public YouTube video URL and select
singles/doubles. Imports are asynchronous jobs; the video appears when source
inspection completes. Source match videos and annotation data are supplied separately.
The image includes the small project-trained side head and its report. Download
the external player, shuttle, and family checkpoints into the state volume before
running recognition.

The review target uses the same command with `badminton-review`. For a small CPU
host, start there. CPU tracking is supported but can take substantially longer
than the laptop GPU measurements. Allow disk space for source videos, temporary
uploads/downloads, metadata, and model artifacts; a 2 GiB upload can temporarily
occupy more than 2 GiB while being staged and inspected.

```powershell
docker exec badminton python scripts/download_models.py --kind all
docker logs --tail 50 badminton
docker inspect --format '{{.State.Health.Status}}' badminton
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Downloading checkpoints needs outbound HTTPS and happens only when explicitly
requested. The downloader verifies the pinned hashes in
`backend/badminton/model_manifest.json`; model inference does not download
arbitrary checkpoints automatically. The named volume retains media, annotations,
jobs, and weights when the container is replaced. The process runs as UID/GID
10001; Linux bind mounts must be writable by that identity.

## NVIDIA GPU variant

```powershell
docker build --target gpu -t badminton-gpu .
docker run --detach --name badminton-gpu --gpus all --publish 127.0.0.1:8002:8000 --mount type=volume,source=badminton-state,target=/state --env BADMINTON_USERNAME --env BADMINTON_PASSWORD --memory 8g --cpus 4 badminton-gpu
docker exec badminton-gpu python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

Stop the CPU container before opening the same state volume with the GPU
container. On Linux, configure the host NVIDIA Container Toolkit and its Docker
runtime first. Docker Desktop on Windows needs its supported NVIDIA/WSL2 GPU
configuration. The image's CUDA packages do not replace the host driver. See
[NVIDIA's installation guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
and [Docker GPU configuration](https://docs.docker.com/compose/how-tos/gpu-support/).
Choose CPU if the host cannot expose a compatible GPU. The current GPU checkpoint
test is opt-in and is not run on ordinary GitHub-hosted CI.

## Configuration and network exposure

| Setting                                     | Container default                                    | Purpose                                                                                  |
| ------------------------------------------- | ---------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `BADMINTON_ROOT`                            | `/state`                                             | Boundary for imported source paths; uploaded/downloaded files live under `.media/` here. |
| `BADMINTON_DATA_DIR`                        | `/state/data/processed`                              | SQLite database, timestamp maps, images, runtime caches, and analysis runs.              |
| `BADMINTON_WEIGHTS_DIR`                     | `/state/models/weights`                              | Locally downloaded model checkpoints.                                                    |
| `BADMINTON_MAX_MEDIA_BYTES`                 | `2147483648`                                         | Maximum video upload/download size, in bytes.                                            |
| `BADMINTON_USERNAME` / `BADMINTON_PASSWORD` | Unset; required by the container command             | HTTP Basic credentials for the entire app except health. Set both.                       |
| CLI `serve --host` / `--port`               | Container `0.0.0.0:8000`; local CLI `127.0.0.1:8000` | Listener interface and port.                                                             |

`GET /api/health` is deliberately unauthenticated and reports only service health.
It does not load the models or prove inference works. Other API routes, static
files, and media require credentials when authentication is configured. With no
credentials the local CLI permits loopback by default; a network listener
requires credentials or an explicit `--allow-unauthenticated` override.

Publish to `127.0.0.1` as shown above. For remote access, put a maintained HTTPS
reverse proxy in front of that listener and retain application authentication.
HTTP Basic credentials must travel over TLS on an untrusted network. If an
authenticated private proxy supplies the access boundary instead, explicitly
append `serve --host 0.0.0.0 --allow-unauthenticated` after the image name in the
`docker run` command. Never expose that override directly to an untrusted network.

Configure the proxy's body-size limit consistently with the app. The app allows
an additional 1 MiB of request overhead for multipart uploads; a lower proxy limit
rejects a request before Python sees it. Restrict access to the authenticated
operator: local-path import can read supported video files inside
`BADMINTON_ROOT`, and the operator can retrieve registered media. Do not mount
unrelated personal files or credentials into that directory. Resource limits and
free disk space remain deployment concerns, even with bounded uploads.

Use one process and one instance per state volume. The job claim is designed for
local process ownership and is not a distributed lock across hosts or PID
namespaces. Do not share one SQLite volume between replica containers. For an
upgrade or backup, stop the app, copy the entire state volume, then start the new
image against that volume. Preserve source files alongside the database: frame
alignment is verified by source content hash.

## YouTube and media requirements

The image includes Node.js 24, the pip `yt-dlp[default]` dependencies (including
the EJS challenge solver), and FFmpeg/ffprobe. The importer enables Node explicitly
and accepts a single HTTPS YouTube video. It rejects playlists and active or
scheduled streams. Videos requiring account cookies, private access, or DRM are
not supported. Upload a local copy when a public URL cannot be retrieved.

The upstream downloader currently supports CPython 3.10+, while this image uses
Python 3.12. YouTube challenge handling requires a supported JS runtime; Node 22+
is supported and must be enabled. These requirements are documented in
[yt-dlp's README](https://github.com/yt-dlp/yt-dlp#dependencies) and its
[EJS setup guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS). YouTube can change
independently of this app. Rebuild after a downloader fix, test a permitted public
video, and retain its recorded source URL/hash. Do not promise every public URL
will work indefinitely.

The current import format preference uses one downloadable media stream, so an
FFmpeg merge is not normally needed; a video-only fallback can have no audio.
FFmpeg is included for codec tools and future media workflows. FastAPI's
`UploadFile` uses a spooled file; this reduces memory use but is not itself a
size quota. The app separately checks incoming body and saved-file limits.
See [FastAPI file uploads](https://fastapi.tiangolo.com/tutorial/request-files/).

## Dependency licenses and source

Private deployment does not choose a license for the project's own code. No root
project license has been selected here. Preserve dependency notices and review
redistribution requirements before publishing an image or operating a public
service.

| Component                                 | Upstream terms / included material                                                                                                                                                                   |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ultralytics package and player checkpoint | Upstream AGPL-3.0 or separately obtained enterprise terms. CPU/GPU targets install this component. The review target omits it. See [Ultralytics licensing](https://www.ultralytics.com/license).     |
| Vendored TrackNetV3 model                 | MIT text and pinned source manifest are included under `backend/badminton/vendor/`. The checkpoint source/hash/terms are in the packaged model manifest.                                             |
| Vendored BST-0 model                      | MIT text and pinned source manifest are included under `backend/badminton/vendor/bst/`. The official checkpoint source/hash and singles-only scope are in the packaged model manifest. See [the recognition report](SHOT_RECOGNITION_REPORT.md). |
| Project-trained stroke-side head          | A 161 KB experimental head, pinned training recipe, source feature/label hashes, and report ship under `backend/badminton/assets/`. See [the side report](STROKE_SIDE_REPORT.md) for the source-input conditions and missing YOLO validation. |
| PyTorch / torchvision                     | Their installed distributions retain upstream license notices. CPU and CUDA packages are installed from PyTorch's official indexes.                                                                  |
| yt-dlp                                    | Installed from PyPI with upstream package notices. Its source/wheel is Unlicense; optional dependencies carry their own terms. See [upstream licensing](https://github.com/yt-dlp/yt-dlp#licensing). |
| Node.js and FFmpeg                        | Node's license is copied to `/usr/local/share/licenses/node/LICENSE`; Debian copyright/license notices remain under `/usr/share/doc/`. FFmpeg licensing depends on the distributed build.            |

An Ultralytics-dependent public deployment must address its source-availability
requirements or use appropriate enterprise terms. Keep the exact application
source revision and the dependency/model inventory with a deployment; do not
describe an AGPL-dependent image as unrestricted proprietary software. This guide
records upstream terms rather than granting any additional permissions.

## Frontend build, delivery and rollback

FastAPI serves the production React library at `/` and `/library`, and the review
editor at `/editor`. The same single application process serves API, media and UI;
there is no runtime Vite or frontend server. Unknown application paths, missing
assets and unknown API routes return 404. Authentication covers each route and
asset except `/api/health`. HTML, the manifest and stable entry assets revalidate
on release, so a browser does not retain an old entry bundle indefinitely.

Build from a Git checkout with the pinned Node major in `.node-version`:

```sh
npm ci --ignore-scripts
npm run frontend:typecheck
npm run frontend:test
npm run frontend:build
npm run frontend:stage
npm run frontend:stage:check
```

`backend/badminton/static/build-manifest.json` records source-input SHA-256 hashes
and the exact production asset set, including bundled dependency license notices
in `THIRD_PARTY_NOTICES.txt`. Commit the staged snapshot with its frontend
source. CI and Docker rebuild the frontend and compare every staged byte and input
hash; they fail on stale, missing, changed or extra output. Generated bundles are
verified this way instead of reformatting minified build output. The synthetic
foundation is an explicit development/test build and is excluded from production.

Wheels and source distributions include the prebuilt runtime assets. Installing
them requires no frontend build toolchain; Python package discovery excludes the
frontend workspace. Rebuilding the frontend or Docker image requires the Git
checkout, not the Python source distribution. The Docker frontend stage contains
npm and build tooling; application stages copy only the verified assets and
Python package. The existing Node executable remains for YouTube import.

Use `python scripts/verify_package.py --build --dist-dir .cache/dist` with the
project's locked review interpreter and uv to check archive/source parity and a
fresh installed wheel outside the checkout. The verifier starts its own disposable,
authenticated loopback app with empty storage and checks entry pages, asset hashes,
MIME types, auth refusals and unknown paths. It records and verifies its own process
identity before cleanup. It does not connect to an installed application.

For an independently started disposable review/CPU container, the same HTTP probe
can run without Python application dependencies on the host:

```sh
python scripts/verify_package.py --url http://127.0.0.1:8000 --username reviewer --password-env BADMINTON_VERIFY_PASSWORD
```

Set that environment variable to the disposable container's password. The probe
requires an empty catalog and uses GET requests only. Never point test fixtures
at an existing catalog. The package/container probes do not download models or
run inference.

Candidate publication follows the existing approved `public` policy in
`.github/automation.json`; the private Project dashboard is separate. Phase 5's
receipt requirement uses that current visibility, as explicitly approved on its
owning issue. Keep the exact source SHA, package hashes and review/CPU image digests
with each candidate. Publication does not upgrade a running application.

The default UI cutover is a code release and changes no annotation/source-clock
schema. If an operator later authorizes deployment, preserve the state volume and
source media, use one application instance, and retain the previously verified
image digest or wheel. A rollback selects that previous complete code artifact
against the same preserved data; it does not copy obsolete frontend files over a
new backend or rewrite annotations. Stop and verify ownership of the deployed
instance before replacing it. This development task does not perform that upgrade
or rollback. Its final workflow/Docker/packaging diff also requires the frozen
issue's actual non-author human approval before controller integration.

## Verification and current limits

CI checks strict frontend types, the generated OpenAPI contract, frontend tests,
reproducible production output, clean installed-package routes/assets and native
Mac/Windows builds. The production browser harness exercises the complete frozen
generated-media workflow matrix through FastAPI, including imports, source-native
playback, editing, jobs, save/reload, exports, keyboard access and performance
ceilings. External downloads and unavailable inference are explicitly stubbed in
those generated fixtures. Review and CPU containers must each pass authenticated
route/asset checks and dependency verification. A destination GPU remains a
separate explicit validation requirement.

Local parity and frozen three-run performance results, exact CI runs, independent
review and any human approval are recorded on the owning phase-5 issue/PR. Do not
infer a successful image build or rollout from these documented commands. The
runtime dependency graph uses `pyproject.toml` and the committed `uv.lock`; no
running application is upgraded by a candidate build. Green software checks do not
establish live YouTube availability, full-match annotation accuracy or model
promotion.
