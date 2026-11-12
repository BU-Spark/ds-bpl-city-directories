# A-section pilot: source acquisition and first-pass extraction

This folder contains **step 1: source acquisition and sample selection**, followed
by **step 2: rule-based extraction and development image checks**. It extends Katherine's
`fa26/scripts/api_look.ipynb`, using the same Internet Archive item and metadata API.
It downloads individual full-resolution JPEG renderings of the original scans;
these are not the archival JP2 master files. Step 2 retrieves the existing Internet
Archive word OCR for the selected page. No new OCR model, paid model API, or
geocoder is used. Start with `extraction/report.md` for the latest results.

## Selected sample

- Volume: 1916 Boston Directory, A–O (`bostonmassachuse1916112samp`).
- Sample: **53 personal entries on printed page 161**, from **Aalto J** through
  **Abberton T Frank**. Read the left listing column first, then the right.
- There are 19 selected personal entries in the left column and 34 in the right.
- Companies and the surname cross-reference are excluded from the sample count;
  the full, unedited page image preserves them as context.
- A person listed with a business affiliation is still included.
- Aaronson Barnard's death notice and Abber Annie Mrs's removal notice are included
  and flagged. These are personal directory entries, not proof of current residence.
- Printed page 162 is downloaded only for context / a later extension toward 100
  records. It is not included in the current 53-record count.

The 53-entry boundary is a convenient complete-page pilot within the team's
50–100-record range. It is an alphabetical convenience sample, not a representative
sample of all 1916 residents. The same first page also contains the abbreviation key.

`sample_index.csv` is a **selection aid**, not a gold-standard transcription. Its
locator labels have inherited surnames written out for navigation; occupations in
parentheses only distinguish the two Abate Francesco entries. Labels and notice
flags were visually checked by the assistant and still need team review before
they are used as reference answers. The index itself contains no parsed
occupation/address fields; those now live separately in `extraction/records.csv`.

## Reproduce

From the repository root, using Python 3.9 or newer (no extra packages):

```sh
python3 fa26/scripts/download_a_sample.py
python3 fa26/scripts/extract_a_sample.py
```

Or run `fa26/scripts/01_download_a_sample.ipynb`, followed by
`fa26/scripts/02_extract_a_sample.ipynb`. The scripts locate inputs relative to
their own files, so they also work when
launched from another working directory. The first run requires internet access.
Subsequent runs reuse the downloads. Step 1 recreates the two source indexes;
step 2 recreates the five files in `extraction/`. Save review edits in `review/`,
not in generated CSVs, so reruns will not erase them.
To intentionally fetch a fresh source file, remove that specific cached file first.

Selection is recorded in `fa26/config/a_sample_selection.json`. Edit that file
when the team intentionally changes the sample; do not hand-edit generated indexes.
Adding a printed page downloads it, but does not automatically select its people:
the locator list must be reviewed separately against the new scan.

## Files

| File | Purpose |
|---|---|
| `images/*_p161.jpg` | Complete first A-section page, including abbreviation key |
| `images/*_p162.jpg` | Complete following page for a later extension |
| `pages.csv` | One row per downloaded page: source URLs, IDs, local file, dimensions, checksum |
| `sample_index.csv` | 53 stable sample IDs, names for locating entries, column and source page |
| `source/metadata.json` | Original Internet Archive metadata API response |
| `source/scandata.xml` | Original mapping from scan leaf numbers to printed pages |
| `source/iiif_manifest.json` | Original image catalog containing canvas IDs and image URLs |
| `source/p161_ocr.json` | Original page-specific OCR annotations: words, coordinates and canvas links |
| `extraction/records.csv` | One row for each of the 53 selections, including missing entries; raw/normalized fields and provenance |
| `extraction/ocr_lines.txt` | Derived OCR in column/line order, with line IDs and bounding boxes |
| `extraction/issues.csv` | Review queue: rule flags and observed image disagreements; a flag is not necessarily an error |
| `extraction/check_results.csv` | Field-by-field comparison with the 15 assistant image checks |
| `extraction/report.md` | Short results summary, limitations and questions for the client meeting |
| `review/image_checks.json` | Persistent image-based reference transcriptions, expected fields and notes for 15 entries; human review pending |

The source files and images are ignored by Git because they are reproducible
downloads. The scripts, notebooks, config, README, review input and small extracted
outputs can be versioned. There are no separate per-entry files or timestamped copies.

## What step 2 does

```text
Cached scan + page/source mapping + 53-entry selection
  → existing word OCR for that exact canvas
  → left/right column ordering and physical lines
  → entry grouping and candidate raised-bracket continuations
  → surname context, occupation and address rules
  → match OCR candidates to the selected people
  → 53-row baseline + separate image checks + review queue
```

The known locator names help find the selected entries. They are **never copied
into extracted name fields** to repair missing OCR. Each OCR candidate can match
at most one selection; ambiguous or absent matches remain `not_recovered`. This
is sample-assisted development, not a blind person-detection evaluation.

The baseline and the image reference answers remain separate. Reading
`review/image_checks.json` only produces comparisons and flags; it does not
silently correct the baseline. For example, the baseline retains the OCR's
`668 Blue Hill av Dor`, while the image check records `568 Blue Hill av Dor`.

## Reading the result table

