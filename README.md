# 1916 Boston Directory · Volume 1 OCR package

**Your task: Volume 1, 1,371 selected physical pages, in 14 resumable batches.**
This package contains only the Volume 1 assignment. Volume 2 is handled
separately. No OCR starts when you download, install or inspect this package.

The selected model is **Tesseract 5.3.4 + pinned English tessdata_best**, OEM 1,
full-page PSM 3, grayscale/2× Lanczos/10 px border. One sequential worker uses
`OMP_THREAD_LIMIT=1`. Weights and page images download automatically as needed.

## 1. Install once

Open a terminal **inside this package folder**. With Conda or Miniforge available:

```sh
conda env create --prefix .runtime/env --file fa26/environment.yml
conda run --prefix .runtime/env python -m pip install -e ./fa26
conda run --no-capture-output --prefix .runtime/env python run_ocr.py --check
```

The check validates versions and downloads/verifies the English weights; it does
not recognize pages. macOS and Linux use these commands. On Windows, use WSL2
and install Conda inside WSL, then run the same commands. Native macOS arm64 has
been tested; Linux/WSL execution still needs the environment check on your machine.

## 2. Start your queue

```sh
conda run --no-capture-output --prefix .runtime/env python run_ocr.py
```

Leave the machine awake and connected while processing. The runner downloads
only selected pages, saves each attempt, and moves through all 14 batches.
No edits to source code, page ranges or model parameters are needed.

To try only the next unfinished batch, add `--max-batches 1`. To inspect the
assignment without installing dependencies or starting OCR:

```sh
python3 run_ocr.py --dry-run
```

## 3. Resume or check progress

Ctrl-C retains completed pages and the interrupted attempt. Run the same start
command again, from the same folder with the same result path, to resume.
Keep the package code unchanged during a run; execution fingerprints are checked.

```sh
conda run --no-capture-output --prefix .runtime/env python run_ocr.py --status
```

Progress and live console output are also saved in:

```text
results/worker-vol1/status.json
results/worker-vol1/coverage.csv
results/worker-vol1/runner.log
```

An alternative storage location can be selected before starting:
`python run_ocr.py --data-dir /path/to/persistent-data`. Reuse that path
for subsequent runs. Moving active checkpoints requires a reviewed migration.

## 4. Handle flagged pages

The queue continues after recorded page failures or quarantine. Exit code **2**
means processing has finished with pages needing review; inspect `coverage.csv`.
Exit 130 means interrupted; exit 1 means a setup/configuration/command failure.
Incomplete batches remain visible in status output.

Printed p516 / leaf 518 previously showed cross-column merging and should be
quarantined if reproduced. Preserve its raw outputs and reason. The program
does not correct OCR strings or reconstruct entries. Accepted captures still
need text/layout review; line counts and word confidence are not resident counts
or accuracy scores.

## 5. Return the results

Share the **complete `results/worker-vol1/` folder** through the team's chosen
data storage. It includes:

- `status.json`, `coverage.csv`, `runner.log`: overall progress and issues.
- `batches/`: per-batch checkpoints, accepted/quarantined lines, flags and receipts.
- `work/source/`, `work/runs/`: checked source JPEGs and native TXT/TSV/HOCR outputs.

Git tracks this small code/manifest package. Generated results, environments,
downloaded weights and page images are ignored. Preserve the relative folder
structure so the team can audit and re-evaluate saved outputs.

## Exact scope and package contents

Volume 1 includes **1,370 primary pages + one supplementary page**. Scanned leaves
162–1534 are selected except inserted ad scans 781/782. Printed p160 is the
supplementary additions/removals page; p161 mixes abbreviations and directory
text. The absent printed labels 775–778 remain documented source gaps.

The master page list is `fa26/plans/1916/pages.csv`; `project.json` pins all 14
batch plans. Page identity always includes the volume and scanned leaf, rather
than relying on printed labels. Detailed source scope is in
`fa26/manifests/vol1/README.md`.

This bundle contains source code, environment specification, source snapshots,
fixed model settings and assignment plans. Historical comparisons, old pilots,
cached images/weights and previous OCR results are excluded. `CHECKSUMS.json`
checks bundle integrity at startup. The development pipeline passed 36 offline
tests; the exported bundle is also checked after ZIP extraction.
