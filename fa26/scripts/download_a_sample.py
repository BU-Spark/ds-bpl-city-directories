#!/usr/bin/env python3
"""Download the first A-section scans and preserve their source mapping.

Companion to Katherine's api_look.ipynb. Uses only Python's standard library.
Run from any directory: python3 /path/to/fa26/scripts/download_a_sample.py
"""

import csv
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET


FA26 = Path(__file__).resolve().parents[1]
CONFIG = FA26 / "config" / "a_sample_selection.json"
OUTPUT = FA26 / "data" / "a_sample"


def download(url, destination):
    """Reuse complete local files; save new downloads atomically with a timeout."""
    if destination.exists() and destination.stat().st_size:
        print(f"Cached: {destination.name}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(
        url, headers={"User-Agent": "BU-Spark-BPL-sample/1.0"}
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                expected = response.headers.get("Content-Length")
                with partial.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
            if not partial.stat().st_size:
                raise OSError(f"Empty response: {url}")
            if expected and partial.stat().st_size != int(expected):
                raise OSError(f"Incomplete response: {url}")
            partial.replace(destination)
            print(f"Downloaded: {destination.name}")
            return
        except (OSError, urllib.error.URLError):
            partial.unlink(missing_ok=True)
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def image_body(canvas):
    # This item's retrieved manifest uses IIIF Presentation 3.
    for annotation_page in canvas["items"]:
        for annotation in annotation_page["items"]:
            body = annotation.get("body", {})
            if body.get("type") == "Image":
                return body
    raise ValueError(f"No page image on canvas {canvas['id']}")


def main():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    identifier = config["item_id"]
    source = OUTPUT / "source"
    source.mkdir(parents=True, exist_ok=True)
    metadata_url = f"https://archive.org/metadata/{identifier}"
    manifest_url = f"https://iiif.archive.org/iiif/{identifier}/manifest.json"
    download(metadata_url, source / "metadata.json")
    metadata = json.loads((source / "metadata.json").read_text())

    # Discover the filename through the same metadata API used by Katherine.
    scan_names = [f["name"] for f in metadata["files"]
                  if f["name"].endswith("_scandata.xml")]
    if len(scan_names) != 1:
        raise ValueError(f"Expected one scandata file; found {scan_names}")
    scandata_url = (f"https://archive.org/download/{identifier}/"
                    + urllib.parse.quote(scan_names[0]))
    download(scandata_url, source / "scandata.xml")
    download(manifest_url, source / "iiif_manifest.json")

    # Printed page numbers come from scandata, NOT the IIIF canvas label/index.
    scan_pages = {
        int(page.attrib["leafNum"]): page
        for page in ET.parse(source / "scandata.xml").findall(".//pageData/page")
    }
    manifest = json.loads((source / "iiif_manifest.json").read_text())
    if manifest.get("type") != "Manifest" or "items" not in manifest:
        raise ValueError("Expected an IIIF Presentation 3 manifest")

    wanted = [str(page) for page in config["download_printed_pages"]]
    matches = {}
    for index, canvas in enumerate(manifest["items"]):
        body = image_body(canvas)
        # The JP2 filename encodes the leaf number. Never assume a fixed offset.
        decoded_url = urllib.parse.unquote(body["id"])
        match = re.search(r"_(\d+)\.jp2(?:/|$)", decoded_url)
        if not match:
            continue
        leaf = int(match.group(1))
        scan = scan_pages.get(leaf)
        printed = scan.findtext("pageNumber", "") if scan is not None else ""
        if printed not in wanted:
            continue
        if printed in matches:
            raise ValueError(f"Ambiguous printed page {printed}")
        matches[printed] = (index, canvas, body, leaf)
    if set(matches) != set(wanted):
        raise ValueError(f"Missing printed pages: {set(wanted) - set(matches)}")

    rows = []
    for printed in wanted:
        index, canvas, body, leaf = matches[printed]
        filename = f"{identifier}_leaf{leaf:04d}_p{printed}.jpg"
        local = OUTPUT / "images" / filename
        download(body["id"], local)
        image_bytes = local.read_bytes()
        if not image_bytes.startswith(b"\xff\xd8\xff"):
            raise ValueError(f"Expected a JPEG scan: {local}")
        rows.append({
            "page_id": f"{identifier}_leaf{leaf:04d}",
            "item_id": identifier,
            "printed_page": printed,
            "leaf_num": leaf,
            "canvas_index_0based": index,
            "canvas_label": " | ".join(
                value for values in canvas.get("label", {}).values() for value in values
            ),
            "canvas_id": canvas["id"],
            "source_item_url": f"https://archive.org/details/{identifier}",
            "source_page_url": f"https://archive.org/details/{identifier}/page/{printed}/mode/1up",
            "metadata_url": metadata_url,
            "scandata_url": scandata_url,
            "manifest_url": manifest_url,
            "image_url": body["id"],
            "local_image": local.relative_to(OUTPUT).as_posix(),
            "width_px": canvas["width"],
            "height_px": canvas["height"],
            "sha256": hashlib.sha256(image_bytes).hexdigest(),
            "image_saved_at_utc": datetime.fromtimestamp(
                local.stat().st_mtime, tz=timezone.utc
            ).isoformat(),
            "role": "sample_and_abbreviation_key" if int(printed) == config["sample_printed_page"]
                    else "extension_context_only",
        })
    write_csv(OUTPUT / "pages.csv", rows)

    # This is a manually curated selection index, NOT automated OCR/extraction.
    # Labels help locate records; they are NOT gold-standard field transcriptions.
    page = next(row for row in rows
                if int(row["printed_page"]) == config["sample_printed_page"])
    selected = []
    for column in ("left", "right"):
        for position, entry in enumerate(config["people_by_column"][column], 1):
            selected.append({
                "sample_id": f"A{len(selected) + 1:03d}",
                "page_id": page["page_id"],
                "printed_page": page["printed_page"],
                "column": column,
                "person_order_in_column": position,
                "locator_label": entry["label"],
                "notice": entry.get("notice", ""),
                "source_page_url": page["source_page_url"],
                "local_image": page["local_image"],
                "validation_status": "selection_only_not_gold_transcription",
            })
    if len(selected) != config["expected_person_records"]:
        raise ValueError("Selection count differs from the configured count")
    write_csv(OUTPUT / "sample_index.csv", selected)
    print(f"\nSaved {len(rows)} scans and their page mappings to {OUTPUT}")
    print(f"Indexed {len(selected)} personal entries on printed page {page['printed_page']}.")
    print("Next: review the selection, then transcribe/parse the selected entries.")


if __name__ == "__main__":
    main()