| Fields | Meaning |
|---|---|
| `sample_id`, `selection_label` | Stable selection ID and navigation label; the label is not extracted output |
| `extraction_status` | `candidate` means matched to an OCR candidate, not fully correct; `not_recovered` means no usable match |
| `raw_ocr_text` | Word OCR assembled into the candidate's physical line group, preserving errors and line breaks |
| `working_text` | Derived entry text after joining wraps and moving candidate raised-bracket fragments |
| `surname`, `given_name`, `name_qualifier` | Name parsed from OCR/context; initials retained; Mrs/Miss/Mr separate |
| `occupation_raw`, `occupation_normalized` | Parsed description and expanded wording; no occupational taxonomy assigned |
| `affiliation_raw` | Printed firm association or unclassified text before an address; unresolved text is flagged |
| `work_address_raw`, `work_address_normalized` | Workplace address before the residence marker, plus a cautiously expanded form |
| `residence_type_raw`, `residence_type_normalized` | `h` → house, `b`/`bds` → boards, `rms` → rooms; these do not establish ownership |
| `residence_address_raw`, `residence_address_normalized` | Residence after the marker, plus expanded abbreviations/resolved `do` when possible |
| `neighborhood_raw`, `neighborhood_normalized` | Residence suffix as printed in OCR, plus expanded/inherited neighborhood; not a geospatial classification |
| `record_status`, `status_detail_raw` | `listed`, `deceased` or `removed`, with the original date/destination text for notices |
| `field_verification`, `review_flags` | Baseline remains `unverified_rule_output`; flags explain cases requiring attention |
| `image_check_status`, `image_check_differences` | Assistant checked agreement/mismatch or not checked; differing fields listed |
| `page_id`, `printed_page`, `column`, `source_line_ids` | Exact page and contributing OCR lines, including preceding lines that supply raised continuations |
| `source_page_url`, `canvas_id`, `local_image`, `ocr_source_url` | Links back to the viewer, source canvas, cached scan and original OCR |

`raw_ocr_text` is not a verbatim image transcription: it is the existing OCR.
It may still contain a raised fragment belonging to the next entry. Consult
`working_text` for the proposed entry boundaries and `source_line_ids` in
`ocr_lines.txt` for all contributing physical lines. Parsed `*_raw` fields come
from the working text: they retain abbreviations but have joined continuations.

Blank fields mean absent or not recovered, not a numeric zero or a verified
negative. Consult status/flags and the scan. Missing entire entries retain their
sample/source identifiers but have blank extracted fields.

## Conventions and review limits

- The abbreviation key on page 161 supports expansions such as `com trav`
  (commercial traveler), `tel` (telegraph), `h` (house) and neighborhood codes.
  This is a limited lookup for the pilot, not a complete dictionary for all years.
- `h do` can repeat the whole workplace address; a trailing `do` after a different
  street address can repeat only the workplace neighborhood. Unresolved `do`
  is flagged and its normalized residence is left blank.
- For full-address `do`, `neighborhood_raw` stays blank because no separate
  neighborhood is printed; `neighborhood_normalized` may inherit one. Neither
  blank nor absence of a suffix proves a person lives in Boston proper.
- A locality-only residence such as `at Stoneham` is retained and flagged. No
  street, Boston neighborhood, coordinates or current street equivalent is invented.
- `cigars`, `liquors` and `real estate` are preserved as activities. Their
  normalized occupation is blank pending a decision about role classification.
- Death/removal notices are retained with a status. They do not supply a
  confirmed current residential address for spatial analysis.
- The 15 image checks were produced by the assistant during development and
  deliberately include hard cases. They need human review; their agreement
  counts are **not** held-out accuracy or an estimate for all 53 entries.
- Check comparisons cover 16 fields, including expected blanks, and ignore
  whitespace only. They do not evaluate geocoding or every possible schema field.
- Numeric field confidence scores are not yet implemented. Current flags are
  review signals, not calibrated confidence probabilities.

The script currently uses page-161 bounds/indentation settings and A-section
surname rules. Acquiring more pages is supported by step 1, but reliable
extraction across more pages or years requires layout/generalization work and
independent human-verified evaluation. Matching 51 entries is not proof that all
51 are correct.

Run focused regression checks from the repository root:

```sh
python3 -m unittest discover -s fa26/tests -v
```

The tests cover continuation boundaries/provenance, ditto meanings, missing
values, selection ambiguity and separation of review answers from baseline data.
One integration check uses the cached OCR and is skipped if it is not downloaded.

## Page numbering: do not substitute one number for another

| Printed page | Scan leaf number | IIIF canvas index (0-based) | IIIF canvas label |
|---|---|---|---|
| 161 | 163 | 162 | 163 |
| 162 | 164 | 163 | 164 |

The script reads the leaf number from the image's JP2 filename, then looks up the
printed page in `scandata.xml`. It does not assume that the canvas label is the
printed page, or use a fixed `+2` offset. Printed page 161 was verified on the scan
at its bottom; printed page 162 is visible at the top of the next scan.

`source_page_url` opens the Internet Archive viewer using its printed-page label.
`canvas_id` and `image_url` preserve the exact source identities from the manifest.
The stable `page_id` uses the item ID plus leaf number. `local_image` is relative
to this folder, and `sha256` identifies the actual downloaded JPEG bytes.

The line-number cut in the earlier notebook is not used to identify these pages:
the A section begins on printed page 161, and existing plain OCR has missing or
scrambled lines. OCR line counts are not record counts.

## Before the second client meeting

1. Have a team member check the 15 reference entries against page 161, especially
   the six current disagreements. Record verified corrections in the review input,
   with reviewer attribution; do not mark assistant-only checks as human gold.
2. Present one ordinary entry, one `do`/bracket continuation and one OCR omission
   using the scan, raw OCR and extracted fields together.
3. Use `extraction/report.md` to discuss field definitions and analytical treatment
   of special cases. Keep source-recovery errors as a team engineering task.
4. After agreeing the conventions, extend the reviewed reference set and decide
   whether the existing OCR is sufficient or a fresh image-based OCR pass is needed.
