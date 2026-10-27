# OCR review workflow

Use the two standalone English notebooks in this directory:

- `03_tesseract_vs_ia_colab.ipynb`: Colab CPU; IA plus fresh Tesseract.
- `04_dots_mocr_vs_ia_colab.ipynb`: Colab GPU; independent dots.mocr inference plus IA comparison.

Both default to `INPUT_MODE = 'download'` and fetch their own source copies. The
dots.mocr notebook neither installs nor runs Tesseract. Set `review_bundle` only
when you want to import a Tesseract review ZIP for a combined comparison. The
model reads only crop images and its fixed prompt, never another engine's text.

Both create the same 12 source-image review regions on printed page 161. Regions
tile the directory body, including company/context rows. They are not 12 people.
The crops preserve decoded source pixels. Region checksums use decoded pixels,
so different PNG encoders do not invalidate human reviews.

## For teammates reviewing output

1. Unzip the review pack and open `review.html` in a browser.
2. Optionally hide OCR while transcribing. Enter exactly what the scan says.
3. Preserve abbreviations, ditto marks, digits and line-ending hyphens. Do not
   expand names or normalize addresses in the transcription.
4. Enter reviewer and select Verified only when confident; use Uncertain otherwise.
5. Export reviewed CSV before closing/sharing. Import that CSV into the next
   engine's HTML to reuse the human text. Browser storage is not a shared file.
6. Calculate CER/WER in the HTML, or upload the reviewed CSV in the optional final
   notebook cell to save `verified_scores.csv`.

The HTML embeds the scan images and works offline. Human input and predictions
are separate. Only verified regions with reviewer and gold text are scored;
every method uses the same gold regions. Missing/failed predictions count as
omissions. IA is a baseline, not gold. Pending review produces no accuracy score.

## What changed from v1

Tesseract uses native TSV page/block/paragraph/line IDs, rather than clustering
individual word-box centers. Column and source identity are retained. This avoids
extra fragmentation introduced by our wrapper, while retaining the engine's own
segmentation errors for review. Native lines are not guaranteed physical lines.

The default new experiments run Tesseract and dots.mocr directly on the identical
review crops. Original full-page/column results can still be reviewed, but carry
separate context-run method names. No difference-to-IA percentage is advertised
as accuracy. No field extraction, surname expansion or geocoding is included.

## Reprocess the existing Tesseract results

From the repository root, using a Python environment with Pillow and NumPy:

```sh
python fa26/scripts/rebuild_tesseract_review.py \
  --input ../bpl_tesseract_p161_results \
  --output fa26/data/ocr_review/tesseract_existing_p161_v2
```

This preserves the original result directory and does not rerun OCR. It creates
a review HTML and ZIP using the existing three context runs. Fresh same-crop
Tesseract predictions require the CPU notebook. The GPU notebook can optionally
import those predictions; it does not generate missing Tesseract outputs.

## dots.mocr runtime

The GPU notebook follows the official Transformers pathway and pins
`transformers==4.57.6` from the upstream dependency list. It resolves and records
the exact public checkpoint revision. It uses the existing vision/decoder SDPA
path and a logged import-only guard around the upstream unconditional
`flash_attn` import. Model weights are not changed. GPU precision, prompt,
processor dimensions, generation limits, failures and code hashes are saved.
No fictional word boxes are created: each prediction belongs to its actual crop.

The model has not been run on a GPU in this local workspace. The notebook must
complete in Colab before any dots.mocr quality or runtime claim is made. If model
loading fails, inspect its runtime JSON; do not substitute another model silently.

Sources: [model card](https://huggingface.co/dots-studio/dots.mocr),
[official requirements](https://github.com/studio-dots-ai/dots.mocr/blob/main/requirements.txt),
[vision code](https://huggingface.co/dots-studio/dots.mocr/blob/main/modeling_dots_vision.py).

## Maintenance

`ocr_review.py` is the shared review implementation. `dots_mocr_runner.py` contains
GPU inference. After changing either, regenerate the embedded notebook sources:

```sh
python fa26/scripts/build_ocr_notebooks.py
python -m unittest discover -s fa26/tests -v
```
