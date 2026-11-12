#!/usr/bin/env python3
"""Rule-based, sample-assisted extraction from the existing page-161 OCR.

No model API is called. The selection list locates candidates but NEVER supplies
missing extracted field values. Image checks are read only after extraction.
"""

import csv
import difflib
import hashlib
import json
import re
from pathlib import Path
from statistics import median

from download_a_sample import OUTPUT, download


# Page-specific layout, checked against the unchanged page-161 scan.
# These settings must be revisited for a different page layout.
LAYOUT = {"top": 1645, "bottom": 2680, "split_x": 760, "line_tolerance": 10,
          "entry_x_max": {"left": 135, "right": 845}}
NEIGHBORHOODS = {
    "E B": "East Boston", "S B": "South Boston", "W R": "West Roxbury",
    "J P": "Jamaica Plain", "H P": "Hyde Park", "Dor": "Dorchester",
    "Rox": "Roxbury", "Alls": "Allston", "Br": "Brighton",
    "Chsn": "Charlestown", "Ros": "Roslindale", "Mat": "Mattapan",
}
ADDRESS_WORDS = {
    "Wash": "Washington", "B'way": "Broadway", "av": "Avenue",
    "rd": "Road", "pl": "Place", "rm": "Room", "sq": "Square",
    "E": "East", "W": "West", "N": "North", "S": "South",
    "Camb": "Cambridge", "B'line": "Brookline",
}
OCCUPATIONS = {
    "asst sec": "assistant secretary", "com trav": "commercial traveler",
    "tel opr": "telegraph operator", "vice pres": "vice president",
    "law student": "law student", "shoe repairer": "shoe repairer",
    "real estate": "", "cigars": "", "liquors": "",
    "tailor": "tailor", "jeweler": "jeweler", "salesman": "salesman",
    "lawyer": "lawyer", "mgr": "manager", "driver": "driver",
    "porter": "porter", "cigarmaker": "cigar maker", "laborer": "laborer",
    "clerk": "clerk", "shoecutter": "shoe cutter", "baker": "baker",
    "candymaker": "candy maker", "hostler": "hostler", "barber": "barber",
    "blacksmith": "blacksmith", "teamster": "teamster", "physician": "physician",
    "buyer": "buyer", "mason": "mason",
}
FIELDS = [
    "surname", "given_name", "name_qualifier", "occupation_raw", "occupation_normalized",
    "affiliation_raw", "work_address_raw", "work_address_normalized",
    "residence_type_raw", "residence_type_normalized", "residence_address_raw",
    "residence_address_normalized", "neighborhood_raw", "neighborhood_normalized",
    "record_status", "status_detail_raw",
]


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def text_key(value):
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def join_lines(parts):
    """Join line-wrap hyphenation in the working text, leaving raw OCR intact."""
    text = ""
    for part in parts:
        if not part:
            continue
        text = text[:-1] + part if text.endswith("-") else (text + " " + part).strip()
    return re.sub(r"\s+", " ", text).strip()


def reconstruct_lines(annotations):
    words = []
    for annotation in annotations["items"]:
        target = annotation.get("target", "")
        if "#xywh=" not in target:
            continue
        x, y, width, height = map(int, target.split("#xywh=")[1].split(","))
        if not LAYOUT["top"] <= y < LAYOUT["bottom"]:
            continue
        words.append({"x": x, "y": y, "w": width, "h": height,
                      "cy": y + height / 2,
                      "text": annotation["body"]["value"].strip(),
                      "annotation_id": annotation["id"]})
    result = []
    for column in ("left", "right"):
        subset = [word for word in words
                  if (word["x"] < LAYOUT["split_x"]) == (column == "left")]
        bands = []
        for word in sorted(subset, key=lambda value: (value["cy"], value["x"])):
            if bands and abs(word["cy"] - median(w["cy"] for w in bands[-1])) < LAYOUT["line_tolerance"]:
                bands[-1].append(word)
            else:
                bands.append([word])
        for number, band in enumerate(bands, 1):
            x, y = min(w["x"] for w in band), min(w["y"] for w in band)
            right = max(w["x"] + w["w"] for w in band)
            bottom = max(w["y"] + w["h"] for w in band)
            result.append({"line_id": f"{column[0].upper()}{number:03d}",
                           "column": column, "x": x, "y": y,
                           "bbox": f"{x},{y},{right-x},{bottom-y}",
                           "text": " ".join(w["text"] for w in sorted(band, key=lambda w: w["x"])),
                           "annotation_ids": [w["annotation_id"] for w in band]})
    return result


