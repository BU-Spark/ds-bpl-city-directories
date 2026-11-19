# 1916 Boston Directory · Vol. 1 (A–O)

Portable **Python CLI + Tesseract on CPU** for source-traceable directory OCR.
Start here; `bpl-ocr` is the single active entry point. No Colab is required.

## Progress

| Stage | Status | Evidence / next task |
| --- | --- | --- |
| Model selection and cleanup | Complete | [Five-model evidence](archive/model_comparison/README.md) |
| 1. Source scope and manifest | Complete, with recorded source gaps | [Scope and pagination findings](manifests/vol1/README.md) |
| 2. Environment and single-page CLI | Complete on macOS arm64 | [Real page-162 run](examples/leaf0164/README.md) |
| 3. Diverse 10–20 page review | Next | Columns, margins, line boundaries and reading order |
| 4. Batch/recovery validation | Planned | 50–100 pages, interruption, retries and resource sampling |
| 5. Full A–O OCR | Planned | Every target page accounted for; report gaps and failures |
| 6. OCR delivery | Planned | Documented data package for entry extraction |

**Full-volume OCR is not complete.** The CLI currently recognizes one explicitly
requested scanned leaf per invocation. Batching and automatic continuation are
stage 4; entry parsing and geocoding are later work.

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
the Python project separately installs its pinned Pillow wheel.

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

## Layout and outputs

```text
fa26/
  config/vol1.json             Source scope and fixed settings
  manifests/vol1/              Source snapshots, page inventory and scope checks
  src/bpl_ocr/                 Active Python implementation and CLI
  tests/                      Offline integrity/failure tests
  examples/leaf0164/           One real new CLI run for review
  archive/model_comparison/   Completed experiment evidence, read-only
  work/                      Local downloads, weights and runs; ignored by Git
```

Each invocation creates `work/runs/<volume>/<run_id>/` with:

- `raw/page.txt`, `raw/page.tsv`, `raw/page.hocr`: exact native outputs.
- `raw/stderr.txt`, `raw/stdout.txt`: engine logs.
- `lines.csv`: text, original-JPEG boxes, native reading order, IDs and sources.
- `run.json`: source/config/code hashes, actual build/hardware, output checksums,
  stage timings and completed/empty/failed/interrupted status.

Source images and weights are cached, but OCR outputs are not overwritten or
silently skipped. Failed attempts retain their records. Automatic retry/resume
and sampled peak RAM are not implemented yet.

Line boxes are unions of recognized word boxes, transformed back from the
2×/10 px bordered image. Raw TSV/HOCR keep processed-image coordinates.
`reading_order` preserves native TSV encounter order and is not verified column
order. IDs belong to the page and settings; changes to code/build/segmentation
can change IDs. `mean_word_confidence` averages nonnegative word scores on a
0–100 scale; it is **not accuracy**. `line_scope` marks the mixed first-page
abbreviation area but does not classify all margins or individual entries.

The new ARM/native-library build is not byte-identical to historical Colab.
The one-page example validates execution; stage 3 must verify cross-page quality.

## Validation

```sh
conda run --prefix .runtime/env python -m unittest discover -s fa26/tests -v
```

Tests cover pagination/index differences, ads and supplementary scope, offline
rebuilds and hashes, accidental PSM 7, TSV quote/column order, inverse coordinates,
source corruption, failed processes and the evidence/example checksums. Tests do
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
and new production scans/results are ignored. Choose the team's shared data
location before stage 4; an ignored local directory alone does not share data.

The duplicate two-model package and Colab entry points were retired. The
[comparison archive](archive/model_comparison/README.md) retains all five outputs,
seven scans, raw responses, settings, method and qualitative findings.
Teammate `scripts/api_look.ipynb` and original IA text under
`data/1916 Boston Directory Vol. 1 (A–O)/` remain unchanged as reference materials.
Project documents and presentations are maintained in the parent workspace.

Reference: [Tesseract outputs and PSM](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html).
