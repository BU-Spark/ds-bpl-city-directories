"""Offline cross-page diagnostics. Flags are review candidates, never text edits."""

from collections import Counter
import csv
import math
from pathlib import Path
import statistics

from .io import identity, read_json, sha256_file, write_csv, write_json
from .manifest import load_manifest

PAGE_FIELDS = ("leaf_num", "printed_page", "ocr_role", "status", "detected_lines", "recognized_words",
               "source_width", "source_height", "mean_word_confidence", "words_below_confidence_50",
               "source_retrieval", "gutter_x", "image_midpoint_x", "left_start_x", "right_start_x", "column_estimate_status",
               "body_left_rows", "body_right_rows", "native_body_column_segments", "vertical_symbol_candidates",
               "tall_line_candidates", "cross_gutter_candidates", "order_backtrack_candidates",
               "header_candidates", "engine_s", "integrity_status", "run_id", "source_page_url")
FLAG_FIELDS = ("leaf_num", "printed_page", "line_id", "native_reading_order", "column_candidate",
               "x0", "y0", "x1", "y1", "word_count", "mean_word_confidence", "text", "review_flags")


def read_lines(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in ("x0", "y0", "x1", "y1", "mean_word_confidence"):
            row[key] = float(row[key]) if row[key] else None
        for key in ("reading_order", "word_count", "leaf_num", "block_num", "par_num", "line_num"):
            row[key] = int(row[key])
    return rows


def review_body_y(page):
    """Declared diagnostic windows, not production entry/margin masks."""
    if page["section"] == "abbreviations_and_general_directory":
        return 1645, 2678
    if page["ocr_role"] == "supplementary":
        return 1180, 2240
    return 100, page["expected_height"] - 110


def column_geometry(rows, width, body_y):
    top, bottom = body_y
    eligible = [r for r in rows if r["word_count"] >= 4 and r["y0"] >= top and r["y1"] <= bottom
                and 10 < r["y1"] - r["y0"] < 65 and r["x1"] - r["x0"] > width * .14]
    if len(eligible) < 6:
        return {"status": "unresolved", "gutter_x": width / 2, "left_start_x": None, "right_start_x": None}
    starts = [r["x0"] for r in eligible]
    centers = [min(starts), max(starts)]
    for _ in range(20):
        groups = [[x for x in starts if abs(x - c) <= abs(x - centers[1 - i])] for i, c in enumerate(centers)]
        if min(map(len, groups)) < 3:
            return {"status": "unresolved", "gutter_x": width / 2, "left_start_x": None, "right_start_x": None}
        new = [statistics.median(g) for g in groups]
        if new == centers:
            break
        centers = new
    if centers[1] - centers[0] < width * .25:
        return {"status": "unresolved", "gutter_x": width / 2, "left_start_x": None, "right_start_x": None}
    left = [r for r in eligible if abs(r["x0"] - centers[0]) < abs(r["x0"] - centers[1])]
    # Full-width merged OCR rows must not move the gutter inside the right
    # column. Infer the edge only from rows ending before the right starts.
    edges = sorted(r["x1"] for r in left if r["x1"] < centers[1] - width * .015)
    if len(edges) < 3:
        return {"status": "unresolved", "gutter_x": width / 2,
                "left_start_x": centers[0], "right_start_x": centers[1]}
    gutter = (edges[round((len(edges) - 1) * .9)] + centers[1]) / 2
    return {"status": "two_start_clusters", "gutter_x": round(gutter, 3),
            "left_start_x": centers[0], "right_start_x": centers[1]}


def line_diagnostics(rows, page, geometry):
    top, bottom = review_body_y(page)
    width, height = page["expected_width"], page["expected_height"]
    normal_heights = [r["y1"] - r["y0"] for r in rows if r["word_count"] >= 4 and 10 < r["y1"] - r["y0"] < 65]
    median_height = statistics.median(normal_heights) if normal_heights else 25
    result, counts, segments, previous = [], Counter(), [], {}
    gutter = geometry["gutter_x"]
    for row in rows:
        flags = []
        w, h = row["x1"] - row["x0"], row["y1"] - row["y0"]
        body = row["y0"] >= top and row["y1"] <= bottom
        header = row["y0"] < height * .1 and (("BOSTON" in row["text"] and "DIRECTORY" in row["text"])
                  or row["text"].strip() == str(page["printed_page"]))
        if header:
            flags.append("header_candidate")
        vertical = w <= max(45, width * .035) and h >= max(65, median_height * 2.5) and h > w * 2.5
        if vertical:
            flags.append("vertical_symbol_candidate")
        if body and h > median_height * 1.65 and w > width * .12:
            flags.append("tall_line_candidate")
        if body and not header and row["x0"] < gutter - width * .015 and row["x1"] > gutter + width * .015:
            flags.append("cross_gutter_candidate")
        column = "L" if (row["x0"] + row["x1"]) / 2 < gutter else "R"
        if body and not header and not vertical:
            if column in previous and row["y0"] < previous[column]["y0"] - median_height * .75:
                flags.append("order_backtrack_candidate")
            previous[column] = row
            if row["word_count"] >= 4 and h < median_height * 1.65:
                if not segments or segments[-1] != column:
                    segments.append(column)
        counts.update(flags)
        result.append({"leaf_num": page["leaf_num"], "printed_page": page["printed_page"],
                       "line_id": row["line_id"], "native_reading_order": row["reading_order"],
                       "column_candidate": column if body else "outside_review_body",
                       **{k: row[k] for k in ("x0", "y0", "x1", "y1", "word_count", "mean_word_confidence", "text")},
                       "review_flags": "|".join(flags)})
    return result, counts, "".join(segments)


def verify_run(folder, manifest):
    """Check saved provenance and exports before drawing conclusions about OCR."""
    from PIL import Image
    folder = Path(folder)
    record = read_json(folder / "run.json")
    if record["status"] != "completed" or record["manifest_id"] != manifest["manifest_id"]:
        raise ValueError("Only completed runs from the selected source manifest can be reviewed")
    if record["config_id"] != identity(manifest["config"]) or identity(record["settings"]) != record["settings_id"]:
        raise ValueError("Run configuration/settings identity changed")
    if any(record["settings"].get(k) != v for k, v in manifest["config"]["ocr"].items()):
        raise ValueError("Run does not use the selected OCR baseline")
    expected = next(p for p in manifest["pages"] if p["leaf_num"] == record["page"]["leaf_num"])
    if record["page"] != expected:
        raise ValueError("Run page metadata differs from source manifest")
    if not {"raw/page.txt", "raw/page.tsv", "raw/page.hocr", "lines.csv"}.issubset(record["outputs"]):
        raise ValueError("Missing required OCR output receipt")
    for name, digest in record["outputs"].items():
        if sha256_file(folder / name) != digest:
            raise ValueError("Changed OCR output: " + str(folder / name))
    source = folder.parents[2] / record["source"]["image_path_from_work_dir"]
    if sha256_file(source) != record["source"]["sha256"]:
        raise ValueError("Changed review source image")
    with Image.open(source) as image:
        if list(image.size) != [expected["expected_width"], expected["expected_height"]]:
            raise ValueError("Review source dimensions changed")
    rows = read_lines(folder / "lines.csv")
    if len(rows) != record["detected_lines"] or len({r["line_id"] for r in rows}) != len(rows):
        raise ValueError("Missing/duplicate exported line IDs")
    if [r["reading_order"] for r in rows] != list(range(1, len(rows) + 1)):
        raise ValueError("Exported reading-order sequence changed")
    # Re-parse the retained native TSV to detect CSV export/provenance changes;
    # this validates serialization, not recognition accuracy.
    from .engine import parse_tsv
    rebuilt = parse_tsv(folder / "raw/page.tsv", expected, image_sha256=record["source"]["sha256"],
                        settings_id=record["settings_id"], config=manifest["config"])
    if len(rebuilt) != len(rows):
        raise ValueError("CSV line count differs from the native TSV")
    for actual, native in zip(rows, rebuilt):
        for key in ("line_id", "text", "reading_order", "x0", "y0", "x1", "y1", "image_sha256", "settings_id", "source_page_url", "source_image_url"):
            if actual[key] != native[key]:
                raise ValueError("CSV differs from native TSV/provenance: " + key)
        if not all(math.isfinite(actual[k]) for k in ("x0", "y0", "x1", "y1")) or not (
            0 <= actual["x0"] < actual["x1"] <= expected["expected_width"] and
            0 <= actual["y0"] < actual["y1"] <= expected["expected_height"]):
            raise ValueError("Invalid source-coordinate line box")
    return record, rows, source


def build_review(run_index, manifest_path, destination):
    index, manifest = read_json(run_index), load_manifest(manifest_path)
    if index["plan"]["manifest_id"] != manifest["manifest_id"]:
        raise ValueError("Pilot plan uses a different manifest")
    expected_leaves = [p["leaf_num"] for p in index["plan"]["pages"]]
    if len(set(expected_leaves)) != len(expected_leaves):
        raise ValueError("Pilot selection contains duplicate leaves")
    runs = {r["leaf_num"]: r for r in index["runs"]}
    if len(runs) != len(index["runs"]) or set(runs) != set(expected_leaves):
        raise ValueError("Run index must account for every selected leaf exactly once")
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)
    pages, all_flags, receipts = [], [], []
    for leaf in expected_leaves:
        choice = runs[leaf]
        if choice["status"] != "completed":
            raise ValueError("Pilot is incomplete; resolve and retain failed attempts before finalizing review")
        record, rows, source = verify_run(choice["run_directory"], manifest)
        page = record["page"]
        geometry = column_geometry(rows, page["expected_width"], review_body_y(page))
        flagged, counts, segments = line_diagnostics(rows, page, geometry)
        with (Path(choice["run_directory"]) / "raw/page.tsv").open(encoding="utf-8", newline="") as handle:
            words = [w for w in csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE) if w["level"] == "5" and w["text"].strip()]
        confidence = [float(w["conf"]) for w in words if float(w["conf"]) >= 0]
        pages.append({"leaf_num": leaf, "printed_page": page["printed_page"], "ocr_role": page["ocr_role"],
                      "status": record["status"], "detected_lines": len(rows), "recognized_words": len(words),
                      "source_width": page["expected_width"], "source_height": page["expected_height"],
                      "mean_word_confidence": round(statistics.mean(confidence), 3) if confidence else None,
                      "words_below_confidence_50": sum(c < 50 for c in confidence),
                      "source_retrieval": "bookreader_native_alias" if record["source"].get("retrieval_url") else "iiif_native_or_verified_cache",
                      "gutter_x": geometry["gutter_x"], "image_midpoint_x": page["expected_width"] / 2,
                      "left_start_x": geometry["left_start_x"], "right_start_x": geometry["right_start_x"],
                      "column_estimate_status": geometry["status"],
                      "body_left_rows": sum(r["column_candidate"] == "L" for r in flagged),
                      "body_right_rows": sum(r["column_candidate"] == "R" for r in flagged),
                      "native_body_column_segments": segments,
                      "vertical_symbol_candidates": counts["vertical_symbol_candidate"],
                      "tall_line_candidates": counts["tall_line_candidate"],
                      "cross_gutter_candidates": counts["cross_gutter_candidate"],
                      "order_backtrack_candidates": counts["order_backtrack_candidate"],
                      "header_candidates": counts["header_candidate"],
                      "engine_s": round(record["durations_s"]["engine"], 3),
                      "integrity_status": "passed", "run_id": record["run_id"], "source_page_url": page["source_page_url"]})
        all_flags.extend(flagged)
        receipts.append({"leaf_num": leaf, "run_directory": choice["run_directory"],
                         "previous_attempts": choice.get("previous_attempts", []), "record": record})
    write_csv(output / "pages.csv", pages, PAGE_FIELDS)
    write_csv(output / "line_flags.csv", all_flags, FLAG_FIELDS)
    write_json(output / "run_records.json", receipts)
    summary = {"format": "bpl-cross-page-review-v1", "manifest_id": manifest["manifest_id"],
               "review_date": index["plan"]["review_date"], "sampling": index["plan"]["selection_method"],
               "pages": len(pages), "detected_lines": sum(p["detected_lines"] for p in pages),
               "recognized_words": sum(p["recognized_words"] for p in pages),
               "source_retrieval_methods": dict(Counter(p["source_retrieval"] for p in pages)),
               "diagnostic_code_sha256": sha256_file(__file__),
               "diagnostic_policy": {"low_word_confidence_threshold": 50, "vertical_shape": "width <= max(45, 0.035*page_width), height >= max(65, 2.5*median_text_height), height > 2.5*width", "tall_line_height_ratio": 1.65, "order_backtrack_height_ratio": 0.75, "automatic_text_edits": False},
               "verified_integrity_pages": sum(p["integrity_status"] == "passed" for p in pages),
               "engine_seconds": round(sum(p["engine_s"] for p in pages), 3),
               "flag_counts": dict(Counter(f for r in all_flags for f in r["review_flags"].split("|") if f)),
               "meaning": "Automated diagnostic candidates, not verified error counts, accuracy, resident counts or exhaustive line coverage. Manual findings are recorded separately."}
    write_json(output / "summary.json", summary)
    return summary
