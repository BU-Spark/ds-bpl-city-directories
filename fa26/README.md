# 1916 Boston Directory · Vol. 1 (A–O)

Portable **Python CLI + Tesseract on CPU** for source-traceable directory OCR.
Start here; `bpl-ocr` is the single active entry point. No Colab is required.

## Progress

| Stage | Status | Evidence / next task |
| --- | --- | --- |
| Model selection and cleanup | Complete | [Five-model evidence](archive/model_comparison/README.md) |
| 1. Source scope and manifest | Complete, with recorded source gaps | [Scope and pagination findings](manifests/vol1/README.md) |
| 2. Environment and single-page CLI | Complete on macOS arm64 | [Real page-162 run](examples/leaf0164/README.md) |
| 3. Diverse 10–20 page review | Complete with conditions | [16-page review and evidence](quality/stage3/README.md) |
| 4. Batch/recovery validation | Complete with conditions | [60 captures; 59 accepted, p516 quarantined; recovery/resources](quality/stage4/README.md) |
| 5. Full A–O OCR | Planned | Every target page accounted for; report gaps and failures |
| 6. OCR delivery | Planned | Documented data package for entry extraction |

**Full-volume OCR is not complete.** The CLI supports individual pages and fixed
1–100-page batch plans with automatic continuation. Entry parsing and geocoding
are later work.

Stage 3 checked 16 pages / 3,681 native rows, 16 full-page overlays and 96 spatial
bands. Both directory columns were represented; local text loss, broken surname
headings, ditto pseudo-lines and detached suffixes remain. Stage 4 validates a
bounded capture/batch pilot. See the review for evidence, source
access aliases and the conditions before entry extraction.

## Source and baseline

The [source inventory](manifests/vol1/pages.csv) covers 1,544 scanned leaves:
**1,370 primary directory pages + one supplementary additions/removals page**
are selected for future OCR; 173 other scans are excluded. The primary section
runs from printed p161 to p1534. Absent printed labels 775–778 and two inserted
advertisements are documented in the [scope notes](manifests/vol1/README.md).
Primary inclusion is not resident inclusion: firms, deaths and removals also
appear in the general directory. A detected OCR line is not one person.

Selected configuration: **Tesseract 5.3.4, English tessdata_best, OEM 1,
full-page PSM 3**, grayscale, 2× Lanczos, 10 px white border; Pillow 11.3.0.
[config/vol1.json](config/vol1.json) pins the English-model revision and SHA-256.
The CLI checks versions and weights. No extra thresholding, denoising, field
parsing or text correction is applied.

## Setup

Run from the repository root. Conda installs Python and the native OCR engine;
the Python project separately installs pinned Pillow and psutil wheels. psutil
samples worker/child memory and CPU; it does not change OCR preprocessing.
The runner targets macOS and Linux (Windows users can use WSL). Only macOS arm64
has been exercised here; batch locks require a filesystem honoring POSIX locks.

```sh
conda env create --prefix .runtime/env --file fa26/environment.yml
conda run --prefix .runtime/env python -m pip install -e ./fa26
conda run --prefix .runtime/env bpl-ocr --help
```

Mamba/Micromamba can use the same specification. For Micromamba, use
`micromamba create --yes --prefix .runtime/env --file fa26/environment.yml`
and `micromamba run --prefix .runtime/env ...` for commands.
This workspace was validated using Micromamba 2.3.3; the local executables
`.runtime/bin/micromamba` and `.runtime/env/bin/bpl-ocr` are already available.
They are ignored by Git and are not required in a fresh checkout.

[environment.yml](environment.yml) specifies the cross-platform dependencies.
[locks/osx-arm64.explicit.txt](locks/osx-arm64.explicit.txt) additionally pins
all 39 native package builds and SHA-256s used on this Mac. Another Apple Silicon
Mac can pass that explicit file to the environment creation command, then
install the Python project. Linux uses the environment specification and records
its native-library build; Linux execution has not yet been validated.

## Commands

Build the manifest from checked-in source snapshots, without network access:

