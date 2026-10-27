"""Audit and combine the two completed page-161 review packs; no OCR is run.

Uses the standard library only. Image observations below were made by the
assistant against all twelve source crops, not supplied by a human reviewer.
They never populate gold_text or mark a region verified.
"""

import argparse
import base64
import copy
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import statistics
import struct
import zlib


FOLDERS = {
    "tesseract_units": "bpl_tesseract_p161_v2_results",
    "dots_mocr_units": "bpl_dots_mocr_p161_v2_results",
}
IMAGE_NAME = "bostonmassachuse1916112samp_leaf0163_p161.jpg"
IMAGE_SHA = "a5949b1fb596c5acf388234964917e096908584e8ade49a75341d6a835c86f3d"
IA_SHA = "6cdd032291dbd76c11c7430fd2a7c918e6f6ef079c628db41420d81269a68edd"
METHODS = ["ia_existing", "tesseract_units", "dots_mocr_units"]
# unit, visible physical rows, visible leading ditto marks, assistant observation
OBSERVATIONS = [
    ("p161_L01", 7, 0, "mOCR collapses all rows into one line and drops an opening parenthesis. Tesseract reads Wire as ise and eral as er. Both read 165 Oliver; IA reads 163."),
    ("p161_L02", 7, 0, "mOCR preserves [55 Kilby and [ren Rox. Tesseract changes the brackets/text to (55 Kilby and fren Rox. Raised continuation text still needs entry-level interpretation."),
    ("p161_L03", 8, 5, "CRITICAL: mOCR returns only the first row. Barney, Charles T, David J, Fred and Harry F are absent. Tesseract retains these entries but damages Aaron, Empire, trav and av; its 568 is correct versus IA's 668."),
    ("p161_L04", 7, 6, "mOCR reads S B correctly but omits all six leading ditto marks. Tesseract reads 8 B in Herman's row."),
    ("p161_L05", 8, 5, "mOCR reads S E Co and mgr correctly, but changes Golosov to Golosoy and drops all five leading ditto marks. Tesseract reads section-sign E Co and mer."),
    ("p161_L06", 7, 4, "mOCR omits the opening parenthesis in William (Aarons & Finn), splits [671 Wash into a separate row, and drops four ditto marks. Tesseract adds noise and damages the second Golosov firm row."),
    ("p161_R01", 7, 5, "mOCR recovers Aaronson and 347A, but merges the Dor continuation and drops five ditto marks. Tesseract damages Aaronson and reads 3474. IA includes duplicated source words."),
    ("p161_R02", 7, 1, "Both new engines recover the lumbus av continuation and see ARONSON and AHRENSON cross-reference omitted from the IA reconstruction. mOCR varies the case of small-cap letters."),
    ("p161_R03", 8, 5, "Both new engines recover Abate Angelo and Abare's 141 Milk continuation, missing from IA. mOCR reads Fire, Filippo and Prince and retains the five ditto marks here; Tesseract adds noise and reads Hanover ay."),
    ("p161_R04", 7, 4, "mOCR reads Giuseppe and 125A correctly but drops four ditto marks. Tesseract reads Cer and 1254, and damages E B and S B h spacing."),
    ("p161_R05", 8, 4, "mOCR preserves Clarence M and Rox, where Tesseract damages both. mOCR drops four ditto marks. Both new engines read Boston pl; IA reads pi."),
    ("p161_R06", 7, 4, "Both new engines recover John W and Henry T's continuation and read Malden correctly. mOCR reads Devonshire; Tesseract reads Deyonshire. mOCR drops four ditto marks."),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_hashes(root):
    return {p.relative_to(root).as_posix(): sha(p)
            for p in sorted(root.rglob("*")) if p.is_file()}


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fields):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def png_pixel_hash(path):
    """Decode the RGB8, non-interlaced PNGs in these packs and validate CRCs.

    Matches ocr_review.image_digest without requiring an installed image library.
    JPEG-to-crop generation is not rerun by this audit.
    """
    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    offset, compressed = 8, bytearray()
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + length]
        crc = struct.unpack(">I", data[offset + 8 + length:offset + 12 + length])[0]
        assert zlib.crc32(kind + body) & 0xffffffff == crc
        if kind == b"IHDR":
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", body)
            assert (depth, color, compression, filtering, interlace) == (8, 2, 0, 0, 0)
        elif kind == b"IDAT":
            compressed.extend(body)
        offset += length + 12
        if kind == b"IEND":
            break
    raw = zlib.decompress(compressed)
    stride = width * 3
    assert len(raw) == height * (stride + 1)
    pixels, previous = bytearray(), bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind, row = raw[start], bytearray(raw[start + 1:start + stride + 1])
        assert kind in range(5)
        for i in range(stride):
            left = row[i - 3] if i >= 3 else 0
            up = previous[i]
            corner = previous[i - 3] if i >= 3 else 0
            if kind == 0:
                prediction = 0
            elif kind == 1:
                prediction = left
            elif kind == 2:
                prediction = up
            elif kind == 3:
                prediction = (left + up) // 2
            else:
                p = left + up - corner
                distances = [abs(p - v) for v in (left, up, corner)]
                prediction = (left, up, corner)[distances.index(min(distances))]
            row[i] = (row[i] + prediction) & 255
        pixels.extend(row)
        previous = row
    header = f"RGB:{width}x{height}:".encode()
    return hashlib.sha256(header + pixels).hexdigest(), [width, height]


