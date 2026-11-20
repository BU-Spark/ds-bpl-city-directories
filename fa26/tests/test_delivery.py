"""Verify that the evidence and real smoke example remain traceable in Git."""

import csv
from collections import Counter
import json
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

    def test_stage3_review_artifacts_and_visual_anchors_remain_consistent(self):
        review = BASE / "quality/stage3"
        summary = read_json(review / "summary.json")
        manual = read_json(review / "manual_review.json")
        plan = read_json(review / "selection.json")
        self.assertEqual(summary["pages"], len(plan["pages"]))
        self.assertEqual(manual["reviewed_spatial_bands"], 6 * summary["pages"])
        bands = {b["region_id"]: b for b in read_json(review / "bands.json")}
        with (review / "anchors.csv").open(encoding="utf-8-sig", newline="") as handle:
            anchors = list(csv.DictReader(handle))
        self.assertEqual({r["region_id"] for r in anchors}, set(bands))
        for anchor in anchors:
            band = bands[anchor["region_id"]]
            self.assertEqual(json.loads(anchor["source_bbox"]), band["bbox"])
            self.assertEqual(json.loads(anchor["overlapping_line_ids"]), band["line_ids"])
            self.assertEqual(anchor["source_image_sha256"], band["image_sha256"])
        with (review / "line_flags.csv").open(encoding="utf-8-sig", newline="") as handle:
            flags = list(csv.DictReader(handle))
        self.assertEqual(len(flags), summary["detected_lines"])
        counts = Counter(f for row in flags for f in row["review_flags"].split("|") if f)
        self.assertEqual(dict(counts), summary["flag_counts"])
        for name, digest in read_json(review / "figure_checksums.json")["images"].items():
            self.assertEqual(sha256_file(review / "images" / name), digest)

    def test_stage4_coverage_resources_and_live_recovery_evidence_agree(self):
        folder = BASE / "quality/stage4"
        summary = read_json(folder / "summary.json")
        plan = read_json(folder / "plan.json")
        with (folder / "pages.csv").open(encoding="utf-8-sig", newline="") as handle:
            pages = list(csv.DictReader(handle))
        with (folder / "attempts.csv").open(encoding="utf-8-sig", newline="") as handle:
            attempts = list(csv.DictReader(handle))
        self.assertEqual(len(pages), 60)
        self.assertEqual([int(p["leaf_num"]) for p in pages], plan["leaves"])
        self.assertEqual(summary["page_statuses"], {"completed": 59, "quarantined": 1})
        self.assertEqual([int(p["leaf_num"]) for p in pages if p["status"] == "quarantined"], [518])
        self.assertEqual(dict(Counter(a["status"] for a in attempts)), summary["attempt_statuses"])
        self.assertEqual(sum(int(p["detected_lines"]) for p in pages), summary["captured_native_lines"])
        self.assertEqual(sum(int(p["exported_lines"]) for p in pages), summary["exported_lines"])
        self.assertAlmostEqual(sum(float(p["engine_s"]) for p in pages), summary["captured_native_engine_s"])
        self.assertTrue(all(int(p["peak_process_tree_rss_bytes"]) > 0 and int(p["tree_enumeration_failures"]) == 0 for p in pages))
        receipts = read_json(folder / "run_records.json")
        self.assertEqual(len(receipts), len(attempts))
        completed = [r["record"] for r in receipts if r["record"]["status"] == "completed"]
        self.assertEqual(len(completed), 60)
        self.assertEqual(len({r["settings_id"] for r in completed}), 1)
        proof = read_json(folder / "interruption_proof.json")
        self.assertEqual(proof["exit_code"], 130)
        self.assertTrue(proof["native_child_stopped"])
        self.assertTrue(set(proof["after_completed_run_ids"]).issubset({p["run_id"] for p in pages}))
        repeated = read_json(folder / "continuation_proof.json")
        self.assertTrue(repeated["no_new_attempts"] and repeated["completed_ids_unchanged"])
        self.assertEqual(repeated["new_native_run_directories"], 0)
        self.assertTrue(all(read_json(folder / "gate.json")["checks"].values()))
        for name, digest in read_json(folder / "checksums.json").items():
            self.assertEqual(sha256_file(folder / name), digest, name)


if __name__ == "__main__":
    unittest.main()
