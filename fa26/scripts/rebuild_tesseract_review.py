#!/usr/bin/env python3
"""Build the English review pack from already-completed v1 Tesseract outputs.

No OCR is rerun and the original result directory is read-only.
"""
import argparse
import json
from pathlib import Path
import shutil

import ocr_review as review


def rebuild(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents:
        raise ValueError("Choose a separate output directory outside the original results")
    (destination / "source").mkdir(parents=True, exist_ok=True)
    for name in [review.IMAGE_NAME, "p161_ocr.json"]:
        shutil.copyfile(source / "source" / name, destination / "source" / name)
    review.validate_sources(destination)
    manifest = review.make_units(destination)
    predictions = review.lines_to_predictions(review.ia_lines(destination), manifest, "ia_existing", "existing_page_word_ocr")
    all_lines = {}
    for method, variants in [("tesseract_full_page", ["full_page"]),
                             ("tesseract_columns", ["left_column", "right_column"])]:
        words = []
        for variant in variants:
            words.extend(json.loads((source / "ocr" / variant / "words.json").read_text())["words"])
        lines = review.native_tesseract_lines(words)
        # Native IDs from separate cropped images can collide: prefix their source variant.
        if len(variants) > 1:
            words = []
            for variant in variants:
                part = json.loads((source / "ocr" / variant / "words.json").read_text())["words"]
                for word in part:
                    word["native_id"] = variant + ":" + word["native_id"]
                words.extend(part)
            lines = review.native_tesseract_lines(words)
        predictions.extend(review.lines_to_predictions(lines, manifest, method, "original_context_run_not_same_crop_inference"))
        all_lines[method] = len(lines)
        review.write_json(destination / "ocr" / method / "native_lines.json", lines)
    target = destination / "original_run_provenance"
    target.mkdir(exist_ok=True)
    shutil.copyfile(source / "runtime.json", target / "runtime.json")
    for variant in ["full_page", "left_column", "right_column"]:
        shutil.copytree(source / "ocr" / variant, target / variant, dirs_exist_ok=True)
    page = review.build_review(destination, manifest, predictions)
    review.write_json(destination / "reprocessing.json", {
        "source_results": str(source), "fresh_inference": False,
        "change": "Tesseract words grouped by native TSV line IDs, with source/column identity.",
        "native_body_line_counts": all_lines,
        "note": "Native engine lines can still be wrong. These are not human-confirmed physical lines or person counts.",
    })
    return page, review.bundle_results(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in rebuild(args.input, args.output):
        print(path)
