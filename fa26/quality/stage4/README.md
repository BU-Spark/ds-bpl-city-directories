# Stage 4 · bounded batch and recovery validation

**Completed with conditions on 2026-11-19.** All 60 planned pages have native
captures and resources. Current QA accepts **59 pages and quarantines p516 /
leaf 518** for systematic cross-column merges. Accepted captures still require
entry reconstruction. [Gate](gate.json), [coverage](pages.csv).

| Check | Observed result |
| --- | --- |
| Native attempts | 60 completed + one deliberately interrupted |
| Current QA | 59 accepted, one quarantined; all 60 accounted for |
| Native / accepted / quarantined rows | 14,329 / 14,176 / 153 |
| Recognized words | 95,200, including artifacts and the quarantined page |
| Live interruption | SIGINT during leaf 164; exit 130; child stopped; first two run IDs retained |
| Repeat completed command | 61 attempts before/after; zero new native directories; 1.30 s |
| All 60 native engine times | 736.126 s total; median 12.55 s/page; p95 13.16 s/page |
| Measured capture-loop wall | 1,129.611 s, about 18.8 min; excludes startup/export and command gaps |
| Peak sampled attempt process RSS | 430,178,304 bytes = 410.25 MiB |
| Source access during final capture | 19 checked caches + 41 downloaded pages; 17 failed requests recovered |
| Resource coverage | All 61 attempts recorded; no tree enumeration failures |
| Offline tests | 32 passed, including historical comparison/stage-3 evidence |

This is one macOS arm64 host and mixed warm/cold sources, not a full-volume
runtime guarantee or accuracy evaluation.

## Quarantine finding and diagnostic correction

On p516, native PSM 3 groups combine many left/right physical lines. Those wide
boxes also moved the old estimated gutter to x=1244.5 inside the right column.
Current QA uses left edges ending before the right-column starts, restoring
x=887. It flags 85 cross-gutter candidates and quarantines pages with at least
three such candidates comprising at least 10% of diagnostic body rows. These
are conservative review thresholds, not measured error rates.

The [annotated source](leaf0518_quarantine.jpg) and [two native examples](quarantine.json)
document the finding. All 153 rows remain in local `quarantined_lines.csv` and
the original native files. Accepted `lines.csv` has 14,176 rows; flags retain all
14,329 captured rows. Layout repair needs a separate reviewed segmentation
strategy. OCR parameters and recognized strings were preserved.

This is an **offline diagnostic revision after capture**. Only `quality.py`,
`batch.py` and `cli.py` changed; engine, page pipeline, preprocessing and source
acquisition files remain identical to capture. Native settings IDs/receipts and
the original checkpoint are unchanged. [review.json](review.json) records both
code versions. Its current assessment supersedes the earlier 60-completed QA.

## Fixed scope and execution

The sample has six ten-page blocks: scanned leaves 162–171, 300–309, 514–523,
776–787 excluding ad scans 781/782, 1195–1204 and 1525–1534. This is **59 primary
pages + one supplementary page**, covering the mixed first directory page,
adjacent pages, the source label gap, inserted ads and the end of the volume.
It is a purposive engineering sample, not a random accuracy evaluation.

Every selected page receives fresh full-page recognition with Tesseract 5.3.4,
the pinned English tessdata_best weights, OEM 1, PSM 3, Pillow 11.3.0 and the
unchanged gray/2× Lanczos/10 px border preprocessing. One sequential worker runs
with `OMP_THREAD_LIMIT=1`; this runtime control and code hashes are recorded.
Source JPEG caches can be reused after hash/dimension checks. Native outputs
from stages 2 and 3 are not substituted for the new measurements.

Rebuild current QA from saved work files, without OCR or network access:

```sh
conda run --prefix .runtime/env bpl-ocr batch-review --manifest fa26/manifests/vol1/manifest.json --work-dir fa26/work --batch-dir fa26/work/stage4/batch --output fa26/work/stage4/review
```

Exit 2 is expected while leaf 518 is quarantined. A fresh capture with current
code uses a new directory; the old checkpoint still pins its capture code:

```sh
OMP_THREAD_LIMIT=1 conda run --no-capture-output --prefix .runtime/env bpl-ocr batch --manifest fa26/manifests/vol1/manifest.json --plan fa26/quality/stage4/plan.json --work-dir fa26/work --batch-dir fa26/work/stage4/new-batch
```

