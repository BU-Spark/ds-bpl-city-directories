"""Cross-page review safeguards, including asymmetric scans and non-destructive flags."""

from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import unittest

from bpl_ocr.io import read_json, write_json
from bpl_ocr.manifest import load_manifest
from bpl_ocr.quality import build_review, column_geometry, line_diagnostics, verify_run

BASE = Path(__file__).resolve().parents[1]


def row(number, x, y, text="A substantive physical text line", width=520, height=22, words=6):
    return {"line_id": f"test-{number}", "reading_order": number, "x0": x, "y0": y,
            "x1": x + width, "y1": y + height, "word_count": words,
            "mean_word_confidence": 80, "text": text}


class QualityTest(unittest.TestCase):
    def setUp(self):
        manifest = load_manifest(BASE / "manifests/vol1/manifest.json")
        self.manifest = manifest
        self.page = next(p for p in manifest["pages"] if p["leaf_num"] == 164)

    def test_asymmetric_scan_uses_text_starts_rather_than_image_midpoint(self):
        rows = [row(i + 1, 260, 200 + i * 30, width=650) for i in range(5)]
        rows += [row(i + 6, 1000, 200 + i * 30, width=600) for i in range(5)]
        geometry = column_geometry(rows, 1700, (100, 2700))
        self.assertEqual(geometry["status"], "two_start_clusters")
        self.assertGreater(geometry["gutter_x"], 900)
        self.assertLess(geometry["gutter_x"], 1000)

    def test_single_cluster_does_not_claim_two_verified_columns(self):
        rows = [row(i + 1, 200, 200 + i * 30) for i in range(8)]
        self.assertEqual(column_geometry(rows, 1700, (100, 2700))["status"], "unresolved")

    def test_merged_full_width_rows_cannot_move_gutter_inside_right_column(self):
        rows = [row(i + 1, 260, 200 + i * 30, width=650) for i in range(5)]
        rows += [row(i + 6, 1000, 200 + i * 30, width=600) for i in range(5)]
        rows += [row(i + 11, 260, 500 + i * 30, width=1300) for i in range(20)]
        geometry = column_geometry(rows, 1700, (100, 2700))
        self.assertEqual(geometry["status"], "two_start_clusters")
        self.assertLess(geometry["gutter_x"], 1000)
        self.assertGreater(geometry["gutter_x"], 900)
        flags, counts, _ = line_diagnostics(rows, self.page, geometry)
        self.assertEqual(counts["cross_gutter_candidate"], 20)
        self.assertNotIn("cross_gutter_candidate", flags[5]["review_flags"])

    def test_symbol_flags_keep_short_continuations_and_do_not_edit_text(self):
        rows = [row(1, 260, 200), row(2, 260, 240), row(3, 240, 300, "RR RER", width=10, height=180, words=2),
                row(4, 290, 280, "Dor", width=35, height=20, words=1)]
        original = deepcopy(rows)
        flags, counts, _ = line_diagnostics(rows, self.page, {"gutter_x": 950})
        self.assertIn("vertical_symbol_candidate", flags[2]["review_flags"])
        self.assertNotIn("vertical_symbol_candidate", flags[3]["review_flags"])
        self.assertEqual(len(flags), len(rows))
        self.assertEqual(rows, original)

    def test_native_order_backtrack_is_flagged_and_header_is_separate(self):
        rows = [row(1, 260, 500), row(2, 260, 200),
                row(3, 500, 60, "BOSTON [1916] DIRECTORY", width=650), row(4, 1000, 200)]
        flags, counts, segments = line_diagnostics(rows, self.page, {"gutter_x": 950})
        self.assertIn("order_backtrack_candidate", flags[1]["review_flags"])
        self.assertIn("header_candidate", flags[2]["review_flags"])
        self.assertEqual(segments, "LR")
        self.assertEqual([r["native_reading_order"] for r in flags], [1, 2, 3, 4])

    def test_changed_native_output_or_settings_cannot_be_certified(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "run"
            shutil.copytree(BASE / "examples/leaf0164", folder)
            with (folder / "raw/page.txt").open("a") as handle:
                handle.write("changed")
            with self.assertRaisesRegex(ValueError, "Changed OCR output"):
                verify_run(folder, self.manifest)
            shutil.copyfile(BASE / "examples/leaf0164/raw/page.txt", folder / "raw/page.txt")
            record = read_json(folder / "run.json")
            record["settings"]["psm"] = 7
            write_json(folder / "run.json", record)
            with self.assertRaisesRegex(ValueError, "settings identity changed"):
                verify_run(folder, self.manifest)

    def test_duplicate_or_incomplete_sample_does_not_produce_final_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = {"plan": {"manifest_id": self.manifest["manifest_id"], "pages": [{"leaf_num": 164}]},
                     "runs": [{"leaf_num": 164, "status": "failed"}]}
            write_json(root / "index.json", index)
            with self.assertRaisesRegex(ValueError, "Pilot is incomplete"):
                build_review(root / "index.json", BASE / "manifests/vol1/manifest.json", root / "review")
            self.assertFalse((root / "review/summary.json").exists())
            index["plan"]["pages"].append({"leaf_num": 164})
            write_json(root / "index.json", index)
            with self.assertRaisesRegex(ValueError, "duplicate leaves"):
                build_review(root / "index.json", BASE / "manifests/vol1/manifest.json", root / "review")


if __name__ == "__main__":
    unittest.main()
