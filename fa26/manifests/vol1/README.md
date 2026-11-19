# A–O source scope · reviewed 2026-11-18

This manifest identifies source pages, not completed OCR or verified residents.
It was built from the public IA item
[bostonmassachuse1916112samp](https://archive.org/details/bostonmassachuse1916112samp).

## Scope

| Category | Scanned leaves | Count | OCR role |
| --- | --- | ---: | --- |
| General alphabetical directory | 163–1534, excluding 781–782 | 1,370 | Primary |
| Late additions/removals, printed p160 | 162 | 1 | Supplementary, separate from the main sequence |
| Other scans | All remaining leaves | 173 | Excluded |
| Entire scandata inventory | 0–1543 | 1,544 | Source inventory only |

IA marks **1,538** scans as available in access formats. The remaining six are
deleted scans/calibration cards. All 1,538 accessible leaf identifiers,
BookReader indices and native dimensions were checked against the official
[IIIF manifest](https://iiif.archive.org/iiif/bostonmassachuse1916112samp/manifest.json).

The general directory starts below the abbreviation key on printed p161
(leaf 163). The final directory scan is printed p1534 (leaf 1534), ending with
Olsen/Olson/Olstein entries. This does not complete every O-surname: continuation
in Vol. 2 is outside this run's scope. The following leaves are blank/endpapers
and a back cover. The separate business directory named in the contents begins
at p2145, beyond this item's final directory page.

The main alphabetical directory itself includes firms, deceased people,
removals and cross-references. Primary page inclusion is not resident inclusion.
Page 160 also mixes people and businesses and can contain surnames outside A–O;
keep its supplementary role during later reconciliation.

## Pagination findings

- **Leaf 781 and 782:** unnumbered Cat's Paw advertisements, visually checked and
  explicitly excluded from the primary directory.
- **Printed labels 775–778:** absent from the source index. The adjacent scans
  show p774 (leaf 776) and p779 (leaf 777). This is a documented source-coverage
  question; a missing scan, a printing issue or another cause has not been
  established. No pages or text have been invented to fill the gap.
- **Leaf 161:** the paper is headed **153–159** on one physical page; scandata
  records only 159. A documented visual label override preserves the composite
  label. Do not interpret this metadata jump as six absent physical scans.
- **Printed labels 17–18:** absent before p19 in the street-directory reference
  section, outside the primary OCR scope. The cause remains unresolved.
- The independent `page_numbers.json` disagrees with scandata on 23 leaves,
  including 160→154 and 161→155 at leaves 162–163. Both values are retained;
  scandata is used unless a documented visual override exists.

Printed page numbers, scanned leaf numbers and BookReader **n-indices** are
different. For example, printed **162 = leaf 164 = BookReader n163**. Reader URLs
use the accessible zero-based n-index to avoid ambiguous inferred page labels.
See [Open Library's page URL specification](https://openlibrary.org/dev/docs/bookurls).

## Files and reproduction

- `pages.csv`: readable inventory of every scan and its inclusion reason.
- `manifest.json`: complete machine-readable configuration, source hashes and
  pages; its `manifest_id` detects unintended changes.
- `scope_report.json`: counts, absent printed labels and source-index conflicts.
- `visual_checks.csv`: 15 targeted boundary/anomaly checks, including review
  image hashes and exact image/reader URLs.
- `validation.json`: IIIF cross-check summary and canonical response hash.
- `source/`: public metadata/scandata/page-number snapshots, sufficient for an
  offline rebuild. The IA file MD5s are checked as well as local SHA-256 records.

From the repository root, in the configured environment:

```sh
bpl-ocr manifest --config fa26/config/vol1.json --output fa26/manifests/vol1 --offline
```

To intentionally fetch current metadata before rebuilding, replace `--offline`
with `--refresh` and review the resulting changes. The raw JP2 archive is never
downloaded by manifest preparation. JPEG hashes and actual dimensions are added
to each source receipt when that page is downloaded for OCR.

These are boundary/anomaly checks, not an exhaustive visual classification of
every page. Pre-p160 reference pages are grouped coarsely as front matter,
street directory and city record. Headers, margins, nonresident entries and
reading order need the planned cross-page quality review in stage 3.
