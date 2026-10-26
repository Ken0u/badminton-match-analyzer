# ETH shuttle supervision: observed inventory and acquisition prerequisites

Observed October 26, 2026 under [#319](https://github.com/Ken0u/badminton-match-analyzer/issues/319),
following the [five-source qualification](SUPERVISION_SOURCE_DISCOVERY_REPORT.md).
**Acquisition and training readiness remain unestablished.** The release exposes
candidate detection-image filenames, but applicable dataset/media terms and
original-source correspondence remain unresolved. No images, annotation rows,
videos or weights were downloaded; complete scientific rally references remain
**0/2**. The [machine-readable inventory](eth-supervision-inventory.json) preserves
every request, denominator, unqueried branch and readiness limitation.

## Actual metadata coverage

The [public processed folder](https://drive.google.com/drive/folders/1neBfC7-Fp-l53muxZiIbIET6lYH5xv9s)
lists 73 root entries, including 36 folders. The 33 named background/difficulty
folders expand to 11 base names and 66 image/label containers. COCO and `old`
subtrees were excluded; `.DS_Store` and sorting-progress file contents were not
read. Root YAML filenames are observed metadata; their contents were not fetched.

The hard request limit was reached: **160 requests / 17,639,849 response bytes**,
comprising 151 folder pages and nine creator text/code responses. Every response
was HTTP 200 and below the 2 MiB body bound; the largest was 2,019,873 bytes.
No redirects, credentials or network retries were used. The first selector also
matched the two COCO `easy` folders; its root-shape guard stopped before any child
request. The corrected continuation reused that exact saved response. This
diagnostic and both producer scripts remain preserved locally.

Of 132 advertised train/val leaf folders, **51 were queried and 81 remain
unqueried**. Twelve difficulty variants have all four leaf listings, one has
three, and 20 have none. All 25 queried `val` listings contain zero entries.
This establishes observed metadata counts, not an exhaustive release census.

| Background name | Difficulty image lists queried | JPG names observed | Numeric filename span | Unobserved integers within that span |
| --- | ---: | ---: | --- | ---: |
| `cab_1` | 3/3 | 2,296 | 0–4051 | 1,756 |
| `cab_2` | 3/3 | 3,406 | 0–4871 | 1,466 |
| `glc_1` | 3/3 | 2,501 | 0–3256 | 756 |
| `glc_2` | 3/3 | 1,648 | 0–3721 | 2,074 |
| `ml_3` | 1/3 | 606 | partial; not combined | not determined |
| Six remaining background names | 0/3 each | not queried | not determined | not determined |

The 13 queried train pairs contain **10,457 JPG names and 10,458 TXT names**.
There are 10,457 matching stems and one observed orphan:
`cab_2_medium/labels/train/cab_2_00164.txt`. Its matching image name is absent
from the queried medium, easy and hard image listings, with no duplicate label
name in the other two variants. No actual file bytes or native-frame absence
were verified. Matching names do not establish correct bounding boxes.

Numeric filename gaps are metadata observations, not source-time measurements
or negative visibility labels. All three difficulty lists were inspected for
the first four backgrounds; no repeated image names appeared between their
difficulty sets. Distinct filenames still do not prove independent physical
events or absence of duplicate image content.

## Source meaning and intended use

The [creator paper](https://arxiv.org/html/2603.06691v2), methods section and
figure, reports 20,510 frames across 11 backgrounds/five locations, recorded at
1920×1200 and nominal 60 fps. Its introduction instead says 11 locations; the
inventory preserves that discrepancy. The intended domain is egocentric robot
perception, with stationary-camera annotation footage and separate qualitative
moving-camera demonstrations. Broadcast transfer is unverified.

The paper describes automatic box proposals followed by checking/correction and
explicitly excludes invisible-shuttle frames. Thus adjacent released images
cannot automatically supply adjacent native frames, an exact clock or absence
labels. These are author-described properties, not independent label-quality
measurements.

The [pinned converter](https://github.com/leggedrobotics/shuttle_detection/blob/745a82916e919313e6db319a12ea873082192666/src/shuttletrack/convert_labels.py)
routes three corrected difficulty classes from a common named input into
separate folders, rewrites class IDs to zero and stores selected images/labels
under `train`. It creates empty `val` directories and emits no native-PTS map.
Actual annotation schema/coordinates and file dimensions were not read.

The [README](https://github.com/leggedrobotics/shuttle_detection/blob/745a82916e919313e6db319a12ea873082192666/README.md)
explains that `train` is storage for configurable splits. The
[default configuration](https://github.com/leggedrobotics/shuttle_detection/blob/745a82916e919313e6db319a12ea873082192666/src/shuttletrack/config.py)
puts all 11 backgrounds and COCO training data in TRAIN with empty VAL/TEST;
easy/medium are its training difficulties. The
[combination utility](https://github.com/leggedrobotics/shuttle_detection/blob/745a82916e919313e6db319a12ea873082192666/src/shuttletrack/combine_datasets.py)
can split individual files within a source YAML. Neither defaults nor directory
names establish the paper's separate background/location holdout experiments.
Dedicated cross-validation scripts are listed in the tree but were not fetched.
Keep coupled difficulty variants together provisionally; original recording,
cross-corpus overlap and upstream checkpoint membership remain unverified.

## Terms, outcome and verification

The README states AGPLv3 for the project due to Ultralytics. The pinned
[LICENSE](https://github.com/leggedrobotics/shuttle_detection/blob/745a82916e919313e6db319a12ea873082192666/LICENSE)
and inspected creator pages provide no explicit dataset/media grant for the
external Drive release. A paper distribution license does not resolve that
external scope. This finding is limited to inspected material, not a conclusion
about permission beyond it.

The concrete next prerequisite is explicit applicable dataset/media terms.
Any later acquisition also needs an original-source map, byte/schema checks,
retained missing/unpaired cases and overlap accounting. Temporal/event use
additionally needs source clocks and a map of retained and omitted frames.
No acquisition or scientific-use authorization follows from this inventory.

Two separate read-only audits inspected creator claims/code and independently
reconciled retained HTML, hashes, ancestry, coverage and filename pairing.
Required local checks and exact PR/main/controller/public-delivery evidence are
recorded on the owning issue. No scientific image assessment, inference,
training, consumed holdout access or model promotion occurred. Existing
eligibility flags and the unproven full-match accuracy status are preserved.
