# BPL OCR · printed pages 161–167

One hosted Colab notebook and one shared Python file produce line-by-line OCR
from the same seven scans. Select Tesseract, dots.mocr, EasyOCR, PaddleOCR English
v5, or Qwen3-VL-2B. This workflow outputs recognized text only.

```text
scripts/ocr_colab.ipynb       The single OCR entry point
scripts/ocr_pipeline.py       Shared source loading, five models, resume and export
data/ocr/source/              Seven original JPEGs and one shared coordinate index
data/ocr/results/lines.csv    Five model text columns plus sources
data/ocr/results/models.json  Model revisions/settings and historical contexts
data/ocr/results/status.json  Completed/empty/failed/unrun counts, not accuracy
data/ocr/results/raw/         Exact responses and retained original native logs
tests/test_ocr_pipeline.py    Integrity tests using fake recognizers
```

## Run in Colab

1. Upload `scripts/ocr_colab.ipynb` to hosted Colab. Set `ENGINE` in section 1.
   Use a fresh runtime per model. Dots and Qwen require GPU; EasyOCR uses an
   available GPU; Tesseract and this Paddle setup use CPU. No API key is needed.
2. Upload a ZIP of `data/ocr/`, or the latest ZIP downloaded by the notebook.
   It contains `source/` and `results/`. Transfer ZIPs are generated on demand,
   rather than stored beside duplicate folders in the repository.
3. `MAX_NEW_LINES = None` processes all remaining target lines; use `6` for a
   short trial. `FORCE = False` keeps completed outputs and retries empty,
   failed or truncated lines. `FORCE = True` recognizes target lines again;
   earlier raw responses and their original settings remain in the log.
4. Download the common output ZIP in section 4. Upload that latest ZIP for the
   next model to accumulate outputs. After interrupting, download a checkpoint
   before Colab discards its VM.

No OCR is installed on the user's Mac. Weights stay outside the source/results
folder and are excluded from the exported ZIP. Each model sees only line images;
no previous OCR text, name lists or corrections enter recognition.

## Sources and output

`source/p161.jpg` through `p167.jpg` are the complete original scans. Hashes,
dimensions, source URLs and frozen line geometry are kept in `source/index.json`.
Crops exist in memory only. The index retains **1,737** historical detections;
the public CSV has **1,573** rows. Page 161 includes only its lower directory body
(`1645 <= original y0 < 2678`); pages 162–167 retain their existing detections.
All models share the same coordinates/order, including any detection mistakes.
One row is a detected scan line, not a verified physical line or a person.

The CSV has exactly these columns:

```text
tesseract_text,mocr_text,easyocr_text,paddleocr_text,qwen_text,sources
```

All rows remain, including unrun/failed cases. CSV whitespace is collapsed;
exact raw strings and statuses stay internal. `sources` links to the book page.
Existing Tesseract/mOCR outputs and native logs were migrated without rerunning.
Historical Tesseract used full-page PSM 3; new Tesseract recognition uses shared
line crops with PSM 7. This distinction remains in `models.json`. Existing mOCR
used the same shared crops. The other three models have not yet produced BPL
predictions. Blank cells are explained by `status.json` and raw records.

This workflow does not expand ditto, fix spelling, merge people, parse fields,
score accuracy, create human reference forms or geocode.

## Maintenance

The notebook embeds the exact shared Python source. Regenerate after edits:

```sh
python fa26/scripts/ocr_pipeline.py --notebook
python -m unittest discover -s fa26/tests -v
python fa26/scripts/ocr_pipeline.py --pack fa26/data/ocr --output /tmp/bpl_ocr.zip
```

`requirements.txt` contains only lightweight validation dependencies. Model
packages are installed by Colab. Tests use fake recognizers; new model inference
still needs a Colab smoke test. Paddle explicitly uses its English v5 recognizer.

Teammate materials remain separate: `scripts/api_look.ipynb` is the original
fetch exploration; `data/1916 Boston Directory Vol. 1 (A–O)/` contains original
OCR text datasets. They are not additional OCR pipeline entry points.

Official sources: [Tesseract](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html),
[dots.mocr](https://huggingface.co/dots-studio/dots.mocr),
[EasyOCR](https://www.jaided.ai/easyocr/documentation/),
[Paddle English](https://huggingface.co/PaddlePaddle/en_PP-OCRv5_mobile_rec),
[Qwen3-VL-2B](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct).