```sh
conda run --prefix .runtime/env bpl-ocr manifest --config fa26/config/vol1.json --output fa26/manifests/vol1 --offline
```

Check versions and download/verify the pinned English weights:

```sh
conda run --prefix .runtime/env bpl-ocr doctor --config fa26/config/vol1.json --work-dir fa26/work
```

Recognize **one page**: printed 162 = scanned leaf 164 = BookReader n163.

```sh
conda run --prefix .runtime/env bpl-ocr ocr-page --manifest fa26/manifests/vol1/manifest.json --leaf 164 --work-dir fa26/work
```

`--leaf` means IA scandata `leafNum`, never the printed page or reader n-index.
Out-of-scope leaves are rejected. Each requested JPEG is fetched at the native
processed-JP2 crop width; actual dimensions and its SHA-256 receipt are checked.
The full JP2 ZIP is not downloaded. Historical OCR text never enters recognition.

Use `manifest --refresh` instead of `--offline` to intentionally refresh public
metadata; review the changed manifest. Both `doctor` and `ocr-page` accept
`--tesseract /path/to/tesseract` when the binary is outside the active environment.
Commands also work as `python -m bpl_ocr` after installing the project.

Rebuild offline pilot diagnostics and source-review figures from saved runs:

```sh
conda run --prefix .runtime/env bpl-ocr review --runs fa26/work/stage3/pilot_runs.json --manifest fa26/manifests/vol1/manifest.json --output fa26/quality/stage3 --images
```

`review` does not run OCR or change native text. It validates provenance and
exports candidate flags for visual/contextual review. The 16-page plan and
committed review artifacts are in [quality/stage3/](quality/stage3/README.md).

Run or resume the fixed stage-4 batch:

```sh
OMP_THREAD_LIMIT=1 conda run --no-capture-output --prefix .runtime/env bpl-ocr batch --manifest fa26/manifests/vol1/manifest.json --plan fa26/quality/stage4/plan.json --work-dir fa26/work --batch-dir fa26/work/stage4/new-batch
```

Repeat the same command and directories to continue. `--max-pages 10` pauses
after scheduling ten additional leaves; Ctrl-C also retains the current attempt.
Completed pages are hash-checked before being reused, including a native run
that finished before its checkpoint was written. A changed plan, code, engine,
runtime control or work directory requires a new batch directory. Permanent
failures and quarantine are retained for review, rather than retried forever.
Exit codes are 0 for completed/intentional pause, 2 for pages needing attention,
130 for interruption and 1 for a command/configuration failure.

Re-evaluate saved stage-4 captures using current QA, without OCR:

```sh
conda run --prefix .runtime/env bpl-ocr batch-review --manifest fa26/manifests/vol1/manifest.json --work-dir fa26/work --batch-dir fa26/work/stage4/batch --output fa26/work/stage4/review
```

This leaves the original checkpoint/native outputs intact and applies new QA
to old code-pinned captures. The measured capture predates the p516 diagnostic
correction; use this command for its current assessment. Exit 2 indicates the
quarantine. All 14,329 native rows are retained: 14,176 accepted and 153 separated
into `quarantined_lines.csv`.

The batch plan bounds network/engine retries and timeouts. Canonical IIIF is
preferred; timeouts can fall back to the exact JP2 archive member through the
official BookReader, recording request/final URLs, dimensions and hashes. The
JPEG renderings are not assumed byte-identical. Integrity/geometry failures
are quarantined. Diagnostic flags accompany every exported native row without
editing, deleting or reordering text. A `completed` capture still has
`quality_status=review_required`.

## Layout and outputs

```text
fa26/
  config/vol1.json             Source scope and fixed settings
  manifests/vol1/              Source snapshots, page inventory and scope checks
  src/bpl_ocr/                 Active Python implementation and CLI
  tests/                      Offline integrity/failure tests
  examples/leaf0164/           One real new CLI run for review
  quality/stage3/             Cross-page diagnostics, visual anchors and evidence
  quality/stage4/             Fixed batch plan and small validation report
  archive/model_comparison/   Completed experiment evidence, read-only
  work/                      Local downloads, weights and runs; ignored by Git
```

