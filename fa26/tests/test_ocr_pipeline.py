"""Source/output integrity tests; fake recognizers never load OCR frameworks."""
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ocr_pipeline as pipeline


class FakeRecognizer:
    def __init__(self, calls, responses=None):
        self.settings = {"model": "fake", "revision": "a" * 40, "prompt": "literal"}
        self.metadata = {"device": "fake"}
        self.calls = calls
        self.responses = iter(responses or [])
        self.closed = False

    def predict(self, image):
        self.calls.append((image.mode, image.size))
        response = next(self.responses, {"raw_text": '" John h 1 Main', "status": "completed"})
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


class PipelineIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "ocr"
        (self.root / "source").mkdir(parents=True)
        pages, lines = [], []
        for number in range(161, 168):
            image_path = self.root / "source" / f"p{number}.jpg"
            Image.new("RGB", (80, 2800), "white").save(image_path)
            pages.append({"printed_page": number, "width": 80, "height": 2800,
                          "image": f"source/p{number}.jpg", "sha256": pipeline.sha_file(image_path),
                          "source_page_url": f"https://example.org/page/{number}"})
            for i, y in enumerate((1500, 1660, 1700, 2700)):
                lines.append({"line_id": f"p{number}_{i}", "printed_page": number,
                              "bbox": [2, y, 62, y + 15]})
        self.index = {"format": pipeline.FORMAT, "pages": pages, "lines": lines,
                      "scope": "p161 lower body; other pages existing detections"}
        self.index["source_id"] = pipeline.source_identity(self.index)
        pipeline.write_json(self.root / "source/index.json", self.index)

    def read_csv(self, root=None):
        with ((root or self.root) / "results/lines.csv").open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            return reader.fieldnames, list(reader)

    def run_fake(self, engine="easyocr", responses=None, **kwargs):
        calls, factory_args, adapters = [], [], []

        def factory(name, *, device, pinned_settings, model_cache):
            factory_args.append({"engine": name, "device": device,
                                 "pinned_settings": pinned_settings, "model_cache": model_cache})
            adapter = FakeRecognizer(calls, responses)
            adapters.append(adapter)
            return adapter

        summary = pipeline.run_ocr(self.root, engine, adapter_factory=factory, **kwargs)
        return calls, factory_args, adapters, summary

    def save_records(self, engine, records, metadata=None):
        path = self.root / "results/raw" / (engine + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        if metadata is not None:
            pipeline.write_json(self.root / "results/models.json", {engine: metadata})
        return path

    def record(self, row, text="original", status="completed", legacy=False):
        value = {"line_id": row["line_id"], "bbox": row["bbox"], "raw_text": text,
                 "raw_text_sha256": pipeline.sha_text(text), "status": status}
        if not legacy:
            value["input_id"] = pipeline.line_identity(self.index, row)
        return value

    def test_common_source_scope_and_exact_output_columns(self):
        loaded = pipeline.load_sources(self.root)
        self.assertEqual(loaded, self.index)
        visible = pipeline.visible_lines(loaded)
        self.assertEqual(len(visible), 26)
        self.assertEqual([r["line_id"] for r in visible if r["printed_page"] == 161], ["p161_1", "p161_2"])
        pipeline.export_lines(self.root)
        fields, rows = self.read_csv()
        self.assertEqual(fields, ["tesseract_text", "mocr_text", "easyocr_text", "paddleocr_text", "qwen_text", "sources"])
        self.assertEqual(len(rows), len(visible))
        self.assertTrue(all(not r[field] for r in rows for field in fields[:-1]))
        self.assertEqual(rows[0]["sources"], "https://example.org/page/161")

    def test_only_images_enter_recognizer_and_problem_outputs_remain(self):
        literal = '"  John\nh at Atlantic'
        responses = [{"raw_text": literal, "status": "completed"},
                     {"raw_text": "", "status": "empty"},
                     {"raw_text": "partial", "status": "truncated"},
                     ValueError("recognizer failed")]
        calls, factory_args, adapters, summary = self.run_fake(responses=responses, max_new_lines=4)
        self.assertEqual(calls, [("RGB", (60, 15))] * 4)
        self.assertEqual(set(factory_args[0]), {"engine", "device", "pinned_settings", "model_cache"})
        self.assertTrue(adapters[0].closed)
        self.assertEqual(summary["new_lines"], 4)
        records = pipeline.read_predictions(self.root, self.index, "easyocr")
        first_id = pipeline.visible_lines(self.index)[0]["line_id"]
        self.assertEqual(records[first_id]["raw_text"], literal)
        _, rows = self.read_csv()
        self.assertEqual(len(rows), 26)
        self.assertEqual([r["easyocr_text"] for r in rows[:4]], ['" John h at Atlantic', "", "partial", ""])
        statuses = json.loads((self.root / "results/status.json").read_text())["models"]["easyocr"]
        self.assertEqual({k: statuses[k] for k in ("completed", "empty", "truncated", "failed", "not_run")},
                         {"completed": 1, "empty": 1, "truncated": 1, "failed": 1, "not_run": 22})

    def test_resume_skips_completed_preserves_settings_and_force_appends(self):
        first, _, _, _ = self.run_fake(max_new_lines=2)
        self.assertEqual(len(first), 2)
        second, factory_args, _, _ = self.run_fake(max_new_lines=1)
        self.assertEqual(len(second), 1)
        self.assertEqual(factory_args[0]["pinned_settings"]["revision"], "a" * 40)
        self.run_fake(max_new_lines=None)
        calls, factories, _, summary = self.run_fake(max_new_lines=None)
        self.assertEqual((calls, factories, summary["new_lines"]), ([], [], 0))
        path = self.root / "results/raw/easyocr.jsonl"
        self.assertEqual(len(pipeline.read_jsonl(path)), 26)
        calls, _, _, summary = self.run_fake(max_new_lines=2, force=True)
        self.assertEqual((len(calls), summary["new_lines"]), (2, 2))
        self.assertEqual(len(pipeline.read_jsonl(path)), 28)
        self.assertEqual(len(pipeline.read_predictions(self.root, self.index, "easyocr")), 26)

    def test_preserved_legacy_mocr_requires_matching_source_and_box(self):
        row = pipeline.visible_lines(self.index)[0]
        record = self.record(row, text='" original mOCR', legacy=True)
        metadata = {"imported_source_id": self.index["source_id"]}
        self.save_records("dots_mocr", [record], metadata)
        predictions = pipeline.read_predictions(self.root, self.index, "dots_mocr")
        self.assertEqual(predictions[row["line_id"]]["raw_text"], '" original mOCR')
        pipeline.export_lines(self.root)
        _, rows = self.read_csv()
        self.assertEqual(rows[0]["mocr_text"], '" original mOCR')
        self.save_records("dots_mocr", [record], {"imported_source_id": "different source"})
        self.assertEqual(pipeline.read_predictions(self.root, self.index, "dots_mocr"), {})
        record["bbox"] = [1, 2, 3, 4]
        self.save_records("dots_mocr", [record], metadata)
        self.assertEqual(pipeline.read_predictions(self.root, self.index, "dots_mocr"), {})

    def test_corrupt_raw_text_and_incompatible_input_are_not_reused(self):
        first, second = pipeline.visible_lines(self.index)[:2]
        altered = self.record(first)
        altered["raw_text"] = "changed without updating checksum"
        wrong_input = self.record(second)
        wrong_input["input_id"] = "incompatible source geometry"
        path = self.save_records("easyocr", [altered, wrong_input])
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"unfinished":')
        self.assertEqual(pipeline.read_predictions(self.root, self.index, "easyocr"), {})
        calls, _, _, _ = self.run_fake(max_new_lines=1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(pipeline.read_predictions(self.root, self.index, "easyocr")), 1)

    def test_changed_source_bytes_or_geometry_are_rejected(self):
        path = self.root / "source/index.json"
        self.index["lines"][0]["bbox"][2] += 1
        pipeline.write_json(path, self.index)
        with self.assertRaisesRegex(ValueError, "geometry changed"):
            pipeline.load_sources(self.root)
        self.index["lines"][0]["bbox"][2] -= 1
        pipeline.write_json(path, self.index)
        Image.new("RGB", (80, 2800), "black").save(self.root / "source/p161.jpg")
        with self.assertRaisesRegex(ValueError, "Source image changed"):
            self.run_fake(max_new_lines=1)
        with self.assertRaisesRegex(ValueError, "Source image changed"):
            pipeline.export_lines(self.root)

    def test_zip_roundtrip_has_seven_sources_and_no_line_crop_files(self):
        self.run_fake(max_new_lines=2)
        archive = pipeline.pack_bundle(self.root, self.base / "transfer.zip")
        with zipfile.ZipFile(archive) as bundle:
            files = [name for name in bundle.namelist() if not name.endswith("/")]
            self.assertEqual(sorted(n for n in files if n.endswith(".jpg")), [f"source/p{n}.jpg" for n in range(161, 168)])
            self.assertFalse(any(n.endswith(".png") for n in files))
        restored = self.base / "restored"
        imported = pipeline.import_bundle(archive, restored)
        self.assertEqual(imported, self.index)
        self.assertEqual(self.read_csv(), self.read_csv(restored))
        for page in self.index["pages"]:
            self.assertEqual(pipeline.sha_file(restored / page["image"]), page["sha256"])
        self.assertEqual(len(pipeline.read_predictions(restored, imported, "easyocr")), 2)

    def test_out_of_memory_stops_without_losing_rows_or_raw_response(self):
        calls, _, adapters, summary = self.run_fake(responses=[RuntimeError("CUDA out of memory")], max_new_lines=None)
        self.assertEqual((len(calls), summary["new_lines"]), (1, 1))
        self.assertTrue(adapters[0].closed)
        records = pipeline.read_predictions(self.root, self.index, "easyocr")
        self.assertEqual(next(iter(records.values()))["status"], "out_of_memory")
        _, rows = self.read_csv()
        self.assertEqual(len(rows), 26)


if __name__ == "__main__":
    unittest.main()
