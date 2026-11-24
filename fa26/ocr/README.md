# 1916 directory · selected Tesseract runner

Run **Volume 1 only: 1,371 physical pages in 14 resumable batches**. This folder
is the minimal OCR addition to the shared `dev` codebase. Model-comparison
archives, old pilots, notebook environments and Volume 2 jobs remain separate.

## Setup from the repository root

The existing `fa26/requirements.txt` is empty and does not define a shared Python
environment. This runner supplies a small reproducible OCR profile. Existing
notebooks and ground-truth workflows keep their current setup.

```sh
conda env create --prefix .runtime/ocr --file fa26/ocr/environment.yml
conda run --prefix .runtime/ocr python -m pip install -e ./fa26/ocr
conda run --no-capture-output --prefix .runtime/ocr python fa26/ocr/run_ocr.py --check
```

The profile uses Python 3.11 and native **Tesseract 5.3.4**; Python dependencies
are **Pillow 11.3.0 and psutil 7.0.0**. The pinned English tessdata_best weights
are downloaded and SHA-256 checked by `--check`. It does not recognize pages.
No GPU, torch, pytesseract or notebook analytics packages are required.
macOS arm64 has been exercised. Linux/Windows via WSL2 use the same profile but
need the environment check on that machine; native Windows is not supported.

## Run, resume, or inspect

```sh
# All 14 batches; rerun the same command to resume.
conda run --no-capture-output --prefix .runtime/ocr python fa26/ocr/run_ocr.py

# Optional: only the next unfinished batch.
conda run --no-capture-output --prefix .runtime/ocr python fa26/ocr/run_ocr.py --max-batches 1

# Progress without OCR.
conda run --no-capture-output --prefix .runtime/ocr python fa26/ocr/run_ocr.py --status

# Validate the assignment without installing dependencies or starting OCR.
python3 fa26/ocr/run_ocr.py --dry-run
```

The script locates its configuration relative to itself, so these commands work
from the repository root. One worker uses `OMP_THREAD_LIMIT=1`. Keep the machine
awake during capture. Ctrl-C retains the current attempt and completed pages.

The selected baseline stays English/OEM 1/PSM 3, grayscale/2× Lanczos/10 px border.
Captured strings and native reading order are preserved. Missing/corrupt outputs,
unresolved columns and systematic cross-column groups are quarantined; the queue
continues to later batches. Exit 2 means processing finished with review items;
exit 130 means interrupted; exit 1 means setup/configuration/command failure.
`completed` is an automated capture check, not verified transcription accuracy.

## Results and Git collaboration

Default output is **`fa26/ocr/results/worker-vol1/`**:

- `status.json`, `coverage.csv`, `runner.log`: overall status and issues.
- `batches/`: checkpoints, accepted/quarantined line CSVs, flags and receipts.
- `work/source/`, `work/runs/`: source JPEGs and native TXT/TSV/HOCR outputs.

A persistent external data root can be set with `--data-dir /path/to/data`.
Use the same path when resuming; existing checkpoints pin their work location.
Share the complete `worker-vol1/` data folder through the team's data storage.
Git carries the code, environment recipe and plans; generated data and weights
are ignored. The team's existing `fa26/results/` files are not changed or ignored.

This integration has `dev` as its base, so normal Git pull/push and PR workflows
apply. Only this folder, an entry link in `fa26/README.md`, local-runtime ignore
rules and one offline test module are added. There is no wholesale merge of the
research branch or unrelated-history standalone runner branch.

After the integration is available on the shared branch, teammates pull that
branch and use the commands above. Recreate/update the OCR environment when its
recipe changes. Unrelated notebook/ground-truth updates do not require reinstalling
OCR. During an active capture, leave the OCR code/configuration unchanged: package
checksums and execution fingerprints prevent mixing incompatible runs.

## Scope and files

The 1,371 selected scans comprise 1,370 primary pages and supplementary p160.
Ad leaves 781/782 remain excluded; the source gap in printed labels 775–778 is
retained. Printed p161 mixes abbreviations and directory text. Printed p516 /
leaf 518 previously showed cross-column merges and should remain quarantined
if reproduced. A raw line is not necessarily one person or one entry.

`plans/1916/project.json` pins the 14 batch plans. `manifests/vol1/manifest.json`
contains source URLs, page identities and scope flags. `config/vol1.json` pins
model/preprocessing settings. `src/` is the runtime; `CHECKSUMS.json` checks the
fixed run package. Source-scope rebuilding snapshots and experiment evidence
stay in the research branch. No OCR starts from cloning or installing this folder.
