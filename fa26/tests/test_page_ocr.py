"""Meaningful I/O, geometry and failed-run guarantees using tiny local fixtures."""

import csv
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from bpl_ocr.engine import parse_tsv
from bpl_ocr.io import load_config, read_json, sha256_file, write_json
from bpl_ocr.manifest import load_manifest
from bpl_ocr.pipeline import fetch_page, recognize_page

BASE = Path(__file__).resolve().parents[1]
HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"


class PageOcrTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.config = load_config(BASE / "config/vol1.json")
        self.page = next(p for p in load_manifest(BASE / "manifests/vol1/manifest.json")["pages"] if p["leaf_num"] == 164)

    def test_native_column_order_literal_ditto_and_inverse_coordinates(self):
        path = self.work / "input.tsv"
        # The second line is at the top of a second column. Sorting by y would
        # break native reading order. An opening quote must not consume rows.
        path.write_text(HEADER +
                        '5\t1\t1\t1\t1\t1\t30\t210\t10\t20\t80\t"\n' +
                        '5\t1\t1\t1\t1\t2\t50\t210\t60\t20\t90\tJohn\n' +
                        '5\t1\t2\t1\t1\t1\t1810\t30\t60\t20\t70\tRight\n')
        rows = parse_tsv(path, self.page, image_sha256="a" * 64, settings_id="b" * 64, config=self.config)
        self.assertEqual([r["text"] for r in rows], ['" John', 'Right'])
        self.assertEqual([rows[0][k] for k in ("x0", "y0", "x1", "y1")], [10, 100, 50, 110])
        self.assertEqual(rows[0]["mean_word_confidence"], 85)
        self.assertEqual(rows[1]["reading_order"], 2)
        self.assertNotEqual(rows[0]["line_id"], rows[1]["line_id"])

    def test_malformed_tsv_is_not_silently_exported(self):
        path = self.work / "bad.tsv"
        path.write_text("text\nhello\n")
        with self.assertRaisesRegex(ValueError, "required columns"):
            parse_tsv(path, self.page, image_sha256="a", settings_id="b", config=self.config)

    def test_source_cache_rejects_changed_bytes(self):
        page = {**self.page, "expected_width": 80, "expected_height": 100}
        folder = self.work / "source" / page["volume_id"]
        folder.mkdir(parents=True)
        image = folder / "leaf0164.jpg"
        Image.new("RGB", (80, 100), "white").save(image)
        write_json(image.with_suffix(".json"), {"source_image_url": page["source_image_url"], "sha256": sha256_file(image)})
        _, _, cached = fetch_page(page, self.work)
        self.assertTrue(cached)
        Image.new("RGB", (80, 100), "black").save(image)
        with self.assertRaisesRegex(ValueError, "provenance validation"):
            fetch_page(page, self.work)

    def test_excluded_advertisement_does_not_start_an_engine_or_make_a_run(self):
        with patch("bpl_ocr.pipeline.inspect_engine") as engine:
            with self.assertRaisesRegex(ValueError, "outside the declared OCR scope"):
                recognize_page(BASE / "manifests/vol1/manifest.json", 781, self.work)
            engine.assert_not_called()
        self.assertFalse((self.work / "runs").exists())

    def test_engine_failure_keeps_stderr_and_failed_provenance(self):
        image = self.work / "fake.jpg"
        Image.new("RGB", (80, 100), "white").save(image)
        response = subprocess.CompletedProcess([], 1, b"", b"failed native process")
        with patch("bpl_ocr.pipeline.inspect_engine", return_value={"binary": "fake", "version_text": "tesseract 5.3.4"}), \
             patch("bpl_ocr.pipeline.prepare_model", return_value=self.work), \
             patch("bpl_ocr.pipeline.fetch_page", return_value=(image, {"sha256": sha256_file(image)}, True)), \
             patch("bpl_ocr.pipeline.run_tesseract", return_value=(response, ["fake"] * 8)):
            with self.assertRaisesRegex(RuntimeError, "failed native process"):
                recognize_page(BASE / "manifests/vol1/manifest.json", 164, self.work)
        records = list((self.work / "runs").rglob("run.json"))
        self.assertEqual(len(records), 1)
        record = read_json(records[0])
        self.assertEqual(record["status"], "failed")
        self.assertIn("finished_at_utc", record)
        self.assertEqual((records[0].parent / "raw/stderr.txt").read_bytes(), b"failed native process")
        self.assertFalse((records[0].parent / "lines.csv").exists())


if __name__ == "__main__":
    unittest.main()
