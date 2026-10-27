"""Shared, self-contained OCR review workflow embedded in both Colab notebooks.

Review units come from fixed source-image regions, not from an OCR engine's hits.
Tesseract lines use native TSV line IDs. Human transcription stays separate.
"""

import base64
from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import time
import zipfile

from PIL import Image

VERSION = "2026-10-24-review-v2"
PAGE_ID = "bostonmassachuse1916112samp_leaf0163"
IMAGE_NAME = PAGE_ID + "_p161.jpg"
IMAGE_SHA = "a5949b1fb596c5acf388234964917e096908584e8ade49a75341d6a835c86f3d"
IA_SHA = "6cdd032291dbd76c11c7430fd2a7c918e6f6ef079c628db41420d81269a68edd"
CANVAS_ID = "https://iiif.archive.org/iiif/bostonmassachuse1916112samp$162/canvas"
IMAGE_URL = ("https://iiif.archive.org/image/iiif/3/bostonmassachuse1916112samp%2F"
             "bostonmassachuse1916112samp_jp2.zip%2Fbostonmassachuse1916112samp_jp2%2F"
             "bostonmassachuse1916112samp_0163.jp2/full/max/0/default.jpg")
IA_URL = ("https://iiif.archive.org/iiif/3/annotations/bostonmassachuse1916112samp/"
          "bostonmassachuse1916112samp_djvu.xml/163.json")
