"""Checked source caching with a bounded, explicitly recorded access fallback."""

from datetime import datetime, timezone
import http.client
import os
from pathlib import Path
import time
import urllib.error
from urllib.parse import urlencode

from PIL import Image

from .io import download, read_json, sha256_file, write_json


class SourceUnavailable(RuntimeError):
    def __init__(self, attempts):
        self.attempts = attempts
        super().__init__("All bounded source requests failed: " + attempts[-1]["error"])


def transient_source_error(error):
    if isinstance(error, urllib.error.HTTPError):
        return error.code in (408, 425, 429, 500, 502, 503, 504)
    return isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError,
                              http.client.IncompleteRead, http.client.RemoteDisconnected))


def bookreader_url(page, policy):
    # Address the exact archive member, never infer a leaf from a printed label.
    query = urlencode({"zip": policy["bookreader_zip"], "file": page["image_member"],
                       "id": page["ia_identifier"], "scale": 1, "rotate": 0})
    return policy["bookreader_base"] + "?" + query


def check_image(image, page):
    with Image.open(image) as source:
        size = list(source.size)
        source.verify()
    expected = [page["expected_width"], page["expected_height"]]
    if size != expected:
        raise ValueError(f"Source dimensions differ from scandata: expected {expected}, got {size}")
    return size


def fetch_page(page, work_dir, *, policy=None):
    folder = Path(work_dir) / "source" / page["volume_id"]
    image = folder / f"leaf{page['leaf_num']:04d}.jpg"
    receipt_path = image.with_suffix(".json")
    if image.exists() and receipt_path.exists():
        receipt = read_json(receipt_path)
        if (receipt.get("source_image_url") != page["source_image_url"] or
                receipt.get("page_id", page["page_id"]) != page["page_id"] or
                sha256_file(image) != receipt.get("sha256")):
            raise ValueError("Cached source image failed provenance validation: " + str(image))
        check_image(image, page)
        return image, receipt, True
    routes = [("iiif_native", page["source_image_url"], (policy or {}).get("iiif_timeout_s", 60))]
    if policy:
        routes.extend(("bookreader_exact_member", bookreader_url(page, policy), policy["bookreader_timeout_s"])
                      for _ in range(policy["bookreader_attempts"]))
    candidate = image.with_suffix(".candidate.jpg")
    attempts = []
    try:
        for method, url, timeout in routes:
            if attempts:
                time.sleep(policy["backoff_s"])
            start = time.perf_counter()
            entry = {"method": method, "url": url, "timeout_s": timeout}
            try:
                receipt = download(url, candidate, timeout=timeout)
                size = check_image(candidate, page)
            except Exception as error:
                entry.update(status="failed", elapsed_s=time.perf_counter() - start,
                             error=type(error).__name__ + ": " + str(error))
                attempts.append(entry)
                if not transient_source_error(error):
                    error.source_attempts = attempts
                    raise
                continue
            entry.update(status="completed", elapsed_s=time.perf_counter() - start)
            attempts.append(entry)
            receipt.update(source_image_url=page["source_image_url"], page_id=page["page_id"],
                           downloaded_at_utc=datetime.now(timezone.utc).isoformat(),
                           width=size[0], height=size[1], retrieval_method=method, acquisition_attempts=attempts)
            if method != "iiif_native":
                receipt.update(retrieval_url=url, rendering_note="Official exact JP2 member rendered at scale=1, rotate=0; byte/pixel equality with IIIF is not assumed")
            os.replace(candidate, image)
            write_json(receipt_path, receipt)
            return image, receipt, False
        raise SourceUnavailable(attempts)
    finally:
        candidate.unlink(missing_ok=True)