def split_overflow(text, allow_open_paren=True):
    """A trailing unmatched bracket is a candidate continuation of the next entry.

    Boston's raised continuation brackets are sometimes OCRed as '('. All such
    repairs stay flagged; balanced business-affiliation parentheses are retained.
    """
    match = re.search(r"\[([^\]]+)$", text)
    if not match and allow_open_paren and text.count("(") > text.count(")"):
        match = re.search(r"\(([^)]+)$", text)
    return (text[:match.start()].strip(), match.group(1).strip()) if match else (text, "")


def segment_entries(lines):
    entries = []
    for column in ("left", "right"):
        groups = []
        for line in [line for line in lines if line["column"] == column]:
            if not groups or line["x"] <= LAYOUT["entry_x_max"][column]:
                groups.append([])
            groups[-1].append(line)
        pending = ""
        pending_line_ids = []
        for group in groups:
            inherited_overflow, pending = pending, ""
            inherited_line_ids, pending_line_ids = pending_line_ids, []
            working = []
            complete = " ".join(line["text"] for line in group)
            allow_open_paren = complete.count("(") > complete.count(")")
            for line in group:
                main_text, overflow = split_overflow(line["text"], allow_open_paren)
                working.append(main_text)
                if overflow:
                    pending = join_lines([pending, overflow])
                    pending_line_ids.append(line["line_id"])
            if inherited_overflow:
                working.append(inherited_overflow)
            entries.append({"column": column, "lines": group,
                            "source_line_ids": list(dict.fromkeys(
                                inherited_line_ids + [line["line_id"] for line in group])),
                            "raw_ocr_text": "\n".join(line["text"] for line in group),
                            "working_text": join_lines(working),
                            "overflow_received": inherited_overflow,
                            "overflow_passed_forward": pending})
    return entries


def split_name(text, previous_surname):
    had_ditto = bool(re.match(r'^[^A-Za-z0-9]', text))
    clean = re.sub(r'^[^A-Za-z0-9]+', '', text).strip()
    surname, rest = previous_surname, clean
    explicit = re.match(r"^(A[a-z]+)\s+", clean)
    if explicit and not had_ditto:
        surname, rest = explicit.group(1), clean[explicit.end():]
    tokens = rest.split()
    name, qualifier = [], ""
    while tokens and re.fullmatch(r"[A-Z][A-Za-z'.-]*", tokens[0]):
        token = tokens.pop(0)
        if token in {"Mrs", "Miss", "Mr"}:
            qualifier = token
            break
        name.append(token)
    return surname, " ".join(name), qualifier, " ".join(tokens)


def neighborhood_suffix(address):
    for code, expanded in NEIGHBORHOODS.items():
        match = re.search(r"(?:^|\s)" + re.escape(code) + r"[.,]?$", address)
        if match:
            return address[:match.start()].strip(), code, expanded
    return address, "", ""


def normalize_address(address):
    base, _, neighborhood = neighborhood_suffix(address.strip())
    base = re.sub(r"^at\s+", "", base)
    for word, expanded in sorted(ADDRESS_WORDS.items(), key=lambda item: -len(item[0])):
        base = re.sub(r"(?<!\w)" + re.escape(word) + r"(?!\w)", expanded, base)
    return ", ".join(part for part in (base, neighborhood) if part)