BODY_TOP, BODY_BOTTOM, SPLIT_X = 1645, 2680, 760
METHOD_LABELS = {
    "ia_existing": "IA existing OCR",
    "tesseract_units": "Tesseract / same review crops",
    "dots_mocr_units": "dots.mocr / same review crops",
    "tesseract_full_page": "Tesseract / original full-page run",
    "tesseract_columns": "Tesseract / original column runs",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def image_digest(path):
    """Hash decoded pixels so PNG encoder versions do not change region identity."""
    with Image.open(path) as image:
        image = image.convert("RGB")
        header = ("RGB:" + str(image.width) + "x" + str(image.height) + ":").encode()
        return hashlib.sha256(header + image.tobytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize(text):
    """Whitespace only: case, punctuation, ditto signs and digits are retained."""
    return re.sub(r"\s+", " ", text).strip()


def distance(a, b):
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        current = [i]
        for j, right in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def download_sources(root):
    """Download the exact two pilot files; an upload mode is also in the notebooks."""
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    root = Path(root)
    (root / "source").mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "BU-Spark-BPL-OCR-Review/2.0"
    session.mount("https://", HTTPAdapter(max_retries=Retry(
        total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])))
    try:
        for name, url, expected in [(IMAGE_NAME, IMAGE_URL, IMAGE_SHA),
                                     ("p161_ocr.json", IA_URL, IA_SHA)]:
            target = root / "source" / name
            if target.exists() and digest(target) == expected:
                continue
            partial = target.with_suffix(target.suffix + ".part")
            try:
                with session.get(url, stream=True, timeout=(15, 60)) as response:
                    response.raise_for_status()
                    with partial.open("wb") as handle:
                        for chunk in response.iter_content(1024 * 1024):
                            if chunk:
                                handle.write(chunk)
                if digest(partial) != expected:
                    raise ValueError("Source checksum changed: " + name + ". Use the original pilot files in upload mode.")
                partial.replace(target)
            finally:
                partial.unlink(missing_ok=True)
    finally:
        session.close()
    validate_sources(root)


def validate_sources(root):
    root = Path(root)
    for name, expected in [(IMAGE_NAME, IMAGE_SHA), ("p161_ocr.json", IA_SHA)]:
        if digest(root / "source" / name) != expected:
            raise ValueError("Wrong input file: " + name)
    with Image.open(root / "source" / IMAGE_NAME) as image:
        if image.size != (1680, 2799):
            raise ValueError("Unexpected source image dimensions")
    annotations = json.loads((root / "source/p161_ocr.json").read_text())
    if annotations["id"] != IA_URL or not all(
        item["target"].startswith(CANVAS_ID + "#xywh=") for item in annotations["items"]
    ):
        raise ValueError("IA annotations belong to another page")
    write_json(root / "source/provenance.json", {
        "page_id": PAGE_ID, "printed_page": 161, "scan_leaf": 163,
        "canvas_index_0based": 162, "image_sha256": IMAGE_SHA, "ia_sha256": IA_SHA,
        "image_url": IMAGE_URL, "ia_url": IA_URL,
        "note": "Exact existing pilot JPEG; archival JP2 resolution not evaluated.",
    })


def make_units(root):
    """Six strips per column. Move each proposed cut to a nearby ink-light row.

    Boundaries depend only on source pixels, never OCR output or known names.
    Strips tile the complete body region without gaps or overlapping pixels.
    """
    root = Path(root)
    import numpy as np
    with Image.open(root / "source" / IMAGE_NAME) as source:
        source = source.convert("RGB")
        gray = np.asarray(source.convert("L"))
        units = []
        for column, x0, x1 in [("L", 0, SPLIT_X), ("R", SPLIT_X, 1680)]:
            ink = (gray[:, x0:x1] < 110).sum(axis=1)
            cuts = [BODY_TOP]
            for i in range(1, 6):
                target = round(BODY_TOP + i * (BODY_BOTTOM - BODY_TOP) / 6)
                candidates = range(target - 10, target + 11)
                cut = min(candidates, key=lambda y: (int(ink[y-1:y+2].sum()), abs(y-target)))
                cuts.append(cut)
            cuts.append(BODY_BOTTOM)
            for i, (top, bottom) in enumerate(zip(cuts, cuts[1:]), 1):
                unit_id = "p161_" + column + f"{i:02d}"
                box = [x0, top, x1, bottom]
                path = root / "inputs" / (unit_id + ".png")
                path.parent.mkdir(parents=True, exist_ok=True)
                source.crop(box).save(path)
                units.append({"unit_id": unit_id, "column": column, "bbox": box,
                              "image": path.relative_to(root).as_posix(),
                              "image_sha256": image_digest(path),
                              "file_sha256": digest(path),
                              "top_cut_ink_pixels": int(ink[top]),
                              "bottom_cut_ink_pixels": int(ink[bottom-1])})
    identity = {"page_id": PAGE_ID, "source_sha256": IMAGE_SHA,
                "units": [{k: u[k] for k in ["unit_id", "bbox", "image_sha256"]} for u in units]}
    unit_hash = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    manifest = {"version": VERSION, "units_sha256": unit_hash, **identity,
                "description": "12 image-based review strips; not person records or gold labels.",
                "preprocessing": "Pixel-preserving crops only. Model processors may resize; log that separately.",
                "review_units": units}
    write_json(root / "inputs/manifest.json", manifest)
    return manifest


def ia_lines(root):
    annotations = json.loads((Path(root) / "source/p161_ocr.json").read_text())
    words = []
    for item in annotations["items"]:
        x, y, width, height = map(int, item["target"].split("#xywh=")[1].split(","))
        if BODY_TOP <= y < BODY_BOTTOM:
            words.append({"text": item["body"]["value"].strip(),
                          "bbox": [x, y, x + width, y + height]})
    result = []
    for column in ["L", "R"]:
        subset = [w for w in words if (w["bbox"][0] < SPLIT_X) == (column == "L")]
        bands = []
        for word in sorted(subset, key=lambda w: ((w["bbox"][1]+w["bbox"][3])/2, w["bbox"][0])):
            cy = (word["bbox"][1] + word["bbox"][3]) / 2
            if bands and abs(cy - statistics.median((w["bbox"][1]+w["bbox"][3])/2 for w in bands[-1])) < 10:
                bands[-1].append(word)
            else:
                bands.append([word])
        for index, band in enumerate(bands):
            result.append(line_from_words(band, column, "ia_" + str(index)))
    return result


def line_from_words(words, column, native_id):
    words = sorted(words, key=lambda w: w["bbox"][0])
    return {"column": column, "native_line_id": native_id,
            "text": " ".join(w["text"] for w in words),
            "cy": statistics.median((w["bbox"][1]+w["bbox"][3])/2 for w in words),
            "bbox": [min(w["bbox"][0] for w in words), min(w["bbox"][1] for w in words),
                     max(w["bbox"][2] for w in words), max(w["bbox"][3] for w in words)]}


def native_tesseract_lines(words, body_only=True):
    """Fix: group by native line ID, not individual word-box y centers.

    Include column identity to avoid combining columns even if a native ID spans them.
    Input native_id contains page:block:paragraph:line:word; drop only the last part.
    """
    groups = defaultdict(list)
    for word in words:
        if not word["text"].strip() or (body_only and not BODY_TOP <= word["bbox"][1] < BODY_BOTTOM):
            continue
        column = "L" if word["bbox"][0] < SPLIT_X else "R"
        line_id = word["native_id"].rsplit(":", 1)[0]
        groups[(column, line_id)].append(word)
    lines = [line_from_words(group, column, key) for (column, key), group in groups.items()]
    return sorted(lines, key=lambda line: (line["column"], line["cy"], line["bbox"][0]))


def parse_tsv(path, offset=(0, 0)):
    words = []
    for row in read_tsv(path):
        if row["level"] != "5" or not row["text"].strip():
            continue
        x, y, width, height = (int(row[k]) for k in ["left", "top", "width", "height"])
        x, y = x + offset[0], y + offset[1]
        words.append({"text": row["text"], "bbox": [x, y, x+width, y+height],
                      "confidence": float(row["conf"]),
                      "native_id": ":".join(row[k] for k in ["page_num", "block_num", "par_num", "line_num", "word_num"])})
    return words


def read_tsv(path):
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


PREDICTION_FIELDS = ["unit_id", "method", "input_mode", "unit_image_sha256", "text", "status", "notes"]


def lines_to_predictions(lines, manifest, method, input_mode):
    result = []
    for unit in manifest["review_units"]:
        top, bottom = unit["bbox"][1], unit["bbox"][3]
        selected = [line for line in lines if line["column"] == unit["column"] and top <= line["cy"] < bottom]
        selected.sort(key=lambda line: (line["cy"], line["bbox"][0]))
        result.append({"unit_id": unit["unit_id"], "method": method, "input_mode": input_mode,
                       "unit_image_sha256": unit["image_sha256"],
                       "text": "\n".join(line["text"] for line in selected), "status": "completed",
                       "notes": "Position-based assignment; compare with scan. Native source lines remain available."})
    return result


def run_tesseract_units(root, manifest):
    root = Path(root)
    engine = shutil.which("tesseract")
    if not engine:
        raise RuntimeError("Tesseract is missing. Run the Colab setup cell.")
    version = subprocess.run([engine, "--version"], capture_output=True, text=True, check=True)
    languages = subprocess.run([engine, "--list-langs"], capture_output=True, text=True, check=True)
    listing = languages.stdout + languages.stderr
    if "eng" not in listing.splitlines():
        raise RuntimeError("The Tesseract eng model is missing")
    match = re.search(r'in "([^"\n]+)"', listing)
    model_path = Path(match.group(1)) / "eng.traineddata" if match else None
    runtime = {"engine": "tesseract", "version": version.stdout + version.stderr,
               "language_listing": listing,
               "english_model_sha256": digest(model_path) if model_path and model_path.exists() else None,
               "oem": 1, "psm": 6, "units_sha256": manifest["units_sha256"], "runs": []}
    predictions = []
    for unit in manifest["review_units"]:
        image = root / unit["image"]
        if image_digest(image) != unit["image_sha256"]:
            raise ValueError("Review input changed")
        directory = root / "ocr/tesseract_units" / unit["unit_id"]
        directory.mkdir(parents=True, exist_ok=True)
        base = directory / "raw"
        command = [engine, str(image), str(base), "-l", "eng", "--oem", "1", "--psm", "6", "txt", "tsv", "hocr"]
        start = time.perf_counter()
        completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
        (directory / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
        record = {"unit_id": unit["unit_id"], "command": command, "returncode": completed.returncode,
                  "seconds": round(time.perf_counter()-start, 3), "input_pixels_sha256": unit["image_sha256"],
                  "input_file_sha256": digest(image)}
        runtime["runs"].append(record)
        write_json(root / "ocr/tesseract_units/runtime.json", runtime)
        if completed.returncode or not all(base.with_suffix(ext).exists() for ext in [".txt", ".tsv", ".hocr"]):
            raise RuntimeError("Tesseract failed for " + unit["unit_id"] + ": " + completed.stderr)
        words = parse_tsv(base.with_suffix(".tsv"), unit["bbox"][:2])
        lines = native_tesseract_lines(words)
        write_json(directory / "lines.json", lines)
        predictions.append({"unit_id": unit["unit_id"], "method": "tesseract_units",
                            "input_mode": "same_review_crop_psm6", "unit_image_sha256": unit["image_sha256"],
                            "text": "\n".join(line["text"] for line in lines),
                            "status": "completed", "notes": "Native TSV line IDs; no word-center regrouping."})
        print("Tesseract:", unit["unit_id"])
    return predictions


def import_bundle(archive, destination):
    """Read only known files, never extract arbitrary archive paths."""
    destination = Path(destination)
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        manifests = [name for name in names if name.endswith("inputs/manifest.json")]
        if len(manifests) != 1:
            raise ValueError("Expected one review bundle manifest")
        prefix = manifests[0][:-len("inputs/manifest.json")]
        manifest = json.loads(bundle.read(manifests[0]))
        if manifest.get("source_sha256") != IMAGE_SHA or "units_sha256" not in manifest:
            raise ValueError("Use the new v2 review ZIP, not the old v1 results ZIP")
        for relative in ["source/" + IMAGE_NAME, "source/p161_ocr.json"]:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.read(prefix + relative))
        validate_sources(destination)
        current = make_units(destination)
        if current["units_sha256"] != manifest["units_sha256"]:
            raise ValueError("Review-region definitions differ; do not merge these predictions")
        predictions = list(csv.DictReader(io.StringIO(bundle.read(prefix + "predictions.csv").decode("utf-8-sig"))))
        validate_predictions(predictions, current)
        old_review = prefix + "manual_review.csv"
        if old_review in names and not (destination / "manual_review.csv").exists():
            (destination / "manual_review.csv").write_bytes(bundle.read(old_review))
        # Preserve the provenance of imported model outputs, not only their text.
        for name in names:
            relative = name[len(prefix):] if name.startswith(prefix) else ""
            if (relative.startswith("ocr/") and relative.endswith("runtime.json")) or relative == "run_manifest.json":
                if ".." in Path(relative).parts or Path(relative).is_absolute():
                    raise ValueError("Unsafe bundle path")
                target = destination / "imported_provenance" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(name))
    return current, predictions


