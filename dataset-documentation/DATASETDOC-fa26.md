***Project Information*** 

**Project Name:** Boston Public Library (BPL): Boston City Directories Collection
**Github Repository:** https://github.com/BU-Spark/ds-bpl-city-directories.git
**Google Drive:** https://drive.google.com/drive/folders/1lupe8jc-6P4AzP2e0z5tHROopPPMQVj9
**Clients:** Boston Public Library and Leventhal Map & Education Center
**Client Contacts:** Eben English and Garrett Dash Nelson
**Class:** DS701

**What it's about:**
Converting the digitized 1916 Boston City Directory (~3,000 pages of raw, shorthand-heavy OCR text) into a structured, geocoded dataset of Boston's residents, occupations, and addresses.

**The goal:**
Build a reproducible Python pipeline to extract, normalize, and geocode the directory entries (with accuracy validation) into a CSV and GeoJSON dataset. This allows researchers and the Boston Public Library / Leventhal Map & Education Center to map 1916 socioeconomic patterns and compare who lived in the city against who owned property on historical city atlases (Atlascope).

***Dataset Information***

**Datasets:** [1916 Boston Directory, Vol. 1 (A–O)](https://archive.org/details/bostonmassachuse1916112samp) and [1916 Boston Directory, Vol. 2 (O–Z)](https://archive.org/details/bostonmassachuse19162112samp)

**Data Dictionary:**
Based on ground truth dataset
Tags: OCR, NLP, Named Entity Recognition, Geospatial Analysis & Geocoding, Data Cleaning / ETL, Entity Resolution / Record Linkage, Housing, Civic Tech, Transportation, Digital Humanities, Urban History, Historical GIS, Labor & Demographics, Boston / New England Heritage

| Field Name | Data Type | Description | Example Value |
| :--- | :--- | :--- | :--- |
| **Year** | Integer | Publication year of the directory volume | `1916` |
| **Page** | Integer | Physical/scanned page number in the volume | `165` |
| **Surname** | String | Individual's last name (carried down from column header if omitted via ditto) | `Abramson` |
| **Given name** | String | Individual's first name and/or middle initials | `Harry` |
| **Occupation (as printed)** | String | Unnormalized trade, profession, or role as it appears in the text | `grocer` |
| **Employer / affiliation** | String | Associated business, firm, or organization (often parenthetical in source) | `Abramson Bros` |
| **Work address (raw)** | String | Unnormalized business or workplace street address(es) as printed | `409 and 520 Main` |
| **Home address (raw)** | String | Unnormalized residential street address as printed | `43 Eden` |
| **Residence marker** | String | Shorthand indicator of housing status (`h` = home/head of household, `bds` = boards) | `h` |
| **Transcription (working)** | String | Full raw/working text string of the directory entry | `Harry (Abramson Bros) grocer 409 and 520 Main Chsn and 45 Eden do h 43 do` |

*Motivation* 

While the raw scans and OCR text are hosted on the Internet Archive, the structured, geocoded dataset itself is being created specifically for this project by the Boston Public Library (BPL), the Leventhal Map & Education Center, and BU Spark!.

The dataset transforms the 1916 Boston City Directory (~3,000 pages of dense, shorthand-heavy, unstructured OCR text) into a clean, structured, and geocoded tabular/spatial dataset (CSV and GeoJSON) covering Boston's residents, occupations, housing tenure (h vs. bds), and addresses.

  1. Spatial & Historical Mapping: To be ingested as a queryable geographic layer inside the Leventhal Center's historical mapping tools (specifically Atlascope).

  2. Socioeconomic Research: To enable quantitative analysis of 1916 Boston—specifically mapping occupational clustering, homeownership versus boarding rates across neighborhoods, and suburban commuting patterns into Boston proper.

  3. Pipeline Benchmarking: To establish an open-source, documented extraction and accuracy-validation workflow that future teams can reuse on other directory years.

The Gap It Fills:

  1. Usability Gap: On the Internet Archive, the directories exist only as a "wall of words"—searchable as raw, error-prone OCR text full of 1916 abbreviations and ditto marks (do), making them impossible to filter, aggregate, or map as data.

  2. Historical Data Gap (Occupancy vs. Ownership): Existing historical city atlases (from the 1880s–1940s) record who owned property in Boston, whereas city directories record who actually lived and worked there. Until now, neither source supported comparing property ownership against actual residency; structuring and geocoding the directory bridges that gap.

*Composition*

Each instance represents an individual residential directory listing (a person living and/or working in Boston in 1916), along with a secondary manually transcribed ground-truth validation subset. The dataset is delivered in tabular (CSV) and geospatial (GeoJSON) formats, derived from underlying text (OCR) and image (JP2 scans) data.

The final dataset targets the complete residential listings across both 1916 volumes (~3,000 pages total, representing hundreds of thousands of individual resident entries—exact count determined upon full pipeline execution), paired with a manually transcribed ground-truth sample for accuracy benchmarking.

It is a sample of a larger historical collection—specifically, a single year (1916) and section (residential listings, excluding business and street directories) drawn from the broader Boston City Directories series (published late 1700s–1980s). It is not statistically representative of all years, as demographics, city boundaries, and publisher conventions shifted over time.

Each instance of the ground truth and OCR tables contains both raw and extracted/engineered features: raw OCR text (Transcription (working)), source provenance (Year, Page), extracted fields (Surname, Given name, Occupation, Employer, Work/Home address, Residence marker, Neighborhood), normalized values, geocoded coordinates (Latitude, Longitude), and extraction/geocoding confidence scores.

Certain fields (such as middle initials, employers, work addresses, or residence markers) are frequently absent because they were omitted in the original 1916 print publication. Additionally, geocoded coordinates (Lat/Lon) will be missing (null) for entries with renamed, vanished, or unresolvable historical street addresses, or suburban residences outside the geocoder's coverage.

There is no recommended data split, however, the manually transcribed ground-truth sample serves as an evaluation/benchmark split to measure field-level extraction accuracy against the full automated output. 

Primary sources of noise include 1916 OCR artifacts (misread characters, broken hyphens, merged columns), ditto-mark (do) propagation errors (misattributing surnames or streets down a column), shorthand ambiguity, and geocoding mismatches caused by 20th-century street renamings or urban renewal. Redundancies may occur when individuals have multiple listings (e.g., cross-referenced at both home and business addresses).

The extracted CSV/GeoJSON files are self-contained, though each record includes a source page reference linking back to the Internet Archive volumes, and geocoding relies on external reference layers (e.g., US Census Geocoder / BPL historical street data).

  - Persistence: Internet Archive items use persistent identifiers, and BPL/Digital Commonwealth steward archival copies, though third-party geocoding APIs can change over time.

  - Archival versions: Yes—the underlying 1916 volumes are permanently archived on the Internet Archive and held physically/digitally by BPL.

  - Restrictions: The 1916 directory is in the public domain with no licensing fees or access restrictions.

All records are derived from a publicly published 1916 directory (over 110 years old) and contain no private communications or legally privileged data.

None of the content is necessarily sensitvie or offensive, as it consists of factual names, addresses, and trades. However, as an unedited historical document from 1916, certain archaic occupational titles, institutional names, or demographic labels may reflect outdated social norms or biases of the era.

Every instance explicitly lists a natural person’s full name, occupation, and exact street address. Because the records date from 1916, the vast majority of listed individuals are deceased, minimizing modern privacy risks, though records can be linked to living descendants via genealogical research.

| Size of dataset | ~24 MB of plain OCR text (~12 MB per volume across Vol. 1 A–O and Vol. 2 O–Z) |
| :---- | :---- |
| Number of instances | ~3,000 scanned pages (~120,000+ raw text lines in Vol. 1) |
| Number of fields  | 1 |
| Labeled classes | 0 |
| Number of labels  | 0 |
  
*Collection Process*

* **Collection mechanisms & validation:** Raw OCR text (`_djvu.txt`) and scanned page images (`JP2`) were collected programmatically via the **Internet Archive API** using the `internetarchive` Python library. The ground-truth evaluation subset was **manually transcribed** by team members directly from the digitized page scans. Extraction was validated by checking page boundaries (confirming residential listings begin on page 161) and measuring Character Error Rate (CER) and Word Error Rate (WER) against the hand-transcribed ground truth.
* **Sampling strategy:** The dataset uses a **deterministic** sampling strategy—selecting a single historical year (**1916**) and section (**residential listings**, starting at page 161) from the broader Boston City Directories collection (1780s–1980s), alongside a contiguous page sample for manual ground-truth transcription.
* **Collection vs. creation timeframe:** The digital files were harvested and processed during **Fall 2026**, whereas the underlying directory data was originally compiled and published in **1916**.

*Preprocessing / Cleaning / Labeling*

* **Preprocessing, cleaning & labeling:** Yes. Front matter (pages 1–160) and blank lines were stripped; running page headers (`BOSTON [1916] DIRECTORY`), bare page numbers, and line-end hyphens were normalized; ditto marks (`do`) were resolved to carry down surnames; 1916 shorthand/abbreviations were expanded (e.g., *Dor* $\rightarrow$ *Dorchester*); and entries were parsed into structured fields (`Surname`, `Given name`, `Occupation`, `Address`, `Residence marker`) and geocoded to latitude/longitude coordinates.
* **Transformations applied:** Unstructured OCR text streams were segmented into individual entries, split into discrete tabular columns, standardized into both as-is and normalized representations with confidence scores, and spatially joined with geocoding outputs to generate CSV and GeoJSON files.
* **Raw data storage:** Yes. Both the original Internet Archive volumes and extracted raw line files (`A-O_raw_lines.csv`) are preserved in the project's BU Spark! Google Drive folder and GitHub repository (large JP2 page scans are excluded via `.gitignore` and reproducible via the API script).
* **Preprocessing code availability:** Yes. All extraction, cleaning, normalization, and accuracy-benchmarking notebooks (`api_data_extraction_pipeline.ipynb`, `accuracy_measure_pipeline.ipynb`, and parsing scripts) are available in the designated **project GitHub repository**.

*Uses*

* **Tasks used for so far:** Benchmarking OCR engine fidelity (CER/WER), developing and validating an automated directory-parsing pipeline, and analyzing 1916 Boston occupational clustering, homeownership vs. boarding rates (`h` vs. `bds`), and suburban commuting patterns.
* **Other potential tasks:** Linking residential occupancy with historical property ownership data in the Leventhal Center's Atlascope viewer, genealogical research, longitudinal urban migration studies (when combined with other directory years), and training historical NER/OCR post-correction models.
* **Composition/cleaning impacts on future use:** Known limitations include unresolvable geocoding failures for renamed or demolished streets, residual OCR/ditto-propagation errors, and the exclusion of the 1916 business and street directory sections—meaning analyses should account for missingness rather than treating counts as a 100% exhaustive census.
* **Tasks the dataset should NOT be used for:** Modern commercial marketing/solicitation, real-time demographic or credit scoring, or drawing definitive conclusions about unlisted populations (such as non-working dependents or residents omitted by 1916 directory canvassers) without cross-referencing official census records.

*Distribution*

The underlying 1916 directory is in the public domain, and the structured dataset and pipeline are intended for public release via the Boston Public Library (Digital Commonwealth), the Leventhal Map & Education Center, and GitHub.

*Maintenance*

The open-source extraction pipeline, schema documentation, and ground-truth benchmarks are hosted on GitHub, allowing future BU Spark! teams, library technologists, or researchers to submit pull requests, adapt the parser to additional directory years or cities, and link extracted ownership layers from historical atlases.

*Other*

Both raw ("as-is") and normalized versions of key fields (occupation, address, residence type, neighborhood) are retained alongside confidence scores and Internet Archive page references so researchers can audit automated cleaning decisions directly against the original 1916 scans.

