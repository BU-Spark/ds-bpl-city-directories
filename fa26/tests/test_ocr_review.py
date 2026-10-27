"""Checks for OCR line provenance, comparable regions and human-only scoring."""
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ocr_review as review


def word(text, box, native):
    return {"text": text, "bbox": box, "native_id": native, "confidence": 0.0}


class NativeLineTest(unittest.TestCase):
    def test_tall_word_stays_on_its_native_line(self):
        words = [word("AA", [77, 1664, 131, 1683], "1:22:1:1:1"),
                 word("wire", [146, 1663, 209, 1705], "1:22:1:1:2"),
                 word("Co", [222, 1662, 258, 1682], "1:22:1:1:3"),
                 word("next", [77, 1688, 131, 1708], "1:22:1:2:1")]
        lines = review.native_tesseract_lines(words)
        self.assertEqual([line["text"] for line in lines], ["AA wire Co", "next"])

    def test_native_id_never_merges_columns(self):
        lines = review.native_tesseract_lines([
            word("Left", [80, 1660, 150, 1680], "1:1:1:1:1"),
            word("Right", [800, 1660, 870, 1680], "1:1:1:1:2")])
        self.assertEqual([(line["column"], line["text"]) for line in lines], [("L", "Left"), ("R", "Right")])

    def test_tsv_offsets_and_zero_confidence_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "raw.tsv"
            path.write_text("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
                            "5\t1\t1\t1\t1\t1\t45\t406\t80\t23\t0\tGiuseppe\n")
            words = review.parse_tsv(path, (760, 1645))
            self.assertEqual(words[0]["bbox"], [805, 2051, 885, 2074])
            self.assertEqual(words[0]["confidence"], 0.0)


class HumanScoringTest(unittest.TestCase):
    def setUp(self):
        self.manifest = {"units_sha256": "manifest", "review_units": [
            {"unit_id": "one", "image_sha256": "image-one"},
            {"unit_id": "two", "image_sha256": "image-two"}]}
        self.reviews = {
            "one": {"unit_id": "one", "review_status": "verified", "reviewer": "Reviewer", "gold_text": "568"},
            "two": {"unit_id": "two", "review_status": "pending", "reviewer": "", "gold_text": "Do not score"}}
        self.predictions = [
            {"unit_id": "one", "method": "ia_existing", "unit_image_sha256": "image-one", "text": "668", "status": "completed"},
            {"unit_id": "two", "method": "ia_existing", "unit_image_sha256": "image-two", "text": "", "status": "completed"},
            {"unit_id": "one", "method": "tesseract_units", "unit_image_sha256": "image-one", "text": "568", "status": "completed"}]

    def test_each_method_is_scored_against_the_same_human_reference(self):
        scores = {row["method"]: row for row in review.score_verified(self.reviews, self.predictions, self.manifest)}
        self.assertAlmostEqual(scores["ia_existing"]["CER"], 1/3)
        self.assertEqual(scores["tesseract_units"]["CER"], 0)
        self.assertEqual(scores["ia_existing"]["verified_units"], 1)

    def test_missing_prediction_is_not_dropped(self):
        self.reviews["two"] = {"unit_id": "two", "review_status": "verified", "reviewer": "Reviewer", "gold_text": "abc"}
        scores = {row["method"]: row for row in review.score_verified(self.reviews, self.predictions, self.manifest)}
        self.assertEqual(scores["tesseract_units"]["verified_units"], 2)
        self.assertEqual(scores["tesseract_units"]["failed_or_missing_units"], 1)
        self.assertEqual(scores["tesseract_units"]["CER"], 0.5)

    def test_pending_has_no_accuracy_score(self):
        self.reviews["one"]["review_status"] = "pending"
        scores = review.score_verified(self.reviews, self.predictions, self.manifest)
        self.assertTrue(all(row["CER"] is None and row["verified_units"] == 0 for row in scores))

    def test_wrong_region_or_duplicate_prediction_is_rejected(self):
        with self.assertRaises(ValueError):
            review.validate_predictions(self.predictions + [self.predictions[0]], self.manifest)
        self.predictions[0]["unit_image_sha256"] = "wrong"
        with self.assertRaises(ValueError):
            review.validate_predictions(self.predictions, self.manifest)


class RegionsAndReviewTest(unittest.TestCase):
    def test_regions_tile_source_and_png_compression_does_not_change_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "source").mkdir()
            image = Image.new("RGB", (1680, 2799), "white")
            draw = ImageDraw.Draw(image)
            for y in range(1662, 2670, 23):
                draw.rectangle([80, y, 600, y+12], fill="black")
                draw.rectangle([800, y, 1400, y+12], fill="black")
            image.save(root / "source" / review.IMAGE_NAME)
            manifest = review.make_units(root)
            self.assertEqual(len(manifest["review_units"]), 12)
            with Image.open(root / "source" / review.IMAGE_NAME) as source:
                for column in ["L", "R"]:
                    units = [u for u in manifest["review_units"] if u["column"] == column]
                    self.assertEqual(units[0]["bbox"][1], review.BODY_TOP)
                    self.assertEqual(units[-1]["bbox"][3], review.BODY_BOTTOM)
                    for a, b in zip(units, units[1:]):
                        self.assertEqual(a["bbox"][3], b["bbox"][1])
                    for unit in units:
                        with Image.open(root / unit["image"]) as crop:
                            self.assertEqual(crop.tobytes(), source.crop(unit["bbox"]).tobytes())
            unit = manifest["review_units"][0]
            path = root / unit["image"]
            before = review.image_digest(path)
            with Image.open(path) as crop:
                crop.save(root / "different_encoder.png", compress_level=0)
            self.assertEqual(before, review.image_digest(root / "different_encoder.png"))

    def test_human_input_survives_report_rebuild_and_import(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "inputs").mkdir()
            image = root / "inputs/one.png"
            Image.new("RGB", (20, 20), "white").save(image)
            manifest = {"units_sha256": "manifest", "review_units": [
                {"unit_id": "one", "image_sha256": review.image_digest(image),
                 "image": "inputs/one.png", "bbox": [0, 0, 20, 20]}]}
            prediction = {"unit_id": "one", "unit_image_sha256": review.image_digest(image),
                          "method": "ia_existing", "input_mode": "test", "text": "668", "status": "completed"}
            review.build_review(root, manifest, [prediction])
            rows = review.read_csv(root / "manual_review.csv")
            rows[0].update(gold_text='568, quote " and\nline break', reviewer="Reviewer", review_status="verified")
            review.write_csv(root / "manual_review.csv", rows, review.REVIEW_FIELDS)
            review.build_review(root, manifest, [prediction])
            self.assertEqual(review.read_csv(root / "manual_review.csv")[0]["gold_text"], rows[0]["gold_text"])
            self.assertIn("668", (root / "predictions.csv").read_text())
            self.assertTrue((root / "review.html").exists())


if __name__ == "__main__":
    unittest.main()