def validate_predictions(predictions, manifest):
    expected = {u["unit_id"]: u["image_sha256"] for u in manifest["review_units"]}
    seen = set()
    for prediction in predictions:
        key = (prediction["unit_id"], prediction["method"])
        if key in seen:
            raise ValueError("Duplicate prediction: " + str(key))
        seen.add(key)
        if expected.get(prediction["unit_id"]) != prediction["unit_image_sha256"]:
            raise ValueError("Prediction belongs to another image region")


REVIEW_FIELDS = ["unit_id", "units_sha256", "unit_image_sha256", "reviewer", "review_status", "gold_text", "notes"]


def load_reviews(path, manifest):
    expected = {u["unit_id"]: u["image_sha256"] for u in manifest["review_units"]}
    result = {}
    if Path(path).exists():
        for row in read_csv(path):
            unit_id = row["unit_id"]
            if unit_id in result:
                raise ValueError("Duplicate reviewed unit: " + unit_id)
            if row.get("units_sha256") != manifest["units_sha256"] or row.get("unit_image_sha256") != expected.get(unit_id):
                raise ValueError("Reviewed CSV belongs to another source or set of regions")
            result[unit_id] = row
    return result


def score_verified(reviews, predictions, manifest):
    """Missing/failed predictions count as deletions; all methods use the same gold units."""
    validate_predictions(predictions, manifest)
    lookup = {(r["unit_id"], r["method"]): r for r in predictions}
    methods = sorted({r["method"] for r in predictions})
    verified = [row for row in reviews.values() if row.get("review_status") == "verified"
                and row.get("reviewer", "").strip() and normalize(row.get("gold_text", ""))]
    scores = []
    for method in methods:
        chars = tokens = char_errors = word_errors = exact = failed = 0
        for row in verified:
            gold = normalize(row["gold_text"])
            prediction = lookup.get((row["unit_id"], method))
            if prediction is None or prediction["status"] != "completed":
                text = ""
                failed += 1
            else:
                text = normalize(prediction["text"])
            chars += len(gold)
            tokens += len(gold.split())
            char_errors += distance(gold, text)
            word_errors += distance(gold.split(), text.split())
            exact += gold == text
        scores.append({"method": method, "verified_units": len(verified),
                       "total_review_units": len(manifest["review_units"]),
                       "character_errors": char_errors, "gold_characters": chars,
                       "CER": char_errors/chars if chars else None,
                       "word_errors": word_errors, "gold_words": tokens,
                       "WER": word_errors/tokens if tokens else None,
                       "exact_units": exact, "failed_or_missing_units": failed})
    return scores


