"""One real full-page run with immutable native outputs and explicit provenance.

Batch scheduling and cross-page entry extraction are later stages. This entry
point deliberately recognizes exactly one explicitly selected scanned leaf.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import uuid

from . import __version__
from .engine import LINE_FIELDS, inspect_engine, parse_tsv, prepare_model, preprocess, run_tesseract
from .io import download, identity, read_json, sha256_file, write_csv, write_json
from .manifest import load_manifest


def fetch_page(page, work_dir):
    """Cache a checked JPEG and its source receipt, independent of old experiments."""
    from PIL import Image
    folder = Path(work_dir) / "source" / page["volume_id"]
    image = folder / f"leaf{page['leaf_num']:04d}.jpg"
    receipt_path = image.with_suffix(".json")
    cached = image.exists() and receipt_path.exists()
    if cached:
        receipt = read_json(receipt_path)
        if receipt.get("source_image_url") != page["source_image_url"] or sha256_file(image) != receipt.get("sha256"):
            raise ValueError("Cached source image failed provenance validation: " + str(image))
    else:
        receipt = download(page["source_image_url"], image)
        receipt.update(source_image_url=page["source_image_url"], page_id=page["page_id"],
                       downloaded_at_utc=datetime.now(timezone.utc).isoformat())
    with Image.open(image) as source:
        size = list(source.size)
        source.verify()
    if size != [page["expected_width"], page["expected_height"]]:
        raise ValueError(f"Source dimensions differ from scandata: expected {page['expected_width']}×{page['expected_height']}, got {size}")
    receipt.update(width=size[0], height=size[1])
    write_json(receipt_path, receipt)
    return image, receipt, cached


def code_provenance():
    hashes = {p.name: sha256_file(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        head = commit.stdout.strip() if commit.returncode == 0 else None
        changed = bool(dirty.stdout.strip()) if dirty.returncode == 0 else None
    except OSError:
        head, changed = None, None
    return {"package_version": __version__, "code_sha256": hashes,
            "git_commit": head, "git_dirty": changed}


def recognize_page(manifest_path, leaf, work_dir, *, executable=None, timeout=300):
    if type(leaf) is not int or leaf < 0 or timeout <= 0:
        raise ValueError("Use a nonnegative scanned leaf and a positive timeout")
    wall_start = time.perf_counter()
    manifest = load_manifest(manifest_path)
    matches = [p for p in manifest["pages"] if p["leaf_num"] == leaf]
    if len(matches) != 1:
        raise ValueError("Scanned leaf is not present exactly once in the manifest")
    page, config = matches[0], manifest["config"]
    if not page["selected_for_ocr"]:
        raise ValueError("This leaf is outside the declared OCR scope: " + page["scope_reason"])
    info = inspect_engine(config, executable)
    timestamp = datetime.now(timezone.utc)
    run_id = timestamp.strftime("%Y%m%dT%H%M%S") + f"-leaf{leaf:04d}-" + uuid.uuid4().hex[:8]
    run_dir = Path(work_dir) / "runs" / config["volume_id"] / run_id
    raw = run_dir / "raw"
    raw.mkdir(parents=True, exist_ok=False)
    record = {"format": "bpl-page-run-v1", "run_id": run_id, "status": "running",
              "started_at_utc": timestamp.isoformat(), "manifest_id": manifest["manifest_id"],
              "config_id": identity(config), "page": page, "code": code_provenance(),
              "runtime": {"python": sys.version, "platform": platform.platform(), "machine": platform.machine(),
                          "cpu_count": os.cpu_count(), "omp_thread_limit": os.environ.get("OMP_THREAD_LIMIT"),
                          "tesseract_version_text": info["version_text"]}, "durations_s": {}}
    write_json(run_dir / "run.json", record)
    try:
        start = time.perf_counter()
        model_dir = prepare_model(config, work_dir)
        record["durations_s"]["model_prepare"] = time.perf_counter() - start
        record["settings"] = {**config["ocr"], "input": "full native-size processed-JP2 JPEG page",
                              "preprocessing": "grayscale, 2x Lanczos, 10 px white border; no extra thresholding or denoising",
                              "engine_build": info["version_text"], "code_sha256": record["code"]["code_sha256"]}
        record["settings_id"] = identity(record["settings"])
        start = time.perf_counter()
        image, receipt, cached = fetch_page(page, work_dir)
        record["durations_s"]["source_prepare"] = time.perf_counter() - start
        record["source"] = {**receipt, "cache_reused": cached,
                            "image_path_from_work_dir": image.relative_to(Path(work_dir)).as_posix()}
        with tempfile.TemporaryDirectory(prefix="bpl-page-") as temporary:
            prepared = Path(temporary) / "input.png"
            start = time.perf_counter()
            preprocess(image, prepared, config["ocr"])
            record["durations_s"]["preprocessing"] = time.perf_counter() - start
            record["prepared_image_sha256"] = sha256_file(prepared)
            start = time.perf_counter()
            response, command = run_tesseract(info["binary"], model_dir, prepared, raw / "page", config["ocr"], timeout)
            record["durations_s"]["engine"] = time.perf_counter() - start
            # Record arguments without user-specific absolute installation paths.
            record["command"] = ["tesseract", "<temporary/input.png>", "raw/page", "--tessdata-dir", "<pinned model directory>", *command[5:]]
            (raw / "stderr.txt").write_bytes(response.stderr)
            (raw / "stdout.txt").write_bytes(response.stdout)
            record["engine_returncode"] = response.returncode
            if response.returncode:
                raise RuntimeError("Tesseract failed: " + response.stderr.decode("utf-8", errors="replace")[-1500:])
        start = time.perf_counter()
        for suffix in ("txt", "tsv", "hocr"):
            if not (raw / f"page.{suffix}").exists():
                raise ValueError("Tesseract did not produce required output: " + suffix)
        lines = parse_tsv(raw / "page.tsv", page, image_sha256=receipt["sha256"],
                          settings_id=record["settings_id"], config=config)
        raw_text = (raw / "page.txt").read_text(encoding="utf-8")
        if bool(lines) != bool(raw_text.strip()):
            raise ValueError("TXT and TSV disagree about whether any text was recognized")
        write_csv(run_dir / "lines.csv", lines, LINE_FIELDS)
        record.update(status="completed" if lines else "empty", detected_lines=len(lines),
                      quality_status="unreviewed", reading_order="native TSV group order; not yet visually validated",
                      confidence_definition="Arithmetic mean of nonnegative word confidence values (0–100), not an accuracy estimate")
        record["durations_s"]["export"] = time.perf_counter() - start
        record["outputs"] = {str(p.relative_to(run_dir)): sha256_file(p) for p in sorted(run_dir.rglob("*"))
                             if p.is_file() and p.name != "run.json"}
    except BaseException as error:
        record.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                      error=type(error).__name__ + ": " + str(error))
        raise
    finally:
        record["durations_s"]["wall"] = time.perf_counter() - wall_start
        record["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(run_dir / "run.json", record)
    return run_dir, record