def parse_fields(entry, previous_surname):
    result = dict.fromkeys(FIELDS, "")
    flags = []
    surname, given, qualifier, body = split_name(entry["working_text"], previous_surname)
    result.update(surname=surname, given_name=given, name_qualifier=qualifier,
                  record_status="listed")
    if not surname:
        flags.append("surname_context_missing")
    if entry["overflow_received"] or entry["overflow_passed_forward"]:
        flags.append("bracket_continuation_rule")
    status = re.search(r"\b(died|rem to)\s+(.*)$", body)
    if status:
        result["record_status"] = "deceased" if status.group(1) == "died" else "removed"
        result["status_detail_raw"] = status.group(2)
        flags.append("historical_status_notice")
        return result, flags

    residence = re.search(r"\b(house|h|bds|b|rms)(?:\s+|$)", body)
    before = body[:residence.start()].strip() if residence else body
    if residence:
        result["residence_type_raw"] = residence.group(1)
        result["residence_type_normalized"] = {
            "h": "house", "house": "house", "b": "boards", "bds": "boards", "rms": "rooms",
        }[residence.group(1)]
        result["residence_address_raw"] = body[residence.end():].strip()
    affiliations = re.findall(r"\(([^)]+)\)", before)
    result["affiliation_raw"] = "; ".join(affiliations)
    before = re.sub(r"\([^)]*\)", "", before).strip()
    for occupation in sorted(OCCUPATIONS, key=len, reverse=True):
        if re.match(re.escape(occupation) + r"(?:\s|$)", before):
            result["occupation_raw"] = occupation
            result["occupation_normalized"] = OCCUPATIONS[occupation]
            before = before[len(occupation):].strip()
            if not OCCUPATIONS[occupation]:
                flags.append("occupation_activity_not_specific_role")
            break
    address_start = re.search(r"\b\d+[a-zA-Z]?\b", before)
    if address_start:
        result["work_address_raw"] = before[address_start.start():].strip()
        residual = before[:address_start.start()].strip()
    else:
        residual = before
    if residual:
        result["affiliation_raw"] = "; ".join(filter(None, [result["affiliation_raw"], residual]))
        flags.append("unclassified_pre_address_text")
    result["work_address_normalized"] = normalize_address(result["work_address_raw"])
    raw_residence = result["residence_address_raw"]
    resolved = raw_residence
    if raw_residence == "do":
        resolved = result["work_address_raw"]
        flags.append("ditto_entire_address" if resolved else "unresolved_address_ditto")
    elif re.search(r"\bdo$", raw_residence):
        _, work_code, _ = neighborhood_suffix(result["work_address_raw"])
        if work_code:
            resolved = re.sub(r"\bdo$", work_code, raw_residence)
            flags.append("ditto_neighborhood")
        else:
            flags.append("unresolved_neighborhood_ditto")
            resolved = ""
    result["residence_address_normalized"] = normalize_address(resolved)
    _, original_code, _ = neighborhood_suffix(raw_residence)
    _, _, expanded = neighborhood_suffix(resolved)
    result["neighborhood_raw"] = original_code or (
        "do" if raw_residence != "do" and re.search(r"\bdo$", raw_residence) else ""
    )
    result["neighborhood_normalized"] = expanded
    if not residence or not raw_residence:
        flags.append("residence_not_recovered")
    elif raw_residence.startswith("at "):
        flags.append("locality_only_residence")
    return result, flags


def locate_samples(candidates, selection):
    """Match candidates to the preselected sample, without copying expected names.

    Name matching is selection assistance, not a blind entry-detection benchmark.
    A poor/absent match remains missing; each OCR candidate is used at most once.
    """
    used = set()
    result = []
    expected_full_names = {
        text_key(re.sub(r"\s+(Mrs|Miss|Mr)$", "",
                        re.sub(r"\s*\([^)]*\)", "", sample["locator_label"])))
        for sample in selection
    }
    for sample in selection:
        label = re.sub(r"\s*\([^)]*\)", "", sample["locator_label"])
        expected_surname, expected_given = label.split(" ", 1)
        expected_given = re.sub(r"\s+(Mrs|Miss|Mr)$", "", expected_given)
        choices = []
        for index, candidate in enumerate(candidates):
            if index in used or candidate["column"] != sample["column"]:
                continue
            parsed = candidate["fields"]
            candidate_full = text_key(parsed["surname"] + " " + parsed["given_name"])
            expected_full = text_key(expected_surname + " " + expected_given)
            if candidate_full in expected_full_names and candidate_full != expected_full:
                continue  # Reserve exact matches for their own selected person.
            ratio = difflib.SequenceMatcher(None, text_key(expected_given),
                                           text_key(parsed["given_name"])).ratio()
            if ratio < 0.75:
                continue
            surname_bonus = 0.10 if parsed["surname"] == expected_surname else 0
            qualifier = re.search(r"\(([^)]+)\)", sample["locator_label"])
            if qualifier and qualifier.group(1) not in candidate["working_text"]:
                continue
            choices.append((ratio + surname_bonus, index))
        if not choices:
            result.append((sample, None, ["selected_entry_not_found_in_ocr"]))
            continue
        choices.sort(reverse=True)
        score, index = choices[0]
        # Never select arbitrarily between equally plausible candidates.
        if len(choices) > 1 and abs(score - choices[1][0]) < 0.02:
            result.append((sample, None, ["ambiguous_sample_match"]))
            continue
        used.add(index)
        candidate = candidates[index]
        flags = list(candidate["flags"])
        if candidate["fields"]["surname"] != expected_surname:
            flags.append("surname_disagrees_with_selection")
        if text_key(candidate["fields"]["given_name"]) != text_key(expected_given):
            flags.append("fuzzy_name_match")
        result.append((sample, candidate, flags))
    return result