def build_review(root, manifest, predictions, reviewed_csv=None):
    root = Path(root)
    validate_predictions(predictions, manifest)
    write_csv(root / "predictions.csv", predictions, PREDICTION_FIELDS)
    reviews = load_reviews(root / "manual_review.csv", manifest)
    if reviewed_csv:
        reviews.update(load_reviews(reviewed_csv, manifest))
    rows = []
    for unit in manifest["review_units"]:
        unit_id = unit["unit_id"]
        rows.append(reviews.get(unit_id, {"unit_id": unit_id, "units_sha256": manifest["units_sha256"],
                    "unit_image_sha256": unit["image_sha256"], "reviewer": "", "review_status": "pending",
                    "gold_text": "", "notes": ""}))
    write_csv(root / "manual_review.csv", rows, REVIEW_FIELDS)
    reviews = {row["unit_id"]: row for row in rows}
    scores = score_verified(reviews, predictions, manifest)
    write_csv(root / "verified_scores.csv", scores, list(scores[0]) if scores else ["method", "verified_units", "CER", "WER"])
    lookup = {(p["unit_id"], p["method"]): p for p in predictions}
    methods = sorted({p["method"] for p in predictions})
    data = {"version": VERSION, "units_sha256": manifest["units_sha256"], "methods": methods,
            "labels": METHOD_LABELS, "reviews": rows, "units": []}
    for unit in manifest["review_units"]:
        data["units"].append({**unit,
            "image_data": "data:image/png;base64," + base64.b64encode((root/unit["image"]).read_bytes()).decode(),
            "predictions": {method: lookup.get((unit["unit_id"], method),
                {"text": "", "status": "missing", "input_mode": "", "notes": "No prediction"}) for method in methods}})
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    (root / "review.html").write_text(REVIEW_HTML.replace("__REVIEW_DATA__", payload), encoding="utf-8")
    write_json(root / "run_manifest.json", {
        "workflow_version": VERSION, "source_sha256": IMAGE_SHA, "units_sha256": manifest["units_sha256"],
        "methods": methods, "review_units": len(rows),
        "verified_units": scores[0]["verified_units"] if scores else 0,
        "scoring": "Whitespace normalized only. CER/WER use human-gold denominators. No gold means no accuracy.",
        "experiment": "Development page 161; 12 strips cover body including companies. Not 12 people or an independent test.",
        "comparability": "tesseract_units and dots_mocr_units use identical crops. Old full-page/column outputs use different context and are labeled separately.",
    })
    (root / "README.txt").write_text(
        "START HERE: open review.html in a browser. No server or installation is needed.\n"
        "1. Optionally hide OCR while transcribing. Read the image and enter exact printed text.\n"
        "2. Preserve abbreviations, ditto marks, digits and line-ending hyphens. Do not infer names.\n"
        "3. Enter reviewer and set Verified only when confident; use Uncertain for unreadable text.\n"
        "4. Export reviewed CSV before closing or sharing. Browser storage is only a convenience.\n"
        "5. Import that CSV into another review.html to carry gold text across OCR engines.\n"
        "6. Calculate scores: only verified units with a reviewer and gold text are scored.\n"
        "predictions.csv holds model outputs; manual_review.csv holds human input; neither overwrites the other.\n"
        "Failed or missing model outputs are scored as omissions, not silently dropped.\n"
        "IA is a baseline, not gold. Do not compare engine confidence or word counts as accuracy.\n"
        "Crops may contain several entries, companies or cross-references. This is development material.\n",
        encoding="utf-8")
    return root / "review.html"


