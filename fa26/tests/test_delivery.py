"""Verify that the evidence and real smoke example remain traceable in Git."""

import csv
from pathlib import Path
import unittest

from bpl_ocr.io import read_json, sha256_file
from bpl_ocr.manifest import load_manifest

BASE = Path(__file__).resolve().parents[1]


class DeliveryTest(unittest.TestCase):
    def test_historical_comparison_evidence_is_unchanged(self):
        archive = BASE / "archive/model_comparison"
        for name, expected in read_json(archive / "checksums.json").items():
            self.assertEqual(sha256_file(archive / name), expected, name)

    def test_saved_real_run_matches_native_outputs_and_current_source_manifest(self):
        example = BASE / "examples/leaf0164"
        record = read_json(example / "run.json")
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["manifest_id"], load_manifest(BASE / "manifests/vol1/manifest.json")["manifest_id"])
        for name, expected in record["outputs"].items():
            self.assertEqual(sha256_file(example / name), expected, name)
        self.assertEqual(sha256_file(BASE / "archive/model_comparison/source/p162.jpg"), record["source"]["sha256"])
        with (example / "lines.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), record["detected_lines"])
        self.assertEqual(len({r["line_id"] for r in rows}), len(rows))
        for row in rows:
            self.assertEqual(row["settings_id"], record["settings_id"])
            self.assertTrue(0 <= float(row["x0"]) <= float(row["x1"]) <= record["source"]["width"])
            self.assertTrue(0 <= float(row["y0"]) <= float(row["y1"]) <= record["source"]["height"])


if __name__ == "__main__":
    unittest.main()
