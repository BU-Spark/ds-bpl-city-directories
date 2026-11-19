"""Small, atomic file and HTTP helpers shared by manifest preparation and OCR."""

import csv
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.request

USER_AGENT = "BPL-Directory-OCR/0.1 (BU Spark academic directory research)"


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def identity(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_json(path, value):
    atomic_bytes(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def write_csv(path, rows, fields):
    import io
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    atomic_bytes(path, handle.getvalue().encode("utf-8-sig"))


def download(url, destination, *, expected_sha256=None, expected_md5=None, max_bytes=30_000_000):
    """Download to a temporary file; publish only a complete, checked response."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=destination.name + ".", suffix=".part", dir=destination.parent)
    digest = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    size = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with os.fdopen(descriptor, "wb") as handle, urllib.request.urlopen(request, timeout=60) as response:
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > max_bytes:
                raise ValueError("Download exceeds the documented size limit: " + url)
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("Download exceeds the documented size limit: " + url)
                digest.update(chunk)
                md5.update(chunk)
                handle.write(chunk)
            if declared and size != int(declared):
                raise ValueError("Incomplete HTTP response: " + url)
            handle.flush()
            os.fsync(handle.fileno())
        if expected_sha256 and digest.hexdigest() != expected_sha256:
            raise ValueError("SHA-256 mismatch: " + url)
        if expected_md5 and md5.hexdigest() != expected_md5:
            raise ValueError("IA file MD5 mismatch: " + url)
        os.replace(temporary, destination)
        return {"sha256": digest.hexdigest(), "bytes": size}
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_config(path):
    config = read_json(path)
    if config.get("format") != "bpl-volume-config-v1":
        raise ValueError("Unsupported volume configuration")
    for key in ("volume_id", "ia_identifier", "scandata_file", "page_numbers_file", "image_archive", "image_prefix"):
        value = config.get(key)
        if not isinstance(value, str) or not value or any(c in value for c in ("/", "\\", "..")):
            raise ValueError("Invalid source identifier: " + key)
    ocr = config["ocr"]
    expected = {"engine_version": "5.3.4", "language": "eng", "oem": 1, "psm": 3,
                "scale": 2, "border": 10, "pillow_version": "11.3.0"}
    if any(ocr.get(k) != v for k, v in expected.items()):
        raise ValueError("This release implements only the selected full-page baseline; use a separate reviewed configuration for changes")
    if not re.fullmatch(r"[a-f0-9]{40}", ocr.get("english_revision", "")) or not re.fullmatch(r"[a-f0-9]{64}", ocr.get("english_sha256", "")):
        raise ValueError("English weights require an immutable revision and SHA-256")
    return config