def bundle_results(root):
    root = Path(root)
    return Path(shutil.make_archive(str(root.parent/(root.name+"_results")), "zip", root_dir=root))


REVIEW_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>BPL OCR review</title><style>
body{font:15px system-ui,sans-serif;max-width:1500px;margin:24px auto;padding:0 20px;background:#f5f6f8;color:#17212b}
h1{font-size:26px;margin-bottom:6px}header{position:sticky;top:0;background:#f5f6f8;padding:8px 0;z-index:2}
button,select,input{padding:7px;font:inherit}button{cursor:pointer}textarea{width:100%;box-sizing:border-box;font:15px ui-monospace,monospace;line-height:1.5;padding:10px}
.card{background:white;border:1px solid #ccd3dd;border-radius:8px;padding:18px;margin:18px 0}.scan{max-width:100%;height:auto;border:1px solid #ddd}
.predictions{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.prediction{background:#f4f7fa;padding:10px;min-width:0}pre{white-space:pre-wrap;word-break:break-word;font:14px ui-monospace,monospace;line-height:1.5}
.muted{color:#5b6573;font-size:13px}.bad{color:#a72727}.gold{margin-top:14px}.hide-ocr .predictions{display:none}table{border-collapse:collapse;background:white}td,th{border:1px solid #ccd3dd;padding:7px}.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
</style></head><body><h1>BPL OCR review · printed page 161</h1>
<p>Read each scan, enter the exact printed text, and verify it. IA is a baseline, not ground truth. Each card is a source-image strip, not one person.</p>
<header><div class="toolbar"><button id="export">Export reviewed CSV</button><label>Import reviewed CSV <input id="import" type="file" accept=".csv"></label><button id="score">Calculate CER / WER</button><label><input id="hide" type="checkbox">Hide OCR while transcribing</label><select id="filter"><option value="all">All regions</option><option value="pending">Not verified</option><option value="different">OCR differs</option></select></div><p id="progress" class="muted"></p></header>
<p class="muted">Whitespace is normalized for scoring; spelling, case, punctuation, ditto signs and digits are retained. Full-page/column context runs are labeled separately from identical-crop runs. Keep uncertain regions unverified. Export before sharing: browser storage does not travel with this file.</p>
<div id="scores"></div><main id="cards"></main><script>
const DATA=__REVIEW_DATA__;
const $=s=>document.querySelector(s), norm=s=>String(s||'').replace(/\s+/g,' ').trim();
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state=Object.fromEntries(DATA.reviews.map(r=>[r.unit_id,{...r}]));
const storageKey='bpl-review-'+DATA.units_sha256;
try{const cached=JSON.parse(localStorage.getItem(storageKey)||'null');if(cached)for(const id in state)if(cached[id]&&cached[id].unit_image_sha256===state[id].unit_image_sha256)state[id]={...state[id],...cached[id]};}catch(e){}
function persist(){try{localStorage.setItem(storageKey,JSON.stringify(state));}catch(e){}$('#scores').innerHTML='';progress();}
function ready(r){return r.review_status==='verified'&&norm(r.reviewer)&&norm(r.gold_text);}
function progress(){const n=Object.values(state).filter(ready).length;$('#progress').textContent=n+' / '+DATA.units.length+' regions ready for scoring. '+(n?'Scores apply only to these regions.':'No human accuracy score yet.');}
function render(){const filter=$('#filter').value;$('#cards').innerHTML=DATA.units.filter(u=>{if(filter==='pending')return !ready(state[u.unit_id]);if(filter==='different')return new Set(DATA.methods.map(m=>norm(u.predictions[m].text))).size>1;return true;}).map(u=>{const r=state[u.unit_id];return `<section class="card" data-id="${u.unit_id}"><h2>${u.unit_id} <span class="muted">source pixels ${u.bbox.join(', ')}</span></h2><img class="scan" src="${u.image_data}" alt="Original scan ${u.unit_id}"><div class="predictions">${DATA.methods.map(m=>{const p=u.predictions[m];return `<div class="prediction"><strong>${esc(DATA.labels[m]||m)}</strong><div class="muted">${esc(p.input_mode||'')} · ${esc(p.status)}</div><pre>${esc(p.text||'[No text]')}</pre>${p.notes?`<div class="muted">${esc(p.notes)}</div>`:''}</div>`;}).join('')}</div><div class="gold"><label><strong>Human transcription</strong><textarea data-field="gold_text" rows="6" placeholder="Type exactly what is printed. Preserve ditto signs and abbreviations.">${esc(r.gold_text)}</textarea></label><div class="toolbar"><label>Reviewer <input data-field="reviewer" value="${esc(r.reviewer)}"></label><label>Status <select data-field="review_status">${['pending','uncertain','verified'].map(s=>`<option ${r.review_status===s?'selected':''}>${s}</option>`).join('')}</select></label><label>Notes <input data-field="notes" value="${esc(r.notes)}"></label></div></div></section>`;}).join('');progress();}
$('#cards').addEventListener('input',e=>{const f=e.target.dataset.field;if(f){const id=e.target.closest('.card').dataset.id;state[id][f]=e.target.value;persist();}});
$('#filter').onchange=render;$('#hide').onchange=e=>document.body.classList.toggle('hide-ocr',e.target.checked);
const fields=['unit_id','units_sha256','unit_image_sha256','reviewer','review_status','gold_text','notes'];
function quote(s){return '"'+String(s??'').replace(/"/g,'""')+'"';}
$('#export').onclick=()=>{const allFields=[...fields,...DATA.methods.map(m=>m+'_text')];const rows=DATA.units.map(u=>({...state[u.unit_id],...Object.fromEntries(DATA.methods.map(m=>[m+'_text',u.predictions[m].text]))}));const csv='\uFEFF'+allFields.map(quote).join(',')+'\r\n'+rows.map(r=>allFields.map(f=>quote(r[f])).join(',')).join('\r\n');const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));a.download='bpl_p161_reviewed.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
function parseCSV(text){text=text.replace(/^\uFEFF/,'');const rows=[];let row=[],field='',quoted=false;for(let i=0;i<text.length;i++){let c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++;}else quoted=!quoted;}else if(c===','&&!quoted){row.push(field);field='';}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(field);if(row.some(v=>v!==''))rows.push(row);row=[];field='';}else field+=c;}if(quoted)throw Error('Unclosed CSV quote');if(field!==''||row.length){row.push(field);rows.push(row);}const header=rows.shift();return rows.map(r=>Object.fromEntries(header.map((h,i)=>[h,r[i]||''])));}
$('#import').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;const rows=parseCSV(await file.text());const ids=new Set();for(const r of rows){if(ids.has(r.unit_id)||!state[r.unit_id]||r.units_sha256!==DATA.units_sha256||r.unit_image_sha256!==state[r.unit_id].unit_image_sha256)throw Error('Wrong source/regions or duplicate unit IDs');ids.add(r.unit_id);}for(const r of rows)for(const f of fields)if(f in r)state[r.unit_id][f]=r[f];persist();render();alert('Human review imported. OCR predictions were not changed.');}catch(err){alert(err.message);}};
function edit(a,b){if(a.length<b.length)[a,b]=[b,a];let prev=Array.from({length:b.length+1},(_,i)=>i);for(let i=1;i<=a.length;i++){const cur=[i];for(let j=1;j<=b.length;j++)cur.push(Math.min(cur[j-1]+1,prev[j]+1,prev[j-1]+(a[i-1]===b[j-1]?0:1)));prev=cur;}return prev[b.length];}
$('#score').onclick=()=>{const units=DATA.units.filter(u=>ready(state[u.unit_id]));if(!units.length){$('#scores').textContent='No verified human transcription with reviewer yet. Scores are unavailable.';return;}const rows=DATA.methods.map(m=>{let ce=0,we=0,nc=0,nw=0,exact=0,failed=0;for(const u of units){const g=norm(state[u.unit_id].gold_text),p=u.predictions[m];const t=p.status==='completed'?norm(p.text):'';if(p.status!=='completed')failed++;ce+=edit(Array.from(g),Array.from(t));we+=edit(g.split(/\s+/),t?t.split(/\s+/):[]);nc+=Array.from(g).length;nw+=g.split(/\s+/).length;exact+=g===t?1:0;}return `<tr><td>${esc(DATA.labels[m]||m)}</td><td>${units.length}</td><td>${(100*ce/nc).toFixed(2)}%</td><td>${(100*we/nw).toFixed(2)}%</td><td>${exact}/${units.length}</td><td>${failed}</td></tr>`;});$('#scores').innerHTML='<h2>Human-verified regions only</h2><table><thead><tr><th>Method</th><th>Verified regions</th><th>CER ↓</th><th>WER ↓</th><th>Exact regions</th><th>Failed/missing</th></tr></thead><tbody>'+rows.join('')+'</tbody></table><p class="muted">Same human text and same regions for every method. CER/WER can exceed 100% when insertions are numerous. Results describe this reviewed development sample.</p>';};
render();
</script></body></html>'''
