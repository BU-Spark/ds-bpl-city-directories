"""Regenerate two standalone English Colab notebooks from the shared helpers."""
from pathlib import Path
import textwrap

import nbformat as nbf


SCRIPTS = Path(__file__).resolve().parent


def make_notebook(engine):
    dots = engine == "dots"
    cells = []

    def md(text):
        cells.append(nbf.v4.new_markdown_cell(textwrap.dedent(text).strip()))

    def code(text, tag, hidden=False):
        cell = nbf.v4.new_code_cell(textwrap.dedent(text).strip() + "\n")
        cell.metadata["tags"] = [tag]
        if hidden:
            cell.metadata.update({"cellView": "form", "collapsed": True,
                                  "jupyter": {"source_hidden": True}})
        cells.append(cell)

    title = "dots.mocr" if dots else "Tesseract"
    filename = "04_dots_mocr_vs_ia_colab.ipynb" if dots else "03_tesseract_vs_ia_colab.ipynb"
    md(f"""
        # BPL OCR review: {title}

        **Runtime:** {"GPU" if dots else "CPU"}. Upload this notebook to Colab and run cells in order.
        Nothing is installed on your Mac. No API key is required for the public inputs/model.

        **Output:** `review.html`, `predictions.csv`, `manual_review.csv`, and a ZIP.
        Teammates open `review.html`, compare the scan with the OCR text, enter human transcription,
        and export a reviewed CSV. CER/WER are available only for verified human text.

        **Scope:** printed page 161, split into the same 12 image-based review regions in both notebooks.
        Regions cover all body text, including companies; they are not 12 people or gold labels.
        This is a development experiment, not an independent test.
    """)
    md("""
        ## 1. Set up the hosted runtime

        Each notebook installs only its own OCR dependencies and can run independently.
    """ + ("""

        The GPU notebook uses the official dots.mocr checkpoint, greedy decoding and the model's
        existing SDPA implementation. A logged import-only compatibility edit avoids requiring
        Flash Attention on Colab. This backend has not been GPU-tested in the local workspace;
        check `ocr/dots_mocr_units/runtime.json` for the actual model revision and any failures.
    """ if dots else ""))
    setup = """
        import subprocess
        import sys
        from pathlib import Path
        if not Path('/content').exists():
            raise RuntimeError('Run this setup cell in a Google Colab hosted runtime.')
    """
    if dots:
        setup += """
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError('Select Runtime > Change runtime type > GPU, then rerun.')
        print('GPU:', torch.cuda.get_device_name(0))
        """
    else:
        setup += """
        subprocess.run(['apt-get', 'update', '-qq'], check=True)
        subprocess.run(['apt-get', 'install', '-y', '-qq', 'tesseract-ocr', 'tesseract-ocr-eng'], check=True)
        """
    setup += """
        dependencies = ['requests', 'Pillow', 'numpy']
    """
    if dots:
        setup += """
        dependencies += ['transformers==4.57.6', 'accelerate', 'qwen-vl-utils', 'huggingface-hub']
        """
    setup += """
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '--disable-pip-version-check',
                        *dependencies], check=True)
    """
    if not dots:
        setup += """
        print(subprocess.run(['tesseract', '--version'], capture_output=True, text=True, check=True).stdout.splitlines()[0])
        """
    code(setup, "setup")
    code("# @title Shared review helpers (expand to inspect)\n" + (SCRIPTS / "ocr_review.py").read_text(), "helpers", hidden=True)
    if dots:
        code("# @title dots.mocr runner (expand to inspect)\n" + (SCRIPTS / "dots_mocr_runner.py").read_text(), "dots_helpers", hidden=True)

    md("""
        ## 2. Prepare the same review images

        Choose one input mode below:
        - `download`: fetch the exact existing pilot JPEG and IA annotations.
        - `upload`: upload `bostonmassachuse1916112samp_leaf0163_p161.jpg` and `p161_ocr.json`.
        - `review_bundle` (optional): upload a v2 review ZIP to reuse inputs, human review
          and any existing Tesseract predictions. This is not required by dots.mocr.

        Region IDs and decoded-pixel checksums stay identical across engines. Cuts use nearby
        ink-light rows from the image; inspect any crop edge before verifying a transcription.
        No OCR names or reference answers are used to choose regions or prompt the models.
    """)
    mode = "download"
    root_name = "bpl_dots_mocr_p161_v2" if dots else "bpl_tesseract_p161_v2"
    code(f"""
        INPUT_MODE = '{mode}'
        ROOT = Path('/content/{root_name}')
        predictions = []
        if INPUT_MODE == 'review_bundle':
            from google.colab import files
            uploaded = files.upload()
            archives = [name for name in uploaded if name.lower().endswith('.zip')]
            if len(archives) != 1:
                raise ValueError('Upload exactly one v2 review ZIP.')
            bundle_path = Path('/content/uploaded_bpl_review.zip')
            bundle_path.write_bytes(uploaded[archives[0]])
            manifest, predictions = import_bundle(bundle_path, ROOT)
        elif INPUT_MODE == 'upload':
            from google.colab import files
            uploaded = files.upload()
            (ROOT / 'source').mkdir(parents=True, exist_ok=True)
            for name in [IMAGE_NAME, 'p161_ocr.json']:
                if name not in uploaded:
                    raise ValueError('Missing upload: ' + name)
                (ROOT / 'source' / name).write_bytes(uploaded[name])
            validate_sources(ROOT)
            manifest = make_units(ROOT)
        elif INPUT_MODE == 'download':
            download_sources(ROOT)
            manifest = make_units(ROOT)
        else:
            raise ValueError('Unknown INPUT_MODE')
        # Keep the primary comparison concise; original full-page context runs are separate.
        predictions = [p for p in predictions if p['method'] in ['ia_existing', 'tesseract_units']]
        predictions = [p for p in predictions if p['method'] != 'ia_existing']
        predictions += lines_to_predictions(ia_lines(ROOT), manifest, 'ia_existing', 'existing_page_word_ocr')
        print('Prepared', len(manifest['review_units']), 'fixed review regions.')
    """, "inputs")

    if not dots:
        md("""
        ## 3. Run Tesseract on the review images

        Uses English, OEM 1 and PSM 6 on every region. If a compatible v2 ZIP already contains
        all 12 completed same-crop Tesseract predictions, reuse them. Original full-page outputs
        are not substituted for same-crop inference. IA remains a page-level historical baseline.
        Native TSV line IDs are preserved instead of regrouping tall word boxes by their centers.
        The engine's own segmentation can still be wrong.
        """)
        code("""
        wanted = {unit['unit_id'] for unit in manifest['review_units']}
        existing = [p for p in predictions if p['method'] == 'tesseract_units']
        if {p['unit_id'] for p in existing} == wanted and all(p['status'] == 'completed' for p in existing):
            print('Reusing completed same-crop Tesseract predictions and imported provenance.')
        else:
            predictions = [p for p in predictions if p['method'] != 'tesseract_units']
            predictions += run_tesseract_units(ROOT, manifest)
        write_csv(ROOT / 'predictions.csv', predictions, PREDICTION_FIELDS)
        """, "tesseract")

    if dots:
        md("""
            ## 3. Run dots.mocr on the review images

            Downloads the approximately 6 GB official checkpoint into the Colab VM. The exact
            revision, prompt, GPU, precision, processor image sizes and token limits are recorded.
            Each region is transcribed directly: no invented word/line bounding boxes are used.
            Model-processor resizing is logged; raw source crops match the Tesseract inputs.
            Failed/truncated units are visible and are not silently removed from scoring.
            Only images and a fixed transcription prompt enter the model; IA/Tesseract text
            is used for comparison only. This notebook does not run Tesseract.
        """)
        code("""
            MODEL_ID = 'dots-studio/dots.mocr'
            MODEL_REVISION = 'main'  # Resolved to an exact commit and recorded before inference.
            predictions = [p for p in predictions if p['method'] != 'dots_mocr_units']
            predictions += run_dots_units(ROOT, manifest, model_id=MODEL_ID, revision=MODEL_REVISION,
                                          max_new_tokens=2048, max_pixels=1000000)
            write_csv(ROOT / 'predictions.csv', predictions, PREDICTION_FIELDS)
        """, "dots")

    n = 4
    md(f"""
        ## {n}. Export the team review pack

        Download and unzip the result. Open **`review.html`** in a browser; no server is needed.
        Transcribe exactly, enter a reviewer, mark confident regions **Verified**, then
        **Export reviewed CSV**. Use **Uncertain** for unreadable text. The HTML can import a
        reviewed CSV from either engine's pack. It calculates CER/WER on the same verified regions
        for every method; before verification it reports no accuracy score.

        Do not overwrite `predictions.csv` with human corrections. Review all regions, including
        those where the OCR outputs agree. Keep a separate unseen page for final validation.
    """)
    code("""
        page = build_review(ROOT, manifest, predictions)
        archive = bundle_results(ROOT)
        print('Start with review.html. Export a reviewed CSV before sharing.')
        print('Result ZIP:', archive)
        from google.colab import files
        files.download(str(archive))
    """, "export")
    md(f"""
        ## {n+1}. Optional: save scores after human review

        Set `SCORE_REVIEWED_CSV = True` only when you have an exported reviewed CSV.
        Upload it to save `verified_scores.csv` and a refreshed review pack.
        Missing model output counts as an omission. Review status, reviewer and gold text are
        required; pending/uncertain regions do not enter accuracy scores.
    """)
    code("""
        SCORE_REVIEWED_CSV = False
        if SCORE_REVIEWED_CSV:
            from google.colab import files
            uploaded = files.upload()
            csv_names = [name for name in uploaded if name.lower().endswith('.csv')]
            if len(csv_names) != 1:
                raise ValueError('Upload exactly one reviewed CSV.')
            reviewed_path = ROOT / 'uploaded_review.csv'
            reviewed_path.write_bytes(uploaded[csv_names[0]])
            build_review(ROOT, manifest, predictions, reviewed_csv=reviewed_path)
            print((ROOT / 'verified_scores.csv').read_text(encoding='utf-8-sig'))
            files.download(str(bundle_results(ROOT)))
    """, "score")
    md("""
        **References:** [Tesseract TSV/PSM](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html)
        · [dots.mocr model card](https://huggingface.co/dots-studio/dots.mocr)
        · [official dependencies](https://github.com/studio-dots-ai/dots.mocr/blob/main/requirements.txt)
        · [vision attention implementation](https://huggingface.co/dots-studio/dots.mocr/blob/main/modeling_dots_vision.py)

        Shared helper source is embedded so this notebook runs without cloning the project repo.
        Its repository sources are `ocr_review.py` and, for the GPU notebook, `dots_mocr_runner.py`.
    """)
    nb = nbf.v4.new_notebook(cells=cells)
    nb.metadata = {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                   "language_info": {"name": "python"},
                   "colab": {"name": filename, "provenance": []}}
    if dots:
        nb.metadata["accelerator"] = "GPU"
        nb.metadata["colab"]["gpuType"] = "T4"
    nbf.validate(nb)
    path = SCRIPTS / filename
    nbf.write(nb, path)
    print(path)


if __name__ == "__main__":
    make_notebook("tesseract")
    make_notebook("dots")
