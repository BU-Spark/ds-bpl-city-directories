# Stage 2 · one-page CLI verification

This is a real new Tesseract run on **printed page 162, scanned leaf 164,
BookReader n163**, completed on 2026-11-18. It verifies that the portable CLI can
download a page, check its provenance, recognize it and export native files.
It is not a cross-page quality assessment or an accuracy benchmark.

| Item | Recorded result |
| --- | --- |
| Host | macOS, arm64, CPU |
| Engine / image library | Tesseract 5.3.4 / Pillow 11.3.0 |
| Configuration | English tessdata_best, OEM 1, PSM 3; gray, 2× Lanczos, 10 px white border |
| Source | 1699 × 2778 JPEG; SHA-256 matches the historical p162 source image |
| Detected lines / recognized words | 259 / 1,607 |
| Engine wall time | 11.535 s |
| Successful invocation wall time | 12.076 s, with image and weight caches reused |
| Quality status | Unreviewed; lines include headers and possible detection artifacts |

`run.json` records the complete configuration, engine/native-library build,
source receipt, code hashes, pre-commit Git revision, timing boundaries and
output checksums. `raw/` contains exact TXT, TSV, HOCR and engine logs.
`lines.csv` contains the source-coordinate line export. The source JPEG is not
duplicated here; the same bytes are retained as
[`../../archive/model_comparison/source/p162.jpg`](../../archive/model_comparison/source/p162.jpg)
and are linked by hash and URL in the run record.

The first development attempt exposed missing output-format config files when
using a standalone weight directory. The implementation now enables TXT/TSV/HOCR
with explicit Tesseract output parameters. That failed attempt remains under
the ignored local work directory; this example contains the successful run.
The source receipt records its earlier download, so the successful invocation's
timing must not be called a cold-download end-to-end benchmark.

The engine number and selected settings match the prior baseline, but this is
an ARM/native-library build with Leptonica 1.83.1. Historical Colab used x86 and
Leptonica 1.82.0. New native TXT/TSV are not byte-identical to the old outputs;
cross-page visual validation remains stage 3. No accuracy ranking or full-volume
runtime estimate is inferred from this one page.

Re-run from the repository root in the configured environment:

```sh
bpl-ocr ocr-page --manifest fa26/manifests/vol1/manifest.json --leaf 164 --work-dir fa26/work
```

Each invocation creates a new run directory and preserves prior results.