def norm(text):
    return " ".join(text.split())


def text_stats(text):
    return {
        "normalized_characters": len(norm(text)),
        "whitespace_tokens": len(text.split()),
        "nonempty_output_lines": sum(bool(line.strip()) for line in text.splitlines()),
        "recognizable_leading_ditto_markers": sum(bool(re.match(r'^\s*[«»"“]', line)) for line in text.splitlines()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    roots = {method: args.workspace.resolve() / name for method, name in FOLDERS.items()}
    output = args.output.resolve()
    assert not any(output == p or p in output.parents or output in p.parents for p in roots.values())
    assert not output.exists(), "Use a new output directory; existing reviews must not be overwritten."
    snapshots = {method: tree_hashes(p) for method, p in roots.items()}
    records, runtimes, manifests, reviews = {}, {}, {}, {}
    for method, root in roots.items():
        manifest = json.loads((root / "inputs/manifest.json").read_text())
        manifests[method] = manifest
        assert manifest["source_sha256"] == IMAGE_SHA
        assert sha(root / "source" / IMAGE_NAME) == IMAGE_SHA
        assert sha(root / "source/p161_ocr.json") == IA_SHA
        identity = {k: manifest[k] for k in ["page_id", "source_sha256", "units"]}
        assert hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest() == manifest["units_sha256"]
        rows = read_csv(root / "predictions.csv")
        records[method] = {(r["unit_id"], r["method"]): r for r in rows}
        assert len(records[method]) == len(rows) == 24
        assert {r["method"] for r in rows} == {"ia_existing", method}
        runtime = json.loads((root / "ocr" / method / "runtime.json").read_text())
        runtimes[method] = runtime
        assert runtime["units_sha256"] == manifest["units_sha256"]
        assert len(runtime["runs"]) == 12
        run_lookup = {run["unit_id"]: run for run in runtime["runs"]}
        for unit in manifest["review_units"]:
            uid = unit["unit_id"]
            path = root / unit["image"]
            pixel_hash, size = png_pixel_hash(path)
            assert pixel_hash == unit["image_sha256"]
            assert sha(path) == unit["file_sha256"]
            box = unit["bbox"]
            assert size == [box[2] - box[0], box[3] - box[1]]
            run = run_lookup[uid]
            assert run["input_pixels_sha256"] == pixel_hash
            assert run["input_file_sha256"] == sha(path)
            for name in ["ia_existing", method]:
                row = records[method][(uid, name)]
                assert row["unit_image_sha256"] == pixel_hash
                assert row["status"] == "completed"
            directory = root / "ocr" / method / uid
            if method == "tesseract_units":
                assert run["returncode"] == 0
                for filename in ["raw.txt", "raw.tsv", "raw.hocr", "lines.json", "stderr.txt"]:
                    assert (directory / filename).is_file()
                lines = json.loads((directory / "lines.json").read_text())
                assert "\n".join(line["text"] for line in lines) == records[method][(uid, method)]["text"]
                tsv_rows = read_csv_tsv(directory / "raw.tsv")
                words = [r for r in tsv_rows if r["level"] == "5" and r["text"].strip()]
                assert norm(" ".join(r["text"] for r in words)) == norm(records[method][(uid, method)]["text"])
            else:
                assert run["status"] == "completed"
                assert run["generated_tokens"] < runtime["max_new_tokens"]
                assert (directory / "raw.txt").read_text() == records[method][(uid, method)]["text"]
                assert json.loads((directory / "run.json").read_text()) == run
                _, processor_size = png_pixel_hash(directory / "processor_input.png")
                assert [processor_size] == run["vision_image_sizes"]
        reviews[method] = read_csv(root / "manual_review.csv")
        assert len(reviews[method]) == 12
        assert all(row["review_status"] == "pending" and not row["gold_text"].strip() for row in reviews[method])

    left, right = (manifests[m] for m in FOLDERS)
    assert left == right, "Region definitions or checksums differ."
    units = left["review_units"]
    for unit in units:
        uid = unit["unit_id"]
        assert records["tesseract_units"][(uid, "ia_existing")] == records["dots_mocr_units"][(uid, "ia_existing")]
    assert reviews["tesseract_units"] == reviews["dots_mocr_units"]
    source_html = (roots["tesseract_units"] / "review.html").read_text()
    old_line = next(line for line in source_html.splitlines() if line.startswith("const DATA="))
    payload = json.loads(old_line[len("const DATA="):-1])
    assert payload["units_sha256"] == left["units_sha256"]
    assert payload["reviews"] == reviews["tesseract_units"]
    predictions = []
    metrics = {"methods": {}, "units": [], "human_verified_units": 0,
               "interpretation": "Output counts and assistant image observations are not human-gold accuracy scores."}
    for unit in payload["units"]:
        uid = unit["unit_id"]
        assert base64.b64decode(unit["image_data"].split(",", 1)[1]) == (roots["tesseract_units"] / ("inputs/" + uid + ".png")).read_bytes()
        unit["predictions"]["dots_mocr_units"] = records["dots_mocr_units"][(uid, "dots_mocr_units")]
        for method in METHODS:
            expected = records["dots_mocr_units" if method == "dots_mocr_units" else "tesseract_units"][(uid, method)]
            assert unit["predictions"][method] == expected
            predictions.append(copy.deepcopy(expected))
        metrics["units"].append({"unit_id": uid, **{m: text_stats(unit["predictions"][m]["text"]) for m in METHODS}})
    payload["methods"] = METHODS
    for method in METHODS:
        selected = [r for r in predictions if r["method"] == method]
        stats = {key: sum(text_stats(row["text"])[key] for row in selected) for key in text_stats("")}
        stats["completed_regions"] = sum(r["status"] == "completed" for r in selected)
        if method in runtimes:
            seconds = [r["seconds"] for r in runtimes[method]["runs"]]
            stats.update(recorded_region_seconds=round(sum(seconds), 3), median_region_seconds=statistics.median(seconds))
        metrics["methods"][method] = stats
    observations = []
    for uid, rows, dittos, note in OBSERVATIONS:
        observations.append({"unit_id": uid, "assistant_observed_printed_rows": rows,
                             "assistant_observed_leading_ditto_positions": dittos,
                             "assistant_observation": note, "human_verified": False})
    metrics["assistant_observed_printed_rows"] = sum(r[1] for r in OBSERVATIONS)
    metrics["assistant_observed_leading_ditto_positions"] = sum(r[2] for r in OBSERVATIONS)
    output.mkdir(parents=True)
    shutil.copytree(roots["tesseract_units"] / "source", output / "source")
    shutil.copytree(roots["tesseract_units"] / "inputs", output / "inputs")
    for method, root in roots.items():
        shutil.copytree(root / "ocr" / method, output / "ocr" / method)
        destination = output / "imported_provenance" / method
        destination.mkdir(parents=True)
        for name in ["run_manifest.json", "manual_review.csv", "verified_scores.csv"]:
            shutil.copy2(root / name, destination / name)
    fields = list(predictions[0])
    write_csv(output / "predictions.csv", predictions, fields)
    write_csv(output / "manual_review.csv", reviews["tesseract_units"], list(reviews["tesseract_units"][0]))
    score_fields = list(read_csv(roots["tesseract_units"] / "verified_scores.csv")[0])
    empty_scores = []
    for method in METHODS:
        empty_scores.append({field: (method if field == "method" else "" if field in ["CER", "WER"] else 12 if field == "total_review_units" else 0) for field in score_fields})
    write_csv(output / "verified_scores.csv", empty_scores, score_fields)
    new_line = "const DATA=" + json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c") + ";"
    (output / "review.html").write_text(source_html.replace(old_line, new_line, 1), encoding="utf-8")
    combined_manifest = json.loads((roots["tesseract_units"] / "run_manifest.json").read_text())
    combined_manifest.update(methods=METHODS, combined_from=list(FOLDERS.values()), ocr_rerun=False)
    write_json(output / "run_manifest.json", combined_manifest)
    write_json(output / "comparison_metrics.json", metrics)
    write_json(output / "assistant_image_observations.json", observations)
    write_json(output / "input_file_checksums.json", snapshots)
    write_json(output / "audit_checks.json", {
        "source_image_sha256": IMAGE_SHA, "ia_annotations_sha256": IA_SHA,
        "units_sha256": left["units_sha256"], "same_source_and_manifest": True,
        "all_24_crop_file_and_decoded_pixel_checksums_valid": True,
        "prediction_text_matches_raw_or_native_tsv_outputs": True,
        "all_12_model_processor_pngs_match_recorded_dimensions": True,
        "same_ia_predictions_in_both_packs": True, "human_verified_units": 0,
        "ocr_rerun": False, "original_inputs_unchanged": True,
        "scope_limit": "JPEG-to-crop generation and GPU inference were not rerun. Assistant image observations are not human gold.",
    })
    (output / "README.txt").write_text(
        "Open OCR_Comparison_Report.md for findings. Open review.html for three-way image review.\n"
        "This pack combines completed Colab outputs; it does not rerun OCR or correct model text.\n"
        "All 12 human transcriptions are still pending. No accuracy score is available yet.\n"
        "Review all regions. Priorities: L03 omissions, R03/R06 recovered entries, L01 layout, and ditto marks.\n"
        "Enter exact Human transcription, Reviewer and verified status, then Calculate CER / WER.\n"
        "Export reviewed CSV before closing or sharing. Browser storage alone is not a shared record.\n"
        "The exported CSV is compatible with either v2 notebook's step 5. That step scores the methods\n"
        "present in that notebook: use this merged review.html to calculate all three together.\n"
        "Assistant observations are kept separate and have not been used as gold text.\n",
        encoding="utf-8")
    for method, root in roots.items():
        assert snapshots[method] == tree_hashes(root), "An original input file changed."
    print(json.dumps(metrics["methods"], indent=2))
    print("Audit passed. Original inputs unchanged. Combined review:", output / "review.html")


def read_csv_tsv(path):
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


if __name__ == "__main__":
    main()
