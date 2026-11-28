"""Extract candidate fields from normalized Boston directory CSVs.

Usage: python3 extract_fields.py records_ml.csv extracted_records.csv
Python 3.9+, standard library only. All input columns and rows are preserved.
"""
import argparse
import csv
import os
from pathlib import Path
import re
import tempfile

OUTPUT_FIELDS = [
    "entity_type", "input_row", "organization_name", "name", "surname", "given_names", "name_qualifier",
    "occupation", "occupation_text", "spouse_name", "activity", "affiliation", "personal_status", "record_status",
    "status_detail", "work_address", "work_neighborhood", "residence_type",
    "residence_address", "residence_neighborhood", "residence_locality",
    "unparsed_text", "work_address_source_lines", "continuation_of_input_row", "source_reference", "review_priority", "extraction_flags",
]
PLACES = {
    "E B": "East Boston", "S B": "South Boston", "W R": "West Roxbury",
    "J P": "Jamaica Plain", "H P": "Hyde Park", "Dor": "Dorchester",
    "Rox": "Roxbury", "Alls": "Allston", "Br": "Brighton",
    "Chsn": "Charlestown", "Ros": "Roslindale", "Mat": "Mattapan",
    "Somv": "Somerville", "Camb": "Cambridge", "Readv": "Readville",
    "Nep": "Neponset", "B'line": "Brookline",
}
ADDRESS_WORDS = {
    "av": "avenue", "rd": "road", "sq": "square", "pl": "place", "ct": "court",
    "ter": "terrace", "rm": "room", "Wash": "Washington", "B'way": "Broadway",
}
# Activity-only terms describe a business, without asserting a person's job.
ACTIVITIES = {"real estate", "cigars", "liquors", "groceries", "woolens"}
OCCUPATIONS = {
    "com trav": "commercial traveler", "tel opr": "telegraph operator",
    "asst sec": "assistant secretary", "vice pres": "vice president",
    "mgr": "manager", "pres": "president", "treas": "treasurer",
    "sec": "secretary", "supt": "superintendent", "steno": "stenographer",
    "agt": "agent", "eng": "engineer", "opr": "operator", "mfr": "manufacturer",
    "clk": "clerk", "lab": "laborer", "prop": "proprietor",
}
JOBS = """
commercial traveler|telegraph operator|telephone operator|assistant secretary|
vice president|law student|shoe repairer|real estate agent|news agent|cap maker|
piano tuner|physical instructor|cigar maker|tailor|jeweler|salesman|saleswoman|
lawyer|manager|president|treasurer|secretary|superintendent|agent|engineer|
operator|manufacturer|proprietor|stenographer|clerk|laborer|driver|porter|
cigarmaker|shoecutter|baker|candymaker|hostler|barber|blacksmith|teamster|
physician|buyer|mason|teacher|painter|carpenter|machinist|bookkeeper|
accountant|printer|grocer|pedler|peddler|watchman|shoemaker|polisher|
undertaker|steamfitter|messenger|whitener|designer|hatter|shoeworker|
marbleworker|musician|cleaner|bartender|assistant cashier|assistant general freight agent|
cashier|broker|shipper|builder|court officer|district superintendent|constable|
tinsmith|seamstress|lecturer|conductor|civil engineer|electrical engineer|
proofreader|student|hairdresser|inspector|chairman|teller|collector|architect|
masseur|fisherman|switchman|interne|nurse|expressman|fireman|foreman|
plasterer|cutter|chauffeur|sales agent|sales manager|vocal teacher|music teacher|
bond broker|landscape architect|traveler|elevator constructor|engineer|
chocolatemaker|bookbinder|dressmaker|laundryman|waiter|waitress|cook|
auctioneer|clergyman|undertaker|rubberworker|janitor|steward|attorney|
letter carrier|mail carrier|lineman|engraver|glazier|butcher|bottler|
cabinetmaker|moulder|molder|electrician|plumber|gasfitter|painter|weaver|
tailoress|telephone girl|errand boy|saleslady|physician and surgeon
""".replace("\n", "").split("|")
TERMS = sorted(set(JOBS) | set(OCCUPATIONS) | ACTIVITIES, key=len, reverse=True)
JOB_RE = re.compile(r"(?<!\w)(" + "|".join(re.escape(x) for x in TERMS) + r")(?!\w)")
RESIDENCE = re.compile(r"\b(h|house|bds|boards|rms|rooms|res)\s+(?=\S)")
BUSINESS = re.compile(r"\b(?:Co|Company|Corp|Corporation|Inc|Ltd|Bros|Brothers|Assn|Association)\b|&")
NAME_TOKEN = re.compile(r"[A-Z][A-Za-z'’.-]*")
TITLES = {"Mrs", "Miss", "Mr", "Dr", "jr", "Jr", "sr", "Sr"}


