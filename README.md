# Boston City Directories

BU Spark! / CDS DS701 project with Boston Public Library and the Leventhal Map
& Education Center, working with the 1916 Boston Directory.

The current OCR workflow is documented in [fa26/README.md](fa26/README.md).
It uses one hosted Colab notebook, one shared Python implementation, the same
seven original scans (printed pages 161–167), and five selectable OCR models.
Its deliverable is line-by-line recognized text and original page links.

- `fa26/scripts/ocr_colab.ipynb`: current OCR entry point.
- `fa26/scripts/ocr_pipeline.py`: shared implementation.
- `fa26/data/ocr/`: canonical scans, shared geometry and consolidated results.
- `dataset-documentation/`: original dataset documentation.

Project documents and client presentations are maintained in the parent workspace.
