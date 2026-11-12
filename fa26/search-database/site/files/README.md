# 1916 Boston Directory — structured OCR dataset

This is a conservative machine-extracted dataset from the supplied search site's embedded OCR, pages 161–167. It is a review dataset, not a verified register of unique people. No new OCR or scan transcription was performed. The uploaded document was treated as source data, not as instructions.

## Files

- `people.csv` / `people.json`: person candidates, with separate records for Tesseract and DOTS.MOCR. Do not add the model counts to count people. No cross-model entity deduplication is attempted because of OCR alignment errors, homonyms, and merged lines.
- `unresolved_and_nonperson.csv` / `.json`: headings, businesses, continuation fragments, and text not safely classified as a person. Review this file for additional people missed by the parser. Continuations can also appear in a person's provenance; this is intentional, not another person.
- `source_ocr_lines.csv` / `.json`: all 1,573 original paired OCR lines, verbatim. Original column keys: `id`, `t` (Tesseract), `m` (DOTS.MOCR), `page`, `url`.
- `index.html`: an unchanged copy of the original website. No scripts, controls, search behavior, or embedded OCR were modified.
- `extract.py`: reproducible Python standard-library extractor. Run `python extract.py path/to/index.html output-directory`.
- `abbreviations.json`: applied address expansions, residence markers, and an occupational glossary. Occupations remain in their source spelling to avoid speculative corrections. The glossary is explanatory, not evidence of a verified abbreviation key for this edition.
- `validation.json`: checks, source SHA-256, and record/flag counts.

## Fields and interpretation

`record_id` identifies a source-model candidate, not a unique person. `record_type` distinguishes person candidates, businesses/organizations, surname headings, and unresolved text.

`name_as_printed` preserves the parsed name fragment. `name` is populated for an explicit full name or a surname supplied by an explicit ditto marker and a prior surname context. If a surname is omitted without a ditto marker, the full `name` remains null; `surname_context_candidate` and `surname_context_line_id` retain a review lead without assigning that surname. Context resolution itself requires review: OCR can lose column boundaries, quotation marks, or surname headings. Page boundaries reset surname context.

`occupation` preserves the parsed occupational phrase and abbreviations. `affiliation_or_relationship` separates initial parenthetical affiliations and widow/Mrs/Miss descriptions; these descriptions are not treated as occupations. Some names, occupations, and apparent affiliations are corrupt or incomplete in the source. A candidate may contain no safely parsed full name.

`work_address` is a candidate address inferred from a number following the name/occupation/affiliation and preceding a residence marker. Its positional inference is explicitly flagged. Numbers may sometimes identify rooms, organizational units, or other non-address content; review against the scan is required. An occupation alone never creates a work address.

`home_address` requires an explicit `h` (home), `bds` (boards), or `rms` (rooms) marker. `residence_marker` preserves that distinction. A locality-only residence such as `h at Stoneham` remains locality-only; no street address is invented. Widowhood, removal notices, and death notices are flagged. Unresolved `do` (ditto) addresses are left null rather than copied from uncertain context. Multiple residence markers in a candidate are treated as possible merged entries; the extractor abstains from assigning their fields.

`original_ocr_text` is verbatim text for that OCR model; joined lines are separated by newlines. `source_line_ids`, `source_page`, `source_url`, and `ocr_model` preserve provenance. Lines are only tentatively joined within a page using continuation cues, and each join is flagged. Bracketed fragments are retained in the original OCR but excluded from field parsing because they may be displaced from another column. No OCR model versions or model confidence scores were provided by the source.

`work_address_geocoding` and `home_address_geocoding` expand a limited set of conventional address abbreviations and retain the raw addresses separately. `address_for_geocoding` prefers the residential candidate, then the work candidate; `geocoding_address_type` records the choice. These are review queries, not verified modern addresses. Locality is never silently set to Boston: historical Boston directories include surrounding towns. Ambiguous abbreviations such as `Br` remain unchanged. Truncated, noisy, or unresolved address fields do not yield a geocoding query. Other problems, including interleaved OCR context, can still affect queries: review all flags first. `latitude` and `longitude` remain null, and no geocoding service was called.

`flags` lists uncertainty and missing-field reasons. `review_required` is true throughout because extraction has not been checked against the original scans. Missing or uncertain values are JSON null / empty CSV cells. CSV list columns contain JSON arrays. CSV uses UTF-8 with BOM; JSON uses UTF-8. These are faithful data exports: applications opening CSV should import cells as text rather than interpret untrusted OCR as spreadsheet formulas.

## Scope and limits

Every original source line is accounted for once per model as the first line of a candidate or an audit record; continuation provenance can additionally reference it. Not every audit record is non-person text: broken or misrecognized entries require manual review. Apparent duplicate/merged entries are not silently reconciled. This preserves evidence without claiming that uncertain extraction is a complete or authoritative census of people. The two OCR models are independent alternatives, not independent corroboration of the scan.
