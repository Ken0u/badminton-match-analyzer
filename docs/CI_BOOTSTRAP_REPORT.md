# Ubuntu CI dependency preparation

Issue [#200](https://github.com/Ken0u/badminton-match-analyzer/issues/200) addresses
repeated slow system-package downloads before application tests. It changes only
native dependency preparation in the existing Python, installed-package and
browser jobs. Required checks, their time limits, retry policy, dependency lock,
signature verification and controller integration remain unchanged.

## Observed failure and frozen comparison

Documentation PR #199 at `4411e581b94dd96d46149f722ae9a2ddddc7e5be` passed
2,048 local tests with four optional skips, but
[CI run 39883596637](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/39883596637)
attempt one timed out both Python jobs while installing system packages. Nine
other verification jobs passed; the dependent gate failed. Its single bounded
failed-job retry passed Python 3.12 and retained those nine successes, but Python
3.10 again exhausted the unchanged 20-minute job limit before project tests.
The original attempts and logs remain preserved. This task does not rerun them.

The retry's Python 3.10 log records 64.7 MB fetched in 19 minutes 39 seconds at
54.9 kB/s from `azure.archive.ubuntu.com`. It requested 87 new packages and four
upgrades. The runner was Ubuntu 24.04.5, image `20261012.334.1`; its notice about
a future Ubuntu 26 migration does not establish the cause. The underlying
network cause remains unknown. Earlier incident #195 and completed reliability
repairs #192/#197 remain distinct from this bootstrap change.

Before implementation, the owning issue recorded the prospective candidate,
baseline log hashes, generated checks, three-hour deadline and 128 MiB output
cap. The [start checkpoint](https://github.com/Ken0u/badminton-match-analyzer/issues/200#issuecomment-6355722711)
retains those boundaries and the separate owner authorization.

## Implementation and safety boundaries

`scripts/ci_linux_dependencies.py` runs through system Python with sudo only on
disposable Ubuntu x86_64 Actions runners. It recognizes Ubuntu 22.04, 24.04 and
26.04 suites and refuses mismatched or unknown releases. It validates source
configuration before writing and replaces only recognized Azure or runner
mirror-list Ubuntu transport URIs with `https://archive.ubuntu.com/ubuntu/`.
Existing official archive/security URIs, unrelated sources, suite pockets,
components, architectures and the Ubuntu archive keyring remain intact. It
rejects mixed unknown URIs, missing/conflicting keyrings, insecure options and
indirect source writes. It changes no signing key or APT retry/trust setting.

The official [Ubuntu archive verification documentation](https://documentation.ubuntu.com/security/software-integrity/archive-verification/)
describes signed metadata and package integrity. The official
[APT source documentation](https://manpages.ubuntu.com/manpages/noble/man5/sources.list.5.html)
defines URI, suite and `Signed-By` behavior. These establish the intended source
and signature semantics; they do not guarantee future mirror availability or
download speed.

The helper probes working `ffmpeg`/`ffprobe` commands for Python/browser jobs,
and loadable `libGL.so.1`/`libglib-2.0.so.0` for Python/package jobs. It reuses
working native dependencies, otherwise runs the existing APT update/install
sequence for missing original packages only. Command failures propagate; all
required probes run again after installation and fail if still unavailable.
The complete existing generated-media, Python, package, browser and container
checks remain the behavior tests. A version/library probe alone does not certify
codec functionality or application correctness. Browser dependency preparation
also routes the Ubuntu archive before the unchanged Playwright dependency step.

No application, model, dataset, reviewed label, research process, local
environment, publisher or coordination policy changes. Raw data and credentials
are excluded. #189 remains incomplete until its own fresh grant and full
verification/delivery; this infrastructure repair does not establish badminton
annotation accuracy.

## Verification and reproduction

Run the focused generated checks with the existing project environment:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_ci_linux_dependencies.py
```

Generated tests exercise source preservation, idempotence, validation before
writes, unsafe/unsupported sources, dependency availability, install failure and
post-install failure. They do not invoke APT or replace actual Linux evidence.
All 32 focused tests pass. The final local suite passes 2,080 tests with four
optional skips and the existing Starlette/httpx deprecation warning. Ruff and
format verification pass across 185 Python files; dependency, UTF-8/LF,
local-link and whitespace checks pass. A structural comparison confirms that
only the three dependency-preparation steps changed in the workflow, with all
other workflow semantics preserved. Original local test lifetimes are checked
independently after their execution session exits.
Required local checks and exact-head/main CI with full public package/both-image
delivery are recorded on the owning issue. Pending hosted results are not
inferred from Windows tests. No old failed workflow is rerun and no automatic
annotation accuracy or model promotion follows from these software checks.