Repeat the same command to continue. For a fresh batch, use a new `--batch-dir`.
`--work-dir` stores sources, weights and immutable native runs; `--batch-dir`
stores checkpoints and derived exports. Both paths are configurable. This pilot
uses ignored local storage, not a new Colab workflow or a team data upload.

## Recovery and failure policy

- Per-page attempt metadata and batch checkpoints are written atomically. Each
  native attempt has a separate directory, including failed/interrupted ones.
- Completed captures are rechecked against source/output hashes, the manifest,
  pinned code/build and native TSV export before being reused. A finished run
  can be adopted if its checkpoint was interrupted before recording completion.
- Ctrl-C/SIGTERM stops the native child and retains the interrupted attempt.
  On restart, an abandoned recorded native PID is checked against its creation
  time and host before cleanup. An incomplete run from another host requires
  checking that worker; the program will not kill a foreign process.
- An OS lock prevents concurrent writers to the same batch. Use only one batch
  per work directory, on a filesystem supporting POSIX advisory locks.
- One canonical IIIF request is followed, on a transient error, by at most two
  exact-member BookReader requests. Each request has a socket timeout and the
  plan records backoff. Request/final URLs, failed requests, actual JPEG hashes,
  dimensions and the chosen rendering are retained. Byte/pixel equality with
  an unavailable IIIF rendering is not assumed. The official rendering method
  is described in [Internet Archive's BookReader documentation](https://openlibrary.org/dev/docs/bookreader).
  Line CSVs retain the canonical `source_image_url`; the matching run's source
  receipt identifies the actual rendering and image SHA-256.
- Source exhaustion and engine timeouts get at most two page attempts;
  interrupted attempts do not consume that failure budget. Permanent failures
  remain visible and do not silently retry forever.
- Missing outputs, invalid geometry, changed bytes, unresolved two-column
  diagnostics and systematic cross-column groups are quarantined. Heuristic flags
  accompany retained raw rows. `completed` means a checked capture, with `quality_status=review_required`.
  No OCR strings or native reading order are corrected, filtered or reassembled.

The saved corpus includes the mixed/supplementary scopes, the absent printed
labels 775–778 and the excluded ads. Two estimated text-start clusters are a
capture diagnostic, not proof that every physical line or column was read.

## Resource definitions

psutil 7.0.0 samples the worker and descendants every 0.1 seconds during each
recognition attempt; final merged-export memory is outside this sampler. Reported peak
RSS is their sampled sum: shared pages may be counted more than once and short
peaks can be missed. CPU seconds sum observed per-process user+system maxima,
less the worker's initial CPU, and are a sampled lower bound. These are not
whole-host RAM/CPU measurements. See the [psutil process API](https://psutil.readthedocs.io/stable/#process-class).
Four individual process observations were unavailable during sampling; process-tree
enumeration itself never failed. Exact CPU/peak measurements are not implied.

Per-attempt timings separate model/source preparation, preprocessing, native
engine and export. Measured session wall time covers the capture loop, including
retries/backoff, but excludes startup revalidation/model preflight, final merged
exports and time between commands. Hard-stop durations without a final receipt remain
unknown. A cached download is not counted as a cold network measurement.
Metrics describe the final fixed-code batch. Preliminary engineering attempts
are retained separately in local work, rather than mixed into these timings.

## Data locations

The batch directory contains `checkpoint.json`, per-page coverage `pages.csv`,
all `attempts.csv`, merged `lines.csv`, `quarantined_lines.csv`, `line_flags.csv`, `run_records.json` and
`summary.json`. Full source JPEGs, native TXT/TSV/HOCR and full merged line tables
remain under ignored `fa26/work/`. This report keeps coverage/resource tables,
receipt copies (host names omitted), recovery evidence and one diagnostic figure.
`checksums.json` covers saved artifacts. `validation.json` records distributions,
sampling limits and the separately retained preliminary runs.

Before stage 5, choose a durable team data location and preserve the native
files there. Relocating an existing checkpoint needs a reviewed migration,
since its resolved work path and execution identity are pinned. macOS arm64 is
the exercised platform; Linux/container execution is not claimed as tested.