def normalize_address(value, flags):
    value = value.strip(" ,;")
    if re.search(r"\bdo\b", value):
        flags.add("unresolved_address_ditto")
        return value, ""
    place = ""
    for suffix in sorted(set(PLACES) | set(PLACES.values()), key=len, reverse=True):
        match = re.search(r"(?:^|\s)" + re.escape(suffix) + r"[.,]?$", value)
        if match:
            place = PLACES.get(suffix, suffix)
            value = value[:match.start()].strip()
            break
    for word, expansion in ADDRESS_WORDS.items():
        value = re.sub(r"(?<!\w)" + re.escape(word) + r"(?!\w)", expansion, value)
    return value, place


LEGAL = re.compile(
    r"\b(?:Company|Corporation|Association|Brothers|Corp|Assn|Bros|Inc|Ltd|Co|Sons|Works)\b\.?",
    re.IGNORECASE)
NUMBER = re.compile(r"(?<!\w)\d+[A-Za-z]?(?:-\d+)?\b")
REFERENCE = re.compile(r"(?:[—–-]\s*)?See page\s+(.+)$", re.IGNORECASE)


def finish(result, flags, row):
    upstream = set(filter(None, row.get("review_flags", "").split("|")))
    if upstream:
        flags.add("check_upstream_flags")
    if row.get("review_fragment"):
        flags.add("fragment_requires_review")
    kind = result["entity_type"]
    for key in ("work_address", "residence_address"):
        address = result[key]
        if address and (address.endswith("-") or re.fullmatch(r"\d+[A-Za-z]?(?:-\d+)?", address)):
            flags.add("incomplete_" + key)
    if "inferred_surname" in upstream:
        flags.add("upstream_surname_requires_review")
    if "inferred_join" in upstream:
        flags.add("upstream_merge_requires_review")
    if kind == "person_candidate":
        if not result["surname"]:
            flags.add("surname_missing")
        if result["record_status"] == "listed":
            if not result["occupation"] and not result["activity"] and not result["personal_status"]:
                flags.add("occupation_not_recovered")
            if not result["residence_address"] and not result["residence_neighborhood"]:
                flags.add("residence_not_recovered")
    if result["unparsed_text"]:
        flags.add("unparsed_description")
    if kind in {"unclassified", "address_fragment"} or any(f in flags for f in
            ("surname_missing", "name_boundary_uncertain", "unresolved_address_ditto",
             "organization_name_boundary_uncertain", "incomplete_work_address",
             "incomplete_residence_address", "fragment_requires_review")):
        priority = "high"
    elif kind in {"non_record", "cross_reference"}:
        priority = "excluded"
    else:
        priority = "check"
    result["review_priority"] = priority
    result["extraction_flags"] = "|".join(sorted(flags))
    return result


