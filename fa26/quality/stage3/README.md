# Stage 3 · cross-page quality review

**Completed with conditions on 2026-11-19.** The selected full-page Tesseract
baseline can proceed to the bounded **stage-4 capture/batch engineering pilot**.
Native OCR rows still require layout/entry reconstruction before they can be
used as verified people, occupations or addresses.

## What was checked

The fixed purposive sample contains **16 pages: 15 primary directory pages and
one supplementary page**. Printed pages: **160, 161, 162, 300, 512, 513, 774, 779,
782, 783, 1000, 1001, 1200, 1201, 1533, 1534**. It covers the mixed first page,
sparse additions/removals, early/interior/late pages, adjacent-page transitions,
the 774→779 gap, inserted ads and the visibly degraded final directory page.
The plan was fixed before inference in [selection.json](selection.json).

All captures used the same recorded settings ID, Tesseract 5.3.4, English weight
hash, OEM 1, **PSM 3**, Pillow 11.3.0 and gray/2× Lanczos/10 px border baseline.
Recognition code was the version committed as
`b9ab926dc73276fc90ff0251fa2f0293aa5b2a3a`. QA code was added after inference;
no production recognition parameters or old results were changed.

| Evidence | Result |
| --- | --- |
| Completed selected pages | 16 / 16 |
| Detected OCR rows / recognized words | 3,681 / 24,285, including reference text and artifacts |
| Source, output hash, export and coordinate checks | Passed on all 16 |
| Visual review | 16 full-page overlays + 96 source bands (six per page) |
| Whole-column dropout | None observed in this review |
| Offline regression/integrity tests | 19 passed |
| Successful engine processing | 179.795 s total; excludes downloads and failed source attempts |

This is a diagnostic review by the Codex assistant, **not an independently
transcribed human reference set**, a probability sample, CER/WER evaluation or
an exhaustive count of physical lines. No finding here establishes full-volume
accuracy or proves that every physical line is present.

## Main findings

1. **Both directory columns are represented.** Full-page overlays and top,
   middle and bottom bands showed substantive text in both columns on the
   selected pages. The source-coordinate boxes showed no systematic offset.
   [Overview 1](images/overview_1.jpg) and [overview 2](images/overview_2.jpg)
   show all 16 pages; they are coverage aids, not character-level proof.
2. **The main left→right column sequence is broadly preserved, with local
   exceptions.** Symbol blocks and detached right-aligned suffixes can interrupt
   native order. A native line is not always a physical line, let alone an entry.
3. **Vertical ditto strips become pseudo-lines.** For example, p512 produces
   `RERURIFRERNRERLRNEA` from a narrow strip of marks. These outputs need review
   flags, not resident counting or automatic surname inference.
4. **Surname headings and actual text lose characters.** Olsen on p1534 becomes
   separate `(0)` / `sen` pieces; Levy on p1201 becomes `Le` / `vy`; Philip and
   Milford on p779 are degraded; Giuseppe on p161 becomes `i`. High overall
   word-confidence scores coexist with these errors.
5. **Continuation and address fragments remain independent.** On p1001 a
   right-aligned `[rd S B]` record precedes the main text at the same baseline.
   Entry affiliation requires later contextual work. On p160, 352 Western av
   is read as 353. Raw strings were preserved, not corrected to the visual text.
6. **Scope and physical sequence matter.** P161's abbreviation key is not the
   directory body; p160 is supplementary and mixes firms/people; the 775–778
   label gap remains unresolved. Foster entries continue after the excluded
   advertisement scans between printed p782 and p783. No missing text was filled.

Selected evidence is linked below. [issues.csv](issues.csv) holds all 12
qualitative issues/scope constraints with stable line IDs and source hashes.

| Page | Example | Source/OCR view |
| --- | --- | --- |
| 512 | Ditto strip recognized as a long pseudo-word | [Six review bands](images/leaf0514_bands.jpg) |
| 1534 | Broken Olsen/Olstein headings and visible text degradation | [Six review bands](images/leaf1534_bands.jpg) |
| 1201 | Levy heading split into fragments | [Six review bands](images/leaf1201_bands.jpg) |
| 779 | Philip/Milford local text loss | [Six review bands](images/leaf0777_bands.jpg) |
| 1001 | Detached right-hand suffix and native-order problem | [Six review bands](images/leaf1001_bands.jpg) |
| 783 | Mary/Bennington line fragmented across records | [Six review bands](images/leaf0783_bands.jpg) |

