# Offline shuttle label revision comparison

The comparator is the generated-input-only implementation prerequisite from
[#221](https://github.com/Ken0u/badminton-match-analyzer/issues/221) to proposed
[corpus comparison #220](https://github.com/Ken0u/badminton-match-analyzer/issues/220).
It compares explicit, pinned local CSVs. It never downloads labels, opens media,
loads models, trains, repairs annotations or changes application truth.
Its software tests establish accounting behavior, not badminton accuracy.

The existing importer prepares a single publication. It does not compare label
revisions. Before this implementation, nine generated comparison outcomes were
frozen on the owning issue: unchanged labels, changed labels, unknown visibility,
missing tail, duplicates, reversal, conflicting basis, absent original and an
invalid ordinal. Original research inputs and earlier eligibility gates remain
unchanged. No real corpus comparison or model improvement is reported here.

The frozen nine-case generated measurement retains all nine cases: three have
declared-frame comparisons and six are explicitly unscored. It preserves 23
known original records across eight cases, one original case with an unknown
record count, and all 27 revised records across nine cases. The changed case
reports both directions of visibility change and one changed both-visible
coordinate pair; the unknown-visibility case keeps its unscored pair in the
denominator. Every pre-frozen expected outcome passes. The focused suite also
checks input/output preservation, failure bounds, CLI behavior and decimal
changes below float resolution. These are generated software measurements only.

## Inventory and declared correspondence

Run `python scripts/compare_shuttle_labels.py --help` from a source checkout, or
`python -m badminton.shuttle_label_comparison --help` from an installed package.
The module includes its protocol, so it does not require a repository-relative
manifest at runtime. The matching public
[protocol v1](../data/manifests/shuttle_label_comparison_protocol_v1.json)
is independently inspectable in Git. Every report binds its canonical encoded
protocol and exact inventory bytes with SHA256.

The inventory is strict JSON with exactly `schema_version: 1` and a nonempty
`cases` list. Every case has exactly these fields:

| Field | Meaning |
| --- | --- |
| `case_id` | Unique opaque ID, 1–128 ASCII letters, digits, underscores, dots or hyphens; starts with a letter or digit. |
| `original`, `revised` | File descriptor, or JSON `null` for an explicitly unavailable side. |
| `quarantine_reasons` | List of distinct reason codes using the same spelling rules as IDs. An existing quarantine must be preserved here. |

A descriptor contains exactly `path`, `sha256` and `basis`. The path is a portable
relative `.csv` path under `--inputs-root`, with ASCII letters, digits, spaces,
underscores, dots and hyphens in components. Absolute paths, traversal, Windows
device names, trailing dots/spaces, alternate streams and links are rejected or
reported unavailable. No directory discovery, archive extraction or filename
alias mapping occurs. A changed SHA256 is reported without parsing those bytes.
All inventory fields are validated before any CSV is opened.

`basis` is either `null` or an object with exactly:

| Field | Meaning |
| --- | --- |
| `source_sha256` | Caller-declared native source identity, lowercase SHA256. |
| `evidence_sha256` | Caller-declared evidence supporting that side's mapping, lowercase SHA256. |
| `frame_count` | Positive integer native frame count, at most 1,000,000,000. |
| `width`, `height` | Positive integer source dimensions, at most 1,000,000. |
| `ordinal_origin` | Integer; only zero is supported for frame comparisons. |
| `rotation` | Integer; only zero is supported by this protocol. |
| `coordinate_space` | String; only `source_pixels` is supported. |

Comparisons require matching supported bases on both sides. The two evidence
hashes may differ, but source hash, count, dimensions and conventions must match.
This is a **caller declaration**, not independently verified source alignment.
The tool does not read the source or evidence files. Matching names or bytes
cannot supply a missing basis, resolve ambiguous clip IDs, prove original-match
identity, or remove a quarantine. A future corpus run must establish those
facts through its separately frozen provenance/access protocol.

## Parsing, denominators and unscored cases

CSV columns must be exactly `Frame,Visibility,X,Y`. UTF-8 with an optional BOM
and CSV newline conventions are accepted. Blank records are counted; malformed
records remain in `record_count`. Ordinals are decimal integers with at most 18
digits, without signs, whitespace or exponent notation. They are never shifted.
Repeated ordinals are all counted, including duplicate excess and affected
record counts. Reversal detection spans invalid ordinal records.

Flags `0` and `1` mean published not-visible and published visible. Other flags
remain unknown. Both coordinates must be finite; visible coordinates must be
within the declared source dimensions. A not-visible row with nonzero
coordinates is inconsistent and unscored. Coordinates use exact decimal numeric
equality with no tolerance, rescaling or float rounding. `1.0` and `1.00` are
equal numeric values; small represented decimal differences remain differences.

Each report preserves every inventory case. Its output separates:

- `byte_equal`: equality of the two SHA256-verified byte strings, including
  unparseable CSVs. It is `null` if either pinned input was unavailable/changed.
- `ordinal_inventory`: the union, intersection and each side's exclusive
  distinct syntactically valid ordinals. This is raw ordinal accounting, even
  when native correspondence is unknown; duplicates are reported separately.
- Per-side records, invalid/duplicate ordinals, reversals, issues, missing native
  ordinals and unlabelled tail counts. Native counts require a supported basis.
  Tail count is the suffix after the last present in-range ordinal; interior
  gaps are counted separately by total missing ordinals.
- `comparison`: declared native frame pairs, usable visibility pairs,
  unscored pairs, visibility transitions, both-visible coordinate pairs and
  changed coordinates. Known visibility pairs plus unscored pairs equal the
  declared pair denominator. Coordinate changes use the both-visible usable
  coordinate-pair denominator, not all rows or frames.

Incomplete native coverage, duplicate/reversed/invalid/out-of-range ordinals,
unsupported schemas, existing quarantines, unavailable sides or incompatible
bases withhold the **entire case comparison**. Original counts and raw ordinal
inventory remain available when parseable. In a structurally complete case,
unknown visibility or invalid coordinates withhold the affected pair without
removing it from the pair denominator.

Unparsed, over-limit or unavailable files have `record_count: null`, not zero.
Summary `known_records` is only the total of known counts; its accompanying
`unknown_record_count_cases` states how many case sides remain unknown. The
summary always satisfies `compared_cases + unscored_cases == cases`. Reason
counts can overlap and must not be summed as disjoint cases. Reports export no
per-row coordinates, ordinal lists or raw label values.

No visibility agreement is expert negative truth. No revision difference is a
model error or a model accuracy score. Every report retains false
`training_allowed`, `independent_test_allowed`, `model_deployment_allowed` and
`dataset_redistribution_allowed` flags. Matching labels cannot grant data rights,
establish source independence or unlock training.

## Bounds and publication

Fixed protocol limits are 512 cases, 1 MiB inventory, 16 MiB per CSV,
64 MiB total CSV bytes read, 200,000 records per CSV, and 2 MiB encoded report.
No command-line option expands these bounds. Reads use regular local files and
check size/mtime before and after. Changed reads consume their byte budget even
though their records are unavailable. Hashes bind actual bytes read. These
checks detect observed changes; they do not provide an adversarial filesystem
snapshot or independent provenance verification.

The output parent must already exist. A complete aggregate file is flushed and
published using a no-replacement hard link in the same directory. Existing files,
including inputs, are never overwritten. Interrupted writes leave no partial
final report. The filesystem must support hard links; unsupported publication
fails without replacing anything. Inventory/schema failures exit with code 2
without a report. A successfully published report, including explicit unscored
cases, exits with code 0. Runs are deterministic for unchanged inventory, inputs
and observations; no timing field changes the report bytes.

## Runnable generated example

Create an empty scratch directory under `.cache/`, save this Python example there,
and run it with the project environment. It creates generated CSVs and a fresh
inventory only; its fake source and evidence hashes make no scientific claim.

```python
import hashlib
import json
from pathlib import Path

root = Path('.cache/comparison-example')
root.mkdir(parents=True, exist_ok=False)
original = b'Frame,Visibility,X,Y\n0,1,5,8\n1,0,0,0\n'
revised = b'Frame,Visibility,X,Y\n0,1,6,8\n1,0,0,0\n'
basis = {
    'source_sha256': hashlib.sha256(b'generated source').hexdigest(),
    'evidence_sha256': hashlib.sha256(b'generated declaration').hexdigest(),
    'frame_count': 2, 'width': 1280, 'height': 720,
    'rotation': 0, 'ordinal_origin': 0, 'coordinate_space': 'source_pixels',
}
def descriptor(name, raw):
    (root / name).write_bytes(raw)
    return {'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'basis': basis}
inventory = {'schema_version': 1, 'cases': [{
    'case_id': 'generated', 'original': descriptor('a.csv', original),
    'revised': descriptor('b.csv', revised), 'quarantine_reasons': [],
}]}
(root / 'inventory.json').write_text(json.dumps(inventory), encoding='utf-8')
```

```text
python scripts/compare_shuttle_labels.py --inventory .cache/comparison-example/inventory.json --inputs-root .cache/comparison-example --output .cache/comparison-example/report.json
```

Expected: one compared case, two declared native frame pairs, two visibility
pairs, one both-visible coordinate pair and one coordinate change. A second
invocation with the same output refuses to overwrite the first report.

Actual #220 execution still needs original corpus/index/declaration hashes and
access on their real host, applicable rights evidence, resolved or explicitly
quarantined filename correspondence and a separate committed grant. Existing
quarantines, original labels and all unknowns must remain preserved. No source
images, real annotation CSVs, weights or holdouts were used for this increment.