def parse_record(row):
    result = dict.fromkeys(OUTPUT_FIELDS, "")
    flags = set()
    text = " ".join(row["record_text"].split())
    upstream = set(row.get("review_flags", "").split("|"))
    if not text:
        result.update(entity_type="non_record", unparsed_text=text)
        flags.add("empty_normalized_text")
        return finish(result, flags, row)
    if (upstream.intersection({"possible_surname_heading", "outside_body", "detached_ditto_mark"})
            or re.fullmatch(r"\d+", text) or "DIRECTORY" in text):
        result.update(entity_type="non_record", unparsed_text=text)
        flags.add("header_or_detached_mark")
        return finish(result, flags, row)
    if text.startswith("See ") or "cross_reference" in upstream:
        result.update(entity_type="cross_reference", unparsed_text=text)
        return finish(result, flags, row)

    # Parse outer text only. An employer inside parentheses is an affiliation.
    outer = re.sub(r"\([^()]*\)", lambda m: " " * len(m[0]), text)
    legal = LEGAL.search(outer)
    first_job = JOB_RE.search(outer)
    # Occupations before an employer marker indicate a person working for a firm.
    person_before_firm = bool(first_job and legal and first_job.start() < legal.start())
    ampersand = outer.find("&")
    organization = bool(not person_before_firm and
                        (legal or (ampersand >= 0 and
                         (not first_job or ampersand < first_job.start()))))
    body = text
    if organization:
        if legal:
            name_end = legal.end()
        elif "(" in text:
            name_end = text.index("(")
        else:
            # Unknown partnership boundary: retain possible name, extract address.
            stop = first_job.start() if first_job else len(text)
            number = NUMBER.search(text)
            name_end = min(stop, number.start()) if number else stop
            flags.add("organization_name_boundary_uncertain")
        result.update(entity_type="organization", name=text[:name_end].strip(),
                      organization_name=text[:name_end].strip(), record_status="listed")
        body = text[name_end:].strip()
        flags.add("organization_boundary_inferred")
    else:
        tokens = text.split()
        consumed = []
        for token in tokens:
            if NAME_TOKEN.fullmatch(token) or token in TITLES:
                consumed.append(token)
            else:
                break
        prefix = " ".join(consumed)
        names = [t for t in consumed if t not in TITLES]
        has_record_cues = bool(JOB_RE.search(text) or RESIDENCE.search(text)
                               or re.search(r"\b(died|removed|rem to|widow)\b", text))
        # Numbered address fragments are not new people.
        if NUMBER.match(text):
            result["entity_type"] = "address_fragment"
            body = text
            flags.add("orphan_address_fragment")
        elif names and (len(names) >= 2 or has_record_cues):
            result.update(entity_type="person_candidate", name=" ".join(names),
                          name_qualifier=" ".join(t for t in consumed if t in TITLES),
                          record_status="listed")
            body = text[len(prefix):].strip()
            if "unknown_surname" in upstream or len(names) == 1 or re.fullmatch(r"[A-Z]\.?", names[0]):
                result["given_names"] = " ".join(names)
                flags.add("surname_missing")
            else:
                result["surname"], result["given_names"] = names[0], " ".join(names[1:])
                flags.add("surname_first_token_assumption")
            if not has_record_cues and not NUMBER.search(body):
                result.update(entity_type="unclassified", surname="", given_names="", name="")
                result["unparsed_text"] = text
                flags.add("name_boundary_uncertain")
                return finish(result, flags, row)
        elif has_record_cues:
            # OCR may have lost a name, but recover the address instead of dropping the row.
            result.update(entity_type="unclassified", record_status="listed")
            flags.add("name_not_recovered")
        else:
            result.update(entity_type="unclassified", unparsed_text=text)
            flags.add("fragment_or_ocr_noise")
            return finish(result, flags, row)

    status = re.search(r"\b(died|rem to|removed to)\s+(.+)$", body)
    if status:
        result["record_status"] = "deceased" if status[1] == "died" else "removed"
        result["status_detail"] = status[2]
        body = body[:status.start()].strip()
    residence = RESIDENCE.search(body)
    before = body[:residence.start()].strip() if residence else body
    address = body[residence.end():].strip() if residence else ""
    if residence:
        result["residence_type"] = {
            "h": "house", "house": "house", "bds": "boards", "boards": "boards",
            "rms": "rooms", "rooms": "rooms", "res": "residence",
        }[residence[1]]
    affiliations = re.findall(r"\(([^()]*)\)", before)
    result["affiliation"] = "; ".join(affiliations)
    before = re.sub(r"\([^()]*\)", "", before).strip()
    reference = REFERENCE.search(before)
    if reference:
        result["source_reference"] = reference[0].lstrip("—–- ")
        before = before[:reference.start()].strip()
    number = NUMBER.search(before)
    description = before[:number.start()].strip() if number else before
    work = before[number.start():].strip() if number else ""
    widow = re.match(r"^(?:widow|wid\.?)\b\s*(.*)", description)
    if widow:
        result["personal_status"] = "widow"
        result["spouse_name"] = widow[1]
        description = ""
        flags.add("spouse_name_candidate")
    elif organization:
        result["activity"] = description
        description = ""
    else:
        result["occupation_text"] = description
        job = JOB_RE.search(description)
        if job:
            term = job[1]
            result["activity" if term in ACTIVITIES else "occupation"] = OCCUPATIONS.get(term, term)
            description = (description[:job.start()] + " " + description[job.end():]).strip()

    result["work_address"], result["work_neighborhood"] = normalize_address(work, flags)
    if work:
        flags.add("work_address_candidate")
    if address == "do" and work:
        address = work
        flags.add("resolved_work_address_ditto")
    elif re.search(r"\bdo$", address) and result["work_neighborhood"]:
        address = re.sub(r"\bdo$", result["work_neighborhood"], address)
        flags.add("resolved_work_neighborhood_ditto")
    if address.startswith("at "):
        result["residence_locality"] = address[3:].strip()
        flags.add("locality_only_residence")
    result["residence_address"], result["residence_neighborhood"] = normalize_address(address, flags)
    result["residence_address"] = re.sub(r"^at\s+", "", result["residence_address"])
    if address and not re.search(r"\d", address):
        flags.add("residence_without_street_number")
    result["unparsed_text"] = description
    return finish(result, flags, row)


