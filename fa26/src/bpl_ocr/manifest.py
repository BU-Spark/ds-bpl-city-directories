"""Map every scanned leaf to source metadata and an explicit OCR scope."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

from .io import download, identity, load_config, read_json, sha256_file, write_csv, write_json

FORMAT = "bpl-volume-manifest-v1"
FIELDS = ("volume_id", "ia_identifier", "page_id", "leaf_num", "bookreader_index", "printed_page",
          "scandata_page_label", "inferred_page_label", "page_label_source", "page_type",
          "access_available", "section", "ocr_role", "selected_for_ocr", "scope_reason",
          "expected_width", "expected_height", "image_member", "source_page_url", "source_image_url")


def image_url(config, leaf, width):
    item, prefix = config["ia_identifier"], config["image_prefix"]
    member = f"{prefix}_jp2/{prefix}_{leaf:04d}.jp2"
    identifier = f"{item}%2F{config['image_archive']}%2F" + member.replace("/", "%2F")
    return member, f"https://iiif.archive.org/image/iiif/3/{identifier}/full/{width},/0/default.jpg"


def classify(config, leaf, page_type, available):
    scope = config["scope"]
    if not available:
        return "non_access_scan", "excluded", "Excluded by IA addToAccessFormats=false (deleted scan or calibration card)."
    if leaf in scope["excluded_advertisement_leaves"]:
        return "inserted_advertisement", "excluded", "Visually verified Cat's Paw advertisement, not directory entries."
    if leaf in scope["supplementary_leaves"]:
        return "late_additions_and_removals", "supplementary", "Visually verified printed p160; retain separately for later entry reconciliation."
    first, last = scope["general_directory_leaf_range"]
    if first <= leaf <= last:
        section = "abbreviations_and_general_directory" if leaf == scope["mixed_abbreviations_leaf"] else "general_directory"
        return section, "primary", "Within visually verified general-directory boundaries; inserted ads excluded separately."
    if page_type == "Cover":
        return "cover", "excluded", "Book cover, not directory entries."
    if leaf > last:
        return "end_matter", "excluded", "Blank/endpaper material after the final directory page."
    return "front_matter_street_directory_and_city_record", "excluded", "Before p160/p161; reference sections, not the target general directory."


def build_pages(config, scandata_path, page_numbers):
    elements = ET.parse(scandata_path).getroot().findall("./pageData/page")
    if not elements:
        raise ValueError("No pages in IA scandata")
    inferred = {p["leafNum"]: p.get("pageNumber") or "" for p in page_numbers["pages"]}
    pages, seen, access_index = [], set(), 0
    for element in elements:
        leaf = int(element.attrib["leafNum"])
        if leaf in seen:
            raise ValueError("Duplicate scanned leaf in source metadata")
        seen.add(leaf)
        available = element.findtext("addToAccessFormats") == "true"
        raw_label = element.findtext("pageNumber") or ""
        override = config["scope"].get("label_overrides", {}).get(str(leaf))
        printed = override["printed_page"] if override else raw_label
        page_type = element.findtext("pageType") or "unknown"
        width, height = (int(element.findtext("cropBox/" + name)) for name in ("w", "h"))
        member, url = image_url(config, leaf, width)
        section, role, reason = classify(config, leaf, page_type, available)
        page_index = access_index if available else None
        # n-indices count access pages, not scanned leaves or printed numbers.
        book_url = f"https://archive.org/details/{config['ia_identifier']}"
        if available:
            book_url += f"/page/n{page_index}/mode/1up"
            access_index += 1
        pages.append({"volume_id": config["volume_id"], "ia_identifier": config["ia_identifier"],
                      "page_id": f"{config['volume_id']}-leaf{leaf:04d}",
                      "leaf_num": leaf, "bookreader_index": page_index, "printed_page": printed,
                      "scandata_page_label": raw_label, "inferred_page_label": inferred.get(leaf, ""),
                      "page_label_source": "visual_override" if override else ("scandata" if raw_label else "unlabelled"),
                      "page_type": page_type, "access_available": available, "section": section,
                      "ocr_role": role, "selected_for_ocr": role != "excluded", "scope_reason": reason,
                      "expected_width": width, "expected_height": height,
                      "image_member": member, "source_page_url": book_url, "source_image_url": url})
    if [p["leaf_num"] for p in pages] != sorted(seen):
        raise ValueError("Scandata leaves must be in scan order")
    return pages


def source_issues(pages):
    issues, previous = [], None
    for page in pages:
        raw = page["scandata_page_label"]
        if raw.isdecimal():
            current = int(raw)
            if previous and current != previous[1] + 1:
                issues.append({"type": "scandata_label_gap", "before_leaf": previous[0],
                               "after_leaf": page["leaf_num"], "before_label": previous[1],
                               "after_label": current,
                               "meaning": "A metadata pagination discontinuity; not automatically proof of missing physical pages."})
            previous = (page["leaf_num"], current)
        if page["inferred_page_label"] != raw:
            issues.append({"type": "page_label_sources_disagree", "leaf_num": page["leaf_num"],
                           "scandata": raw, "page_numbers_json": page["inferred_page_label"],
                           "resolution": "Keep both; use scandata unless a documented visual override exists."})
        if page["page_label_source"] == "visual_override":
            issues.append({"type": "visual_label_override", "leaf_num": page["leaf_num"],
                           "scandata": raw, "printed_page": page["printed_page"]})
    return issues


def prepare_manifest(config_path, destination, *, refresh=False, offline=False):
    """Fetch small source snapshots if needed; never download the image archive."""
    config, destination = load_config(config_path), Path(destination)
    snapshot = destination / "source"
    snapshot.mkdir(parents=True, exist_ok=True)
    item = config["ia_identifier"]
    metadata_path = snapshot / "metadata.json"
    if offline and refresh:
        raise ValueError("--offline and --refresh are mutually exclusive")
    sources = [(f"https://archive.org/metadata/{item}", metadata_path, None)]
    if refresh or not metadata_path.exists():
        if offline:
            raise FileNotFoundError("Offline mode requires the checked-in source snapshots")
        download(sources[0][0], metadata_path)
    metadata = read_json(metadata_path)
    if metadata.get("metadata", {}).get("identifier") != item:
        raise ValueError("IA metadata belongs to a different volume")
    files = {f["name"]: f for f in metadata["files"]}
    if config["image_archive"] not in files:
        raise ValueError("Configured image archive is absent from IA metadata")
    for name in (config["scandata_file"], config["page_numbers_file"]):
        if name not in files:
            raise ValueError("Required IA metadata file not found: " + name)
        url, path = f"https://archive.org/download/{item}/{name}", snapshot / name
        sources.append((url, path, files[name].get("md5")))
        if refresh or not path.exists():
            if offline:
                raise FileNotFoundError("Offline mode requires " + str(path))
            download(url, path, expected_md5=files[name].get("md5"))
        if files[name].get("md5") and hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest() != files[name]["md5"]:
            raise ValueError("Cached source snapshot fails IA MD5 validation: " + name)
    page_numbers = read_json(snapshot / config["page_numbers_file"])
    if page_numbers.get("identifier") != item:
        raise ValueError("Page-number metadata belongs to a different volume")
    pages = build_pages(config, snapshot / config["scandata_file"], page_numbers)
    source_files = [{"file": str(path.relative_to(destination)), "url": url,
                     "sha256": sha256_file(path), "ia_md5": md5} for url, path, md5 in sources]
    payload = {"format": FORMAT, "config": config, "source_files": source_files,
               "image_archive": {k: files[config["image_archive"]].get(k) for k in ("name", "size", "md5")},
               "pages": pages}
    manifest = {**payload, "manifest_id": identity(payload)}
    write_json(destination / "manifest.json", manifest)
    write_csv(destination / "pages.csv", pages, FIELDS)
    primary = [p for p in pages if p["ocr_role"] == "primary"]
    labels = {int(p["printed_page"]) for p in primary if p["printed_page"].isdecimal()}
    missing_labels = sorted(set(range(min(labels), max(labels) + 1)) - labels) if labels else []
    report = {"format": FORMAT, "manifest_id": manifest["manifest_id"],
              "generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "scanned_leaves": len(pages), "access_pages": sum(p["access_available"] for p in pages),
              "ocr_roles": dict(Counter(p["ocr_role"] for p in pages)),
              "sections": dict(Counter(p["section"] for p in pages)),
              "primary_printed_page_range": [min(labels), max(labels)] if labels else [],
              "absent_primary_printed_labels": missing_labels, "issues": source_issues(pages),
              "scope_note": config["scope"]["review_notes"],
              "ocr_completion": "No OCR completion is implied by source-manifest inclusion."}
    write_json(destination / "scope_report.json", report)
    return report


def load_manifest(path):
    manifest = read_json(path)
    payload = {k: v for k, v in manifest.items() if k != "manifest_id"}
    if manifest.get("format") != FORMAT or identity(payload) != manifest.get("manifest_id"):
        raise ValueError("Manifest changed without a valid identity; rebuild it from source snapshots")
    return manifest