def run_checks(records, check_path):
    if not check_path.exists():
        return [], {}
    checks = json.loads(check_path.read_text(encoding="utf-8"))
    lookup = {record["sample_id"]: record for record in records}
    rows, by_sample = [], {}
    for check in checks["entries"]:
        record = lookup[check["sample_id"]]
        differences = []
        expected_fields = {**checks.get("expected_defaults", {}), **check["expected"]}
        for field, expected in expected_fields.items():
            actual = record[field]
            same = " ".join(actual.split()) == " ".join(expected.split())
            if not same:
                differences.append(field)
            rows.append({"sample_id": check["sample_id"], "field": field,
                         "expected_from_image": expected, "baseline_value": actual,
                         "agreement": "yes" if same else "no",
                         "reviewer": checks["reviewer"],
                         "review_scope": checks["review_scope"],
                         "source_page_url": record["source_page_url"]})
        by_sample[check["sample_id"]] = {"differences": differences, "note": check["note"]}
    return rows, by_sample


def main():
    pages = read_csv(OUTPUT / "pages.csv")
    selection = read_csv(OUTPUT / "sample_index.csv")
    if len({sample["page_id"] for sample in selection}) != 1:
        raise ValueError("This pilot currently supports one selected page")
    page = next(page for page in pages if page["page_id"] == selection[0]["page_id"])
    manifest = json.loads((OUTPUT / "source/iiif_manifest.json").read_text())
    canvas = next(canvas for canvas in manifest["items"] if canvas["id"] == page["canvas_id"])
    ocr_url = canvas["annotations"][0]["id"]
    ocr_path = OUTPUT / "source" / f"p{page['printed_page']}_ocr.json"
    download(ocr_url, ocr_path)
    annotations = json.loads(ocr_path.read_text())
    if annotations["id"] != ocr_url or any(
        not item["target"].startswith(page["canvas_id"] + "#xywh=")
        for item in annotations["items"]
    ):
        raise ValueError("OCR annotations do not match the selected source canvas")
    lines = reconstruct_lines(annotations)
    candidates = segment_entries(lines)
    previous = {"left": "", "right": ""}
    for candidate in candidates:
        fields, flags = parse_fields(candidate, previous[candidate["column"]])
        previous[candidate["column"]] = fields["surname"]
        candidate.update(fields=fields, flags=flags)

    records = []
    for sample, candidate, flags in locate_samples(candidates, selection):
        fields = candidate["fields"] if candidate else dict.fromkeys(FIELDS, "")
        record = {
            "sample_id": sample["sample_id"], "selection_label": sample["locator_label"],
            "page_id": sample["page_id"], "printed_page": page["printed_page"],
            "column": sample["column"],
            "extraction_status": "candidate" if candidate else "not_recovered",
            "raw_ocr_text": candidate["raw_ocr_text"] if candidate else "",
            "working_text": candidate["working_text"] if candidate else "",
            **fields,
            "field_verification": "unverified_rule_output",
            "review_flags": "; ".join(sorted(set(flags))),
            "source_line_ids": ";".join(candidate["source_line_ids"]) if candidate else "",
            "source_page_url": page["source_page_url"],
            "canvas_id": page["canvas_id"], "local_image": page["local_image"],
            "ocr_source_url": ocr_url,
        }
        records.append(record)
    check_rows, checked = run_checks(records, OUTPUT / "review/image_checks.json")
    for record in records:
        check = checked.get(record["sample_id"])
        record["image_check_status"] = (
            "assistant_checked_mismatch" if check and check["differences"] else
            "assistant_checked_agreement" if check else "not_checked"
        )
        record["image_check_differences"] = "; ".join(check["differences"]) if check else ""
        # Checks describe disagreements; they never overwrite baseline fields.
    issues = []
    for record in records:
        reasons = list(filter(None, record["review_flags"].split("; ")))
        if record["image_check_differences"]:
            reasons.append("image_check_mismatch: " + record["image_check_differences"])
        if reasons:
            issues.append({"sample_id": record["sample_id"], "selection_label": record["selection_label"],
                           "issues": "; ".join(reasons), "status": "open",
                           "image_check_note": checked.get(record["sample_id"], {}).get("note", ""),
                           "source_page_url": record["source_page_url"]})
    destination = OUTPUT / "extraction"
    write_csv(destination / "records.csv", records)
    write_csv(destination / "issues.csv", issues,
              ["sample_id", "selection_label", "issues", "status", "image_check_note", "source_page_url"])
    write_csv(destination / "check_results.csv", check_rows,
              ["sample_id", "field", "expected_from_image", "baseline_value", "agreement",
               "reviewer", "review_scope", "source_page_url"])
    # Readable derived OCR lines, with IDs that records.csv uses for provenance.
    (destination / "ocr_lines.txt").write_text(
        "\n".join(f"{line['line_id']} [{line['bbox']}] {line['text']}" for line in lines) + "\n",
        encoding="utf-8",
    )
    recovered = sum(record["extraction_status"] == "candidate" for record in records)
    check_agreement = sum(not value["differences"] for value in checked.values())
    report = [
        "# Page 161 extraction pilot", "",
        f"- Selected personal entries: **{len(records)}**.",
        f"- Entries matched to existing OCR candidates: **{recovered}**.",
        f"- Selected entries not recovered: **{len(records)-recovered}**.",
        f"- Records with review flags / observed disagreements: **{len(issues)}**.",
        f"- Assistant image checks: **{len(checked)}** records; **{check_agreement}** agree on all checked fields.",
        "- Team/human-verified gold-standard records: **0** in this workflow.", "",
        "## What was run", "",
        "Existing Internet Archive word OCR → spatial line ordering → indentation-based entry grouping → "
        "bracket-continuation handling → surname context and regex field parsing → selected-record matching.", "",
        "The known 53-name list is used only to select/match OCR candidates. Its names and status notes "
        "are never substituted for missing extracted fields. This is a sample-assisted development baseline, "
        "not a blind evaluation of finding every person on an unseen page.", "",
        "Raw OCR JSON remains unchanged. `raw_ocr_text` preserves the reconstructed physical lines, "
        "including OCR mistakes. `working_text` joins wrapping and moves candidate raised-bracket continuations "
        "to the following entry. Both versions are retained; `source_line_ids` also includes any preceding "
        "physical line supplying a raised continuation. No paid model API or geocoder was called.", "",
        "The current layout settings, abbreviation rules and surname handling are specific to this "
        "A-section pilot. Field confidence scores and geocoding have not been implemented.", "",
        "## Image-check results", "",
        "These are assistant-produced development spot checks selected to include difficult cases. "
        "They are not independent human gold labels, a held-out test, or population accuracy. "
        "The parser does not read expected values until its output is complete. Exact agreement ignores "
        "whitespace only; correctness of a blank field is checked explicitly when included.", "",
        "| Field | Agreement / checked |", "|---|---:|",
    ]
    for field in dict.fromkeys(row["field"] for row in check_rows):
        values = [row for row in check_rows if row["field"] == field]
        report.append(f"| {field} | {sum(row['agreement']=='yes' for row in values)} / {len(values)} |")
    report += ["", "## Main issues to discuss", "",
               "- Missing surname anchors can propagate the wrong surname through ditto entries.",
               "- Entire entries and address continuations are missing from the existing OCR.",
               "- Raised-bracket text may physically sit beside the preceding record.",
               "- `do` can repeat a full work address or only the work-address neighborhood.",
               "- Death/removal notices remain records; they are not counted as confirmed current residents.",
               "- Commodity/activity words such as `cigars` do not establish a specific occupation.",
               "", "## Decisions for the client", "",
               "1. Confirm the representation and analytical treatment of death/removal notices.",
               "2. Confirm how to retain activity-only occupation descriptions without inventing a role.",
               "3. Review the raw/normalized schema and treatment of locality-only residences.",
               "", "## Reproduce and inspect", "",
               "Run `python3 fa26/scripts/extract_a_sample.py` or the step-2 notebook. "
               "See `../README.md` for fields and limitations. `records.csv` is generated; "
               "review notes live in `../review/image_checks.json`, outside the generated output folder.",
               "", f"OCR input: {ocr_url}",
               f"OCR SHA-256: `{hashlib.sha256(ocr_path.read_bytes()).hexdigest()}`", ""]
    (destination / "report.md").write_text("\n".join(report), encoding="utf-8")
    print(f"Matched {recovered}/{len(records)} selected records to OCR candidates.")
    print(f"Image-checked {len(checked)} records; {len(issues)} records in the review queue.")
    print(f"Results: {destination}")


if __name__ == "__main__":
    main()
