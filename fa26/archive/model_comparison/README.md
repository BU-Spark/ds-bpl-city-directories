# Completed OCR model comparison

This is the read-only evidence for the completed model-selection stage. The
active workflow is described in [../../README.md](../../README.md).

**Decision:** use Tesseract for the next production OCR stage. This is a project
decision informed by the comparison and team evaluation, not a claim that it
won every accuracy metric. Ground-truth scoring belongs to the team's separate
evaluation work.

## Evidence to read

| File | Purpose |
| --- | --- |
| [results/lines.csv](results/lines.csv) | All five models on the same 1,573 detected lines, with page links |
| [results/models.json](results/models.json) | Versions, prompts, weights, settings and imported-result context |
| [results/status.json](results/status.json) | Completed, empty and truncated output counts; not accuracy |
| [ANALYSIS.zh-CN.md](ANALYSIS.zh-CN.md) | Detailed visual checks and representative errors, in Chinese |
| [source/index.json](source/index.json) and `source/p161.jpg`–`p167.jpg` | Original scans, hashes, shared coordinates and source URLs |
| `results/raw/` | Exact model responses and native Tesseract TXT/TSV/runtime records |
| [method/ocr_pipeline.py](method/ocr_pipeline.py) | Historical comparison implementation; retained for method provenance |
| [checksums.json](checksums.json) | SHA-256 inventory of the retained historical evidence |

## Scope and limitations

The sample covers printed pages 161–167 of
[Vol. 1](https://archive.org/details/bostonmassachuse1916112samp). Page 161 uses
only the lower directory body. A detected line is not a person or a verified
physical line. Shared detection errors affect all five columns.

| Engine | Completed | Empty | Truncated |
| --- | ---: | ---: | ---: |
| Tesseract | 1,573 | 0 | 0 |
| dots.mocr | 1,555 | 7 | 11 |
| EasyOCR | 1,567 | 6 | 0 |
| PaddleOCR | 1,567 | 6 | 0 |
| Qwen3-VL-2B | 1,520 | 0 | 53 |

These are output statuses, not correctness scores. Historical Tesseract outputs
used **full-page PSM 3**; the other engines used shared line crops. The retained
comparison adapter also supports new Tesseract **PSM 7** line-crop inference;
it did not generate the imported PSM 3 results. This difference must remain
visible when interpreting the comparison.

Tesseract baseline: version 5.3.4, English `tessdata_best`, OEM 1, PSM 3,
grayscale, 2× Lanczos resizing, 10 px white border. No extra thresholding or
denoising. English weights SHA-256:
`8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba`.

The detailed analysis documents both recoverable difficult text and errors:
shared overlapping crops, name/address mistakes, missing fractions, repetition,
and Qwen text absent from the scans. These examples do not establish an overall
accuracy ranking. Historical full-page Tesseract engine time was 130.287 s
across seven pages; complete comparable five-model runtime and peak-memory
measurements were not collected.

## Cleanup on 2026-11-18

The duplicate two-engine `data/ocr/` package was removed after checking that its
26 unchanged files and Tesseract/mOCR CSV columns were retained here. The former
`bpl_ocrs/` package was moved here without changing its evidence files. Obsolete
Colab notebooks and the unused resource-measurement workflow were retired;
their prior versions remain in Git history and in a local recovery archive
outside the team repository. Teammate source exploration and original IA text
files were preserved.

Historical paths in the detailed analysis and method source refer to the old
layout. All `bpl_ocrs/source/` and `bpl_ocrs/results/` references resolve to this
directory's `source/` and `results/`. The historical method is not an active CLI
or a dependency of the new workflow.
