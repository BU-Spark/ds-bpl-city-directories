# 1916 Boston Directory search database

An English search website and structured OCR dataset for pages 161–167 of the 1916 Boston City Directory. Search names, occupations, work addresses and home addresses; filter by source page, OCR model and address availability; inspect original OCR and uncertainty flags; and export all matching results as CSV or JSON.

The dataset preserves Tesseract and DOTS.MOCR readings separately: 1,573 paired source lines yield 1,922 **candidate records, not unique people**. These records have not been manually verified against the scans. Historical abbreviations, uncertain surname context, wrapped or merged entries, missing addresses and OCR disagreements require review. Address queries are prepared for future geocoding; no coordinates have been assigned.

## Run the website

From this directory, with Python 3 installed:

```sh
python -m http.server 8000 --directory site
```

Open <http://localhost:8000>. No packages, build step, API keys or database server are required. The search loads the bundled JSON and runs in the browser. The included dataset is a static snapshot; exports do not change repository files.

For offline use, double-click `site/files/boston-1916-search-english.html`, or extract `site/files/boston-1916-english-search-website.zip` and open its `index.html`. Searching and exporting work offline; external scan links require internet. The standalone HTML's navigation links point to the hosted site. The original OCR comparison search remains unchanged at `site/ocr.html`.

## Using search

1. Enter English keywords, such as `Aaron`, `lawyer`, `Court` or `Stoneham`. Matching is case-insensitive; all keywords must match.
2. Select the search field and optionally filter by page, OCR model or address availability. Names may include uncertain OCR fragments; the interface labels these.
3. Expand a result to inspect raw OCR, geocoding preparation and review flags. Select **View original scan** to check the source.
4. Select **Export results · CSV** or **JSON** to export all matching records, not just the visible page. **Download data** includes the complete offline website and data files.
5. Select **Original OCR search** to compare both models side by side for a source line. The structured search displays model-specific candidates separately.

## Files

- `site/`: static website source, stylesheet and browser scripts. `site/files/` contains downloads, data used by search, the offline website and the two-slide English user guide.
- `data/people.csv`, `data/people.json`: structured candidates; identical to the corresponding website data files.
- `data/source_ocr_lines.*`: complete paired original OCR, with page and scan URLs.
- `data/unresolved_and_nonperson.*`: unparsed text, headings, businesses and continuation fragments retained for review. Some fragments may contain people missed by the parser.
- `data/abbreviations.json`: residence markers, selected address expansions and an occupation glossary.
- `data/validation.json`: source checksum and extraction counts from the original export.
- `docs/DATASET.md`: detailed field definitions and extraction limitations. References in that original export guide describe the original flat dataset package.
- `scripts/extract.py`: reproducible Python standard-library extraction from the supplied HTML.
- `scripts/validate.py`: checks source provenance, export consistency and original OCR preservation.
- `tests/search.cjs`: dependency-free Node checks of filtering, rendering, pagination and export handlers using a simulated DOM; this is not a real browser test.

## Reproduce and validate

```sh
# Reproduce the original flat exports in a separate directory.
python scripts/extract.py site/ocr.html work/extracted

# Validate checked-in data and source provenance.
python scripts/validate.py

# Check search behavior (Node.js 18+).
node tests/search.cjs
```

Regenerating the dataset does not automatically refresh the embedded offline HTML and website ZIP. When changing data, rebuild those downloads as well before distributing a new snapshot. The checked-in website downloads currently match the supplied dataset.

## Provenance and scope

Source: user-supplied OCR search HTML for the 1916 Boston Directory, Internet Archive / Boston Public Library, <https://archive.org/details/bostonmassachuse1916112samp/page/161/mode/1up>. No additional OCR, model training, geocoding or automated person deduplication was performed. CSV spreadsheet users should import raw OCR as text. Filtered CSV exports guard against formula interpretation.

This component is self-contained under `fa26/search-database/`. It adds no CI or hosting configuration and does not alter the repository's existing extraction pipeline, source data or requirements. Hosting account metadata and credentials are intentionally excluded.
