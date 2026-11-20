"""Pinned Tesseract full-page recognition and original-coordinate line export."""

from collections import OrderedDict
import csv
import io
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

from .io import download, sha256_file

LINE_FIELDS = ("volume_id", "page_id", "leaf_num", "bookreader_index", "printed_page", "section",
               "line_id", "reading_order", "block_num", "par_num", "line_num", "x0", "y0", "x1", "y1",
               "word_count", "mean_word_confidence", "line_scope", "text", "image_sha256",
               "settings_id", "source_page_url", "source_image_url")


def inspect_engine(config, executable=None):
    from PIL import __version__ as pillow_version
    candidate = Path(sys.executable).parent / ("tesseract.exe" if sys.platform == "win32" else "tesseract")
    binary = executable or (str(candidate) if candidate.exists() else shutil.which("tesseract"))
    if not binary:
        raise RuntimeError("Tesseract not found. Create the environment from fa26/environment.yml first.")
    response = subprocess.run([str(binary), "--version"], capture_output=True, text=True, check=True, timeout=15)
    version_text = (response.stdout + response.stderr).strip()
    match = re.search(r"\btesseract\s+(\d+\.\d+\.\d+)\b", version_text)
    expected = config["ocr"]
    if not match or match.group(1) != expected["engine_version"]:
        raise RuntimeError(f"Expected Tesseract {expected['engine_version']}; found: {version_text.splitlines()[0]}")
    if pillow_version != expected["pillow_version"]:
        raise RuntimeError(f"Expected Pillow {expected['pillow_version']}; found {pillow_version}")
    return {"binary": str(Path(binary).resolve()), "version": match.group(1),
            "version_text": version_text, "pillow_version": pillow_version}


def prepare_model(config, work_dir):
    settings = config["ocr"]
    folder = Path(work_dir) / "models/tessdata_best" / settings["english_revision"]
    path = folder / "eng.traineddata"
    if path.exists():
        if sha256_file(path) != settings["english_sha256"]:
            raise ValueError("Cached English weights failed SHA-256 validation: " + str(path))
    else:
        url = ("https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/"
               f"{settings['english_revision']}/eng.traineddata")
        download(url, path, expected_sha256=settings["english_sha256"])
    return folder


def preprocess(image_path, destination, settings):
    from PIL import Image, ImageOps
    with Image.open(image_path) as original:
        gray = original.convert("L")
    scaled = gray.resize((gray.width * settings["scale"], gray.height * settings["scale"]),
                         Image.Resampling.LANCZOS)
    prepared = ImageOps.expand(scaled, border=settings["border"], fill=255)
    try:
        prepared.save(destination, format="PNG")
    finally:
        gray.close()
        scaled.close()
        prepared.close()


def run_tesseract(binary, model_dir, prepared_path, output_base, settings, timeout, *, on_start=None):
    command = [str(binary), str(prepared_path), str(output_base), "--tessdata-dir", str(model_dir),
               "-l", settings["language"], "--oem", str(settings["oem"]), "--psm", str(settings["psm"]),
               "-c", "tessedit_create_txt=1", "-c", "tessedit_create_tsv=1", "-c", "tessedit_create_hocr=1"]
    # Output parameters avoid depending on distribution-specific configs/ files
    # inside the separately pinned English-weight directory.
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        if on_start:
            on_start(process.pid)
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException as error:
        if process.poll() is None:
            process.kill()
        stdout, stderr = process.communicate()
        if isinstance(error, subprocess.TimeoutExpired):
            error.output, error.stderr = stdout, stderr
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr), command


def parse_tsv(tsv_path, page, *, image_sha256, settings_id, config):
    """Keep native TSV reading order; map 2×/border coordinates to source JPEG."""
    settings, groups = config["ocr"], OrderedDict()
    text = Path(tsv_path).read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)
    required = {"level", "page_num", "block_num", "par_num", "line_num", "left", "top", "width", "height", "conf", "text"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("Tesseract TSV is missing required columns")
    for word in reader:
        if None in word or any(word.get(k) is None for k in required):
            raise ValueError("Malformed Tesseract TSV row")
        if word["level"] != "5" or not word["text"].strip():
            continue
        key = tuple(int(word[k]) for k in ("page_num", "block_num", "par_num", "line_num"))
        if key[0] != 1:
            raise ValueError("Expected one page in the Tesseract output")
        x, y, width, height = (int(word[k]) for k in ("left", "top", "width", "height"))
        confidence = float(word["conf"])
        if width <= 0 or height <= 0 or not math.isfinite(confidence):
            raise ValueError("Invalid Tesseract word geometry or confidence")
        group = groups.setdefault(key, {"tokens": [], "boxes": [], "confidences": []})
        group["tokens"].append(word["text"])
        group["boxes"].append((x, y, x + width, y + height))
        if confidence >= 0:
            group["confidences"].append(confidence)
    result = []
    for order, ((_, block, paragraph, line), group) in enumerate(groups.items(), 1):
        boxes = group["boxes"]
        processed = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                     max(b[2] for b in boxes), max(b[3] for b in boxes))
        limits = (page["expected_width"], page["expected_height"]) * 2
        box = [round(max(0, min(limit, (value - settings["border"]) / settings["scale"])), 3)
               for value, limit in zip(processed, limits)]
        line_scope = "unreviewed_directory_line" if page["ocr_role"] == "primary" else "supplementary_unreviewed"
        if page["leaf_num"] == config["scope"]["mixed_abbreviations_leaf"]:
            top, bottom = config["scope"]["mixed_page_body_y"]
            line_scope = "directory_body_candidate" if top <= box[1] < bottom else "reference_or_margin"
        confidences = group["confidences"]
        result.append({"volume_id": page["volume_id"], "page_id": page["page_id"],
                       "leaf_num": page["leaf_num"], "bookreader_index": page["bookreader_index"],
                       "printed_page": page["printed_page"], "section": page["section"],
                       "line_id": f"{page['page_id']}:{settings_id[:12]}:b{block:04d}-p{paragraph:04d}-l{line:04d}",
                       "reading_order": order, "block_num": block, "par_num": paragraph, "line_num": line,
                       **dict(zip(("x0", "y0", "x1", "y1"), box)), "word_count": len(group["tokens"]),
                       "mean_word_confidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
                       "line_scope": line_scope, "text": " ".join(group["tokens"]),
                       "image_sha256": image_sha256, "settings_id": settings_id,
                       "source_page_url": page["source_page_url"], "source_image_url": page["source_image_url"]})
    return result