Each page attempt creates `work/runs/<volume>/<run_id>/` with:

- `raw/page.txt`, `raw/page.tsv`, `raw/page.hocr`: exact native outputs.
- `raw/stderr.txt`, `raw/stdout.txt`: engine logs.
- `lines.csv`: text, original-JPEG boxes, native reading order, IDs and sources.
- `run.json`: source/config/code hashes, actual build/hardware, output checksums,
  stage timings, sampled resources and completed/empty/failed/interrupted status.

Source images and weights are cached, but OCR outputs are not overwritten or
silently skipped. Failed attempts retain their records. The batch directory
adds an atomic `checkpoint.json`, coverage `pages.csv`, `attempts.csv`, merged
`lines.csv`, separate `quarantined_lines.csv`, `line_flags.csv`, full
`run_records.json` and `summary.json`.
An OS lock prevents two workers from writing the same batch. Use one worker per
work directory; concurrent batches must use separate work directories.

Resource samples are taken every 0.1 s by the pilot: summed worker/descendant
RSS counts shared memory more than once, can miss short peaks and is not whole
host RAM. Sampled CPU seconds are a lower bound. Per-attempt timings include
source preparation; measured session time covers the capture loop and excludes
startup revalidation, final merged exports and time between invocations.

Line boxes are unions of recognized word boxes, transformed back from the
2×/10 px bordered image. Raw TSV/HOCR keep processed-image coordinates.
`reading_order` preserves native TSV encounter order and is not verified column
order. IDs belong to the page and settings; changes to code/build/segmentation
can change IDs. `mean_word_confidence` averages nonnegative word scores on a
0–100 scale; it is **not accuracy**. `line_scope` marks the mixed first-page
abbreviation area but does not classify all margins or individual entries.

The new ARM/native-library build is not byte-identical to historical Colab.
The one-page example validates execution; the stage-3 review documents observed
cross-page limits. Its flags are non-destructive candidates, not automatic text
filters or new accuracy scores. Entry reconstruction still needs later work.

## Validation

```sh
conda run --prefix .runtime/env python -m unittest discover -s fa26/tests -v
```

Tests cover pagination/index differences, ads and supplementary scope, offline
rebuilds and hashes, accidental PSM 7, TSV quote/column order, inverse coordinates,
source corruption, failed processes, asymmetric review columns, conservative
symbol/order flags, bounded retries, native timeouts/child cleanup, single-writer
locks, checkpoint recovery, tampered-run quarantine and evidence checksums. Tests do
not replace real OCR or the team's separate ground-truth evaluation.

## Optional container

The [Dockerfile](Dockerfile) follows the upstream
[Micromamba container workflow](https://micromamba-docker.readthedocs.io/en/latest/quick_start.html).
Docker is not installed on this Mac, so the container is **not build-tested**.
Target Linux/amd64 for this historical Tesseract release:

```sh
docker build --platform linux/amd64 -f fa26/Dockerfile -t bpl-ocr .
docker run --rm --platform linux/amd64 bpl-ocr --help
```

For recognition, mount a writable data directory and pass its container path
as `--work-dir` so downloads and results persist.

## Git and shared data

Commit code, configuration/environment, manifests, docs, tests, the small CLI
example and the comparison evidence. `.runtime/`, `fa26/work/`, model weights
and new production scans/results are ignored. Stage 4 uses ignored local storage;
`--work-dir` and `--batch-dir` can point to a shared mount. Choose and copy the
team's durable data location before full-volume capture; Git alone does not
share the source cache or native results. A batch pins its resolved work path,
so relocating an existing checkpoint requires a reviewed migration rather than
silently reading a different directory.

The duplicate two-model package and Colab entry points were retired. The
[comparison archive](archive/model_comparison/README.md) retains all five outputs,
seven scans, raw responses, settings, method and qualitative findings.
Teammate `scripts/api_look.ipynb` and original IA text under
`data/1916 Boston Directory Vol. 1 (A–O)/` remain unchanged as reference materials.
Project documents and presentations are maintained in the parent workspace.

Reference: [Tesseract outputs and PSM](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html).
