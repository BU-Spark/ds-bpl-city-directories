## Selected Tesseract OCR

For the fixed 1916 general-directory capture jobs, use [the OCR runner](ocr/README.md).
It has a pinned environment, 14 Volume-1 batches, six Volume-2 batches and a
separate four-page Volume-2 validation entry point. Existing notebooks and
ground-truth files keep their current setup. Run validation before production.


<h1 align="center">
  <br>
  <a href="https://www.bu.edu/spark/" target="_blank"><img src="https://www.bu.edu/spark/files/2023/08/logo.png" alt="BUSpark" width="200"></a>
  <br>
  Project README Template <change to project name>
  <br>
</h1>

<h4 align="center">A template for the project readme file. </h4> <change to repo short description>

<p align="center">
  <a href="#key-features">Key Features</a> •
  <a href="#how-to-use">How To Use</a> •
  <a href="#project-description">Project Description</a> •
  <a href="#data-locations">Data Locations</a>
</p>

## Key Features
In this section you will be including a list of key features of your code/project.

You should also include a short description of what each part of your code does. (Detailed description in the readme of each directory, if applicable)
* fa26/scripts/api_data_extraction_pipeline.ipynb
  - Connects to the Internet Archive API to download raw OCR text and page images for the directory.
  - Configuration: Currently targets the 1916 A–O volume, though the identifier can be swapped for any volume.
  - Text Processing: Trims front matter to start at page 161 (where residential listings begin), strips blank lines/whitespace, and exports the cleaned text as A-O_raw_lines.csv.
  - Image Handling: Downloads page scans locally. Because of file size limits, images are excluded via .gitignore (run locally as needed or configure Git LFS before pushing to GitHub).
* fa26/scripts/accuracy_measure_pipeline.ipynb
  - Measures how faithfully each OCR engine reproduces hand-transcribed ground truth (GT), independent of line breaks. Both texts are normalized into word streams (removing page headers, joining hyphenated line breaks, and unifying ditto marks) and aligned via word-level edit distance—ignoring trailing OCR text past the GT boundary.
* /path/to/script - function and description
  - Key notes
 
## How To Use

To clone and run this application, you'll need <a href="https://git-scm.com" target="_blank">Git</a>
From your command line:

```bash
# Clone this repository
$ git clone [repo link]

# Further Instructions
...
```

Create a new branch from dev, add changes on the new branch you just created.

You will want to look into <a href="https://git-scm.com/docs/git-branch" target="_blank">git branch</a> and <a href="https://git-scm.com/docs/git-checkout" target="_blank">git checkout</a>

```bash
# Create and Checkout a new branch if it doesn't exist
$ git checkout -b your-branch main
...
```
 
## Project Description

Boston city directories are annual volumes listing the city's residents and businesses published from the late 1700s through the 1980s. While the scope and detail of directories entries is variable across years and publishers, a single entry typically consists of a name, address, and occupation, with the occasional inclusion of other information, such as recent moves or work versus home addresses. The original data makes heavy use of abbreviations and shorthand text. These directories are heavily used research tools in BPL’s collection, functioning as a kind of annual city census of residents and businesses. The volumes are digitized and publicly available through the Internet Archive, but their contents exist only as unstructured OCR text: searchable as a wall of words, and not usable as data.
This project will convert the 1916 Boston Directory into a structured, geocoded dataset. Students will extract individual entries from the digitized text, parse them into discrete fields, geocode the addresses, and analyze what the resulting dataset reveals about occupational and residential patterns in 1916 Boston. The output is intended to be loadable as a geographic layer alongside the Leventhal Center's historical map tools — where the atlases record who owned property and the directories record who actually lived there, a comparison neither source supports alone. The client has confirmed that the structured dataset is the primary goal for this semester; a reusable extraction model for other years or cities is a valuable future direction, not a deliverable here.

## Data locations


<a href="dataset-documentation">Dataset Documentation</a>
* Location 1: fa26/data/1916 Boston Directory Vol. 1 (A–O)
  - The text file recieved from API call to Internet Archive. OCR'd text by the Interent Archive. 
* Location 2: fa26/data/ground_truth
  - Ground truth datasets manually transcriped from the original documents availble on the Internet Archive.
  