## Non-destructive diagnostics

The new `bpl-ocr review` command checks saved runs and writes candidate flags
without downloading, recognizing, deleting, correcting or reordering raw OCR.
It found **83 vertical-symbol, 176 tall-line, 40 order-backtrack and 24 header
candidates**. These counts overlap and are **not verified error counts**. A tall
line can be legitimate wrapping; a short continuation such as `Dor` must remain.
The thresholds are recorded in [summary.json](summary.json), with a QA code hash.

Review columns are estimated from two clusters of substantive line starts and
left-column ends, not from the image midpoint. On p162 the estimated split is
about **96 px** right of the midpoint. This corrected the initial review-crop
method, not the full-page recognition input. These are diagnostic estimates and
windows, not production column/entry masks or an approved automatic text filter.

## Source access and provenance

Five capture invocations failed during source preparation, all from timeouts
(p160 once, p783/p1200 twice each). They remain documented in
[acquisition_failures.json](acquisition_failures.json), separate from OCR errors.
P160 was completed from a hash-verified JPEG retained from stage 1. Fourteen
final inputs are IIIF-derived native JPEGs or their verified caches.

For p783 and p1200, repeated canonical IIIF requests timed out. Their **official
BookReader native-size JPEGs** were downloaded instead. Printed headers,
accessible reader indices and expected dimensions were checked before OCR.
Actual request/redirect URLs, hashes and the alias reason are saved in
[run_records.json](run_records.json). No byte/pixel identity with an unavailable
IIIF rendering is assumed. These two input renderings remain disclosed, so the
sample is not a controlled comparison of image encoders or a cold-download
performance benchmark. No automatic fallback was added to production fetching.

## Reproduction and files

With the pilot work files available, run from the repository root:

```sh
conda run --prefix .runtime/env bpl-ocr review --runs fa26/work/stage3/pilot_runs.json --manifest fa26/manifests/vol1/manifest.json --output fa26/quality/stage3 --images
```

This rebuilds derived metrics/flags/figures; it does not overwrite native runs
or the separate visual review notes. A fresh capture uses the selected leaves
with `ocr-page`; preserve exact source receipts and disclose any access alias.

| File | Purpose |
| --- | --- |
| `selection.json` | Fixed 16-page sample and rationale |
| `pages.csv`, `summary.json` | Per-page diagnostics and aggregate checks |
| `line_flags.csv` | Every native row retained with candidate flags and original order |
| `run_records.json` | Full run/source/settings/output receipts |
| `anchors.csv`, `manual_review.json` | 96 inspected bands, partial visible anchors and disposition |
| `bands.json`, `figure_checksums.json`, `images/` | Source crop locations, overlapping rows and review figures |
| `issues.csv`, `acquisition_failures.json` | Traceable qualitative issues and failed source attempts |

Full-resolution source images and native TXT/TSV/HOCR remain in ignored
`fa26/work/source/` and `fa26/work/runs/`. The committed figures, partial anchors,
receipts and source URLs support review without duplicating those full captures
in Git. Band captions show full OCR records intersecting a crop; some text can
extend beyond the displayed crop. The figures are display JPEGs, not new OCR
inputs or gold-standard text.

## Stage-4 conditions

- Keep the selected OCR configuration and all original native outputs.
- Add per-page checkpoint/retry handling and record actual retrieval aliases.
- Carry page/line review flags into batch outputs; quarantine unresolved column,
  geometry or missing-output failures rather than silently marking them complete.
- Keep the mixed/supplementary scopes and source gaps visible across batches.
- Validate interruption recovery and resource sampling on only 50–100 pages.
- Resolve line fragments, surname/ditto context and entry boundaries before
  resident or occupation statistics. That extraction work is not completed here.

Stage 3 is complete as a bounded quality assessment. Full-volume OCR, automatic
batch recovery, structured entries, new accuracy scoring and geocoding remain
outside this stage.