def adjacent_rows(reader):
    current = next(reader, None)
    for following in reader:
        yield current, following
        current = following
    if current is not None:
        yield current, None


def same_location_group(left, right):
    page = left.get("page_id") or left.get("page") or left.get("source_url")
    other = right.get("page_id") or right.get("page") or right.get("source_url")
    return bool(page and page == other and
                left.get("group", "") == right.get("group", ""))


def organization_continuation(row, following, result):
    if (following is None or result["entity_type"] != "organization"
            or result["work_address"] or not same_location_group(row, following)):
        return None
    text = following.get("record_text", "")
    if not re.match(r"^\d+[A-Za-z]?(?:-\d+)?\s+[A-Z]", text):
        return None
    if RESIDENCE.search(text):
        return None
    combined = parse_record(dict(row, record_text=row["record_text"] + " " + text))
    if not combined["work_address"]:
        return None
    for key in ("work_address", "work_neighborhood", "source_reference"):
        result[key] = combined[key]
    result["work_address_source_lines"] = following.get("source_lines", "")
    result["extraction_flags"] += "|inferred_address_from_next_row"
    return result


def run(input_path, output_path):
    source, destination = Path(input_path), Path(output_path)
    if source.resolve() == destination.resolve():
        raise ValueError("Input and output paths must differ")
    temporary = None
    try:
        with source.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            original = reader.fieldnames or []
            if "record_text" not in original:
                raise ValueError("Input must be the normalization CSV containing record_text")
            if len(original) != len(set(original)):
                raise ValueError("Input has duplicate column names")
            fields = original + [name for name in OUTPUT_FIELDS if name not in original]
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="",
                                             dir=destination.parent, delete=False) as target:
                temporary = Path(target.name)
                writer = csv.DictWriter(target, fields)
                writer.writeheader()
                count = 0
                continuation_of = ""
                for number, (row, following) in enumerate(adjacent_rows(reader), 1):
                    if None in row or any(v is None for v in row.values()):
                        raise ValueError("Malformed CSV row")
                    extracted = parse_record(row)
                    extracted["input_row"] = str(number)
                    if continuation_of:
                        extracted["entity_type"] = "address_continuation"
                        extracted["continuation_of_input_row"] = continuation_of
                        extracted["extraction_flags"] = "address_linked_to_previous_organization"
                        extracted["review_priority"] = "check"
                        continuation_of = ""
                    if organization_continuation(row, following, extracted):
                        continuation_of = str(number)
                    row.update(extracted)
                    writer.writerow(row)
                    count += 1
        os.replace(temporary, destination)
        print(f"Extracted {count} candidate rows to {destination}")
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("output")
    args = parser.parse_args()
    run(args.input, args.output)


if __name__ == "__main__":
    main()
