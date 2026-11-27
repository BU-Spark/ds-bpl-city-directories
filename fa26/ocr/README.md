# 1916 directory · selected Tesseract runner

Capture the selected general directory pages with one CPU worker. Each volume
has one person responsible. Volume 1 has three sequential task groups; their
worker IDs describe tasks, not the number of people or machines.

| Volume | Assignment | Physical pages | Batches |
| --- | --- | ---: | --- |
| Volume 1 | `worker-1` | 500 | `vol1-001`–`vol1-005` |
| Volume 1 | `worker-2` | 500 | `vol1-006`–`vol1-010` |
| Volume 1 | `worker-3` | 371 | `vol1-011`–`vol1-014` |
| Volume 2 | `worker-vol2` | 566 | `vol2-001`–`vol2-006` |

Volume 1 defaults remain compatible with the shared worker commands. Volume 2
uses its own registry, `plans/1916/vol2-project.json`. The existing Volume-1
registry, project/plan IDs and core `src/bpl_ocr/` files are unchanged.

## Setup from the repository root

```sh
conda env create --prefix .runtime/ocr --file fa26/ocr/environment.yml
conda run --prefix .runtime/ocr python -m pip install -e ./fa26/ocr
```

The OCR profile uses Python 3.11, native **Tesseract 5.3.4**, Pillow 11.3.0 and
psutil 7.0.0. It is separate from the existing notebooks and ground-truth setup.
macOS arm64 has been exercised. Linux/WSL2 needs an environment check on that
machine; native Windows is not supported. No GPU is required.

The baseline is English `tessdata_best`, OEM 1, full-page PSM 3, grayscale,
2× Lanczos and a 10 px white border. There is no extra thresholding, denoising
or text correction. `--check` verifies the engine and downloads/checks pinned
English weights without recognizing pages.

## Inspect assignments without OCR

```sh
python3 fa26/ocr/run_ocr.py --list-assignments
python3 fa26/ocr/run_ocr.py --assignment worker-1 --dry-run
python3 fa26/ocr/run_ocr.py --volume vol2 --list-assignments
python3 fa26/ocr/run_ocr.py --volume vol2 --assignment worker-vol2 --dry-run
```

`--volume` defaults to `vol1`. Assignment IDs are checked against the selected
volume. Dry runs need only Python's standard library and create no result files.

## Bounded Volume-2 validation

Before production, check the environment and recognize only four fixed pages:
leaf **7, 288, 571 and 572** (first, interior, composite label and final page).

```sh
conda run --no-capture-output --prefix .runtime/ocr python fa26/ocr/run_ocr.py --volume vol2 --assignment worker-vol2 --check
python3 fa26/ocr/validate_vol2.py --dry-run
conda run --no-capture-output --prefix .runtime/ocr python fa26/ocr/validate_vol2.py --run --max-pages 2
conda run --no-capture-output --prefix .runtime/ocr python fa26/ocr/validate_vol2.py --run
python3 fa26/ocr/validate_vol2.py --status
```

The first recognition command stops after two pages; the next resumes the same
checkpoint. Repeating the completed command revalidates saved captures. All
validation output stays under **`fa26/ocr/results/validation-vol2/`**, with its
own `work/` and `batch/` directories. `--data-dir` can select another persistent
validation directory. This sample does not initialize or complete a production
assignment, and historical preflight results are not substituted for new runs.

## Production run and status

The following commands start full assignments. Run them when production is
intended, after validation. One person runs all three Volume-1 groups in sequence
to cover the complete volume:

```sh
conda run --no-capture-output --prefix .runtime/ocr python fa26/ocr/run_ocr.py --assignment worker-1
conda run --no-capture-output --prefix .runtime/ocr python fa26/ocr/run_ocr.py --assignment worker-2
conda run --no-capture-output --prefix .runtime/ocr python fa26/ocr/run_ocr.py --assignment worker-3

# Volume 2: six production batches.
conda run --no-capture-output --prefix .runtime/ocr python fa26/ocr/run_ocr.py --volume vol2 --assignment worker-vol2
```

Repeat the same command to resume. Add `--max-batches 1` to process only the next
unfinished batch. Read Volume-2 coverage without OCR:

```sh
conda run --no-capture-output --prefix .runtime/ocr python fa26/ocr/run_ocr.py --volume vol2 --assignment worker-vol2 --status
```

The script resolves its inputs relative to itself. One worker uses
`OMP_THREAD_LIMIT=1`. Keep the machine awake during capture. Ctrl-C retains the
current attempt and completed pages. Quarantined/failed pages remain visible
while the queue continues to later batches. Exit 2 means review items, 130 means
interrupted, and 1 means a setup/configuration/command failure.

## Results and collaboration

Default production output is `fa26/ocr/results/<assignment>/`, containing:

- `assignment.json`, `status.json`, `coverage.csv`, `runner.log`;
- `batches/` with checkpoints, accepted/quarantined rows, flags and receipts;
- `work/source/` and `work/runs/` with source JPEGs and native TXT/TSV/HOCR.

Use `--data-dir /persistent/data/root` for external storage. Reuse the same path
on resume: checkpoints pin the resolved work directory, engine/runtime controls,
plan and core code hashes. Leave those inputs stable during capture. New
Volume-2 support does not migrate checkpoints from the older `worker-vol1`
release into the current Volume-1 task groups.

Git carries code, fixed environment/configuration, manifests and plans. Share
complete result directories through team data storage; images, weights, logs
and generated OCR remain Git-ignored. Existing `fa26/results/` is unaffected.

## Scope and interpretation

Volume 1 includes 1,370 primary scans and supplementary p160. Ad leaves 781/782
are excluded; the printed-label gap 775–778 remains documented. P161 mixes an
abbreviation key with listings. Printed p516/leaf 518 previously showed merged
columns and remains subject to quarantine if reproduced.

Volume 2 uses IA item `bostonmassachuse19162112samp`: leaves **7–572**, printed
p1535–2144. Leaf **571** is one physical page labelled **2099–2143**. Leaf 573 /
p2145 starts the separate Boston Business Directory, which is excluded together
with later reference/advertisement material. The 1,516 accessible source pages
were checked against official BookReader data; the IIIF manifest request timed
out during that audit. The batch fallback pins the Volume-2 server/archive path.
The lower part of p2144 also contains "Removals, Additions, Etc." with personal
and firm notices. Capture retains the full physical page; later entry extraction
must distinguish this material from the main alphabetical listings.

Use `(volume_id, leaf_num)` across volumes. Preserve native strings and reading
order. `completed` describes automated capture checks; transcription accuracy
and reconstructed person entries require separate validation. OCR rows may
include firms, notices, headers, continuations and artifacts.

Run the offline regression suite from the repository root:

```sh
conda run --prefix .runtime/ocr python -m unittest discover -s fa26/tests -v
```
