"""Fresh-run measurement integrity tests; no OCR frameworks or weights are used."""
import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zipfile

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ocr_pipeline as pipeline
import ocr_efficiency as efficiency


class FakeMonitor:
    def __init__(self, device, engine):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True
        return self

    def stop(self):
        self.stopped = True
        return {"cpu_utilization_percent_one_core": 75.0,
                "peak_process_tree_rss_bytes_sampled": 64 * 1024**2,
                "gpu_peak_used_bytes_sampled": None,
                "gpu_utilization_percent_mean_sampled": None,
                "gpu_monitor_status": "not_used_cpu"}


class FakeCuda:
    def __init__(self, events):
        self.events = events

    def synchronize(self):
        self.events.append("sync")

    def reset_peak_memory_stats(self):
        self.events.append("reset_memory")

    def memory_allocated(self):
        return 2 * 1024**2

    def max_memory_allocated(self):
        return 3 * 1024**2

    def memory_reserved(self):
        return 4 * 1024**2

    def max_memory_reserved(self):
        return 5 * 1024**2


class FakeRecognizer:
    def __init__(self, engine, device, calls, events, responses=None):
        self.engine, self.device = engine, device
        self.gpu = device.startswith("cuda")
        self.settings = {"model": "fake-" + engine, "revision": "a" * 40}
        self.metadata = {"actual_device": device}
        self.calls, self.events = calls, events
        self.responses = iter(responses or [])
        self.closed = False
        self.framework = SimpleNamespace(cuda=FakeCuda(events)) if self.gpu else None

    def predict(self, image):
        self.calls.append((image.mode, image.size))
        self.events.append("predict")
        result = next(self.responses, {"raw_text": '"  Fresh OCR\nline', "status": "completed"})
        if isinstance(result, BaseException):
            raise result
        return result

    def close(self):
        self.closed = True


class EfficiencyIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "ocr"
        (self.root / "source").mkdir(parents=True)
        pages, lines = [], []
        for number in range(161, 168):
            image_path = self.root / "source" / f"p{number}.jpg"
            Image.new("RGB", (80, 2800), "white").save(image_path)
            pages.append({"printed_page": number, "width": 80, "height": 2800,
                          "image": f"source/p{number}.jpg", "sha256": pipeline.sha_file(image_path),
                          "source_page_url": f"https://example.org/page/{number}"})
            for order, y in enumerate((1500, 1660, 1700, 2700)):
                lines.append({"line_id": f"p{number}_{order}", "printed_page": number,
                              "bbox": [2, y, 62, y + 15]})
        self.index = {"format": pipeline.FORMAT, "pages": pages, "lines": lines,
                      "scope": "p161 directory body; other pages all detected lines"}
        self.index["source_id"] = pipeline.source_identity(self.index)
        pipeline.write_json(self.root / "source/index.json", self.index)
        (self.root / "results/raw").mkdir(parents=True)
        original_settings = {"model": "preserved old model", "revision": "b" * 40}
        pipeline.write_json(self.root / "results/models.json", {
            "easyocr": {"active_settings_id": "old", "settings_history": {"old": original_settings}}})
        with (self.root / "results/raw/easyocr.jsonl").open("w", encoding="utf-8") as handle:
            for row in pipeline.visible_lines(self.index):
                record = {"line_id": row["line_id"], "bbox": row["bbox"],
                          "input_id": pipeline.line_identity(self.index, row),
                          "raw_text": "Existing completed answer", "status": "completed",
                          "raw_text_sha256": pipeline.sha_text("Existing completed answer"), "settings_id": "old"}
                handle.write(json.dumps(record) + "\n")
        pipeline.export_lines(self.root, self.index)
        # Preserve exact bytes, including a value which the old importer would rewrite.
        with (self.root / "results/lines.csv").open("ab") as handle:
            handle.write(b"\n")
        self.original_hashes = self.hashes(self.root)

    @staticmethod
    def hashes(root, names=("source", "results")):
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for name in names for p in (root / name).rglob("*") if p.is_file()}

    def run_fake(self, *, engine="easyocr", device="cpu", responses=None, **kwargs):
        calls, events, factories, adapters, monitors = [], [], [], [], []

        def factory(name, *, device, pinned_settings, model_cache):
            factories.append({"engine": name, "device": device, "pinned_settings": pinned_settings,
                              "model_cache": model_cache})
            adapter = FakeRecognizer(name, device, calls, events, responses)
            adapters.append(adapter)
            return adapter

        def monitor_factory(device, engine):
            monitor = FakeMonitor(device, engine)
            monitors.append(monitor)
            return monitor

        metric = efficiency.run_efficiency(self.root, engine, device=device,
            adapter_factory=factory, monitor_factory=monitor_factory, **kwargs)
        return metric, calls, events, factories, adapters, monitors

    def summary(self):
        with (self.root / "efficiency/summary.csv").open(encoding="utf-8-sig", newline="") as handle:
            return {row["model"]: row for row in csv.DictReader(handle)}

    def run_directory(self, metric):
        return self.root / "efficiency/runs" / metric["engine"] / metric["run_id"]

    def test_old_answers_never_replace_fresh_measurement_and_warmup_is_excluded(self):
        metric, calls, _, factories, adapters, monitors = self.run_fake(setup_seconds=2, import_seconds=3)
        self.assertEqual(len(calls), 27)  # 26 visible lines plus one discarded warmup.
        self.assertEqual(metric["measured_lines"], 26)
        self.assertEqual(metric["requested_lines"], 26)
        self.assertEqual(metric["run_status"], "complete")
        self.assertTrue(metric["comparison_eligible"])
        self.assertEqual(factories[0]["pinned_settings"]["revision"], "b" * 40)
        self.assertTrue(all(call == ("RGB", (60, 15)) for call in calls))
        raw = pipeline.read_jsonl(self.run_directory(metric) / "raw.jsonl")
        self.assertEqual(len(raw), 26)
        self.assertTrue(all(r["raw_text"] == '"  Fresh OCR\nline' for r in raw))
        self.assertTrue(all(r["request_seconds"] >= 0 for r in raw))
        self.assertEqual(metric["output_statuses"], {"completed": 26})
        self.assertEqual(metric["setup_seconds"], 2)
        self.assertTrue(adapters[0].closed and monitors[0].started and monitors[0].stopped)
        self.assertEqual(self.hashes(self.root), self.original_hashes)

    def test_same_full_sample_for_five_engines_and_all_summary_rows(self):
        protocols, sample_ids = [], []
        for engine in pipeline.ENGINES:
            metric, *_ = self.run_fake(engine=engine, warmup_lines=0)
            protocols.append(metric["protocol_id"])
            records = pipeline.read_jsonl(self.run_directory(metric) / "raw.jsonl")
            sample_ids.append([r["line_id"] for r in records])
        self.assertEqual(len(set(protocols)), 1)
        self.assertTrue(all(ids == sample_ids[0] for ids in sample_ids))
        summary = self.summary()
        self.assertEqual(list(summary), list(pipeline.ENGINES))
        self.assertTrue(all(r["run_status"] == "complete" for r in summary.values()))
        self.assertEqual(self.hashes(self.root), self.original_hashes)

    def test_smoke_sample_has_own_protocol_and_no_page_projection(self):
        metric, calls, *_ = self.run_fake(line_limit=6)
        self.assertEqual(len(calls), 7)
        self.assertEqual(metric["run_status"], "smoke_complete")
        self.assertFalse(metric["full_scope"])
        self.assertIsNone(metric["mean_seconds_per_page_scope"])
        self.assertIsNone(metric["page_scopes_per_hour"])
        row = self.summary()["easyocr"]
        self.assertEqual((row["mean_s_per_page"], row["pages_per_hour"]), ("", ""))
        full, _ = efficiency.measurement_protocol(self.index)
        self.assertNotEqual(metric["protocol_id"], full["protocol_id"])

    def test_unmeasured_models_and_unavailable_gpu_are_blank_not_zero(self):
        metric, *_ = self.run_fake(line_limit=2, warmup_lines=0)
        rows = self.summary()
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows["paddleocr"]["run_status"], "not_measured")
        self.assertEqual(rows["paddleocr"]["processing_s"], "")
        self.assertEqual(rows["easyocr"]["peak_ram_mib"], "64.0")
        self.assertEqual(rows["easyocr"]["mean_cpu_pct"], "75.0")
        for key in ("mean_gpu_pct", "peak_vram_allocated_mib", "gpu_device_peak_mib"):
            self.assertEqual(rows["easyocr"][key], "")
        self.assertIsNone(metric["framework_memory"]["gpu_peak_allocated_mib"])

    def test_gpu_requests_are_synchronized_and_allocator_peak_retained(self):
        metric, calls, events, *_ = self.run_fake(device="cuda:0", line_limit=2, warmup_lines=0)
        self.assertEqual(len(calls), 2)
        for position, event in enumerate(events):
            if event == "predict":
                self.assertEqual(events[position - 1], "sync")
                self.assertEqual(events[position + 1], "sync")
        self.assertEqual(metric["framework_memory"]["gpu_peak_allocated_mib"], 3.0)
        self.assertEqual(self.summary()["easyocr"]["peak_vram_allocated_mib"], "3.0")

    def test_oom_records_partial_result_without_page_average(self):
        metric, calls, _, _, adapters, monitors = self.run_fake(
            responses=[RuntimeError("CUDA out of memory")], warmup_lines=0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(metric["run_status"], "incomplete_or_failed")
        self.assertFalse(metric["comparison_eligible"])
        self.assertIsNone(metric["mean_seconds_per_page_scope"])
        records = pipeline.read_jsonl(self.run_directory(metric) / "raw.jsonl")
        self.assertEqual(records[0]["status"], "out_of_memory")
        self.assertTrue(adapters[0].closed and monitors[0].stopped)
        self.assertEqual(self.hashes(self.root), self.original_hashes)

    def test_interruption_keeps_completed_requests_and_releases_resources(self):
        metric, calls, _, _, adapters, monitors = self.run_fake(
            responses=[{"raw_text": "first", "status": "completed"}, KeyboardInterrupt()], warmup_lines=0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(metric["run_status"], "interrupted")
        self.assertEqual(metric["measured_lines"], 1)
        self.assertFalse(metric["comparison_eligible"])
        self.assertEqual(len(pipeline.read_jsonl(self.run_directory(metric) / "raw.jsonl")), 1)
        self.assertTrue(adapters[0].closed and monitors[0].stopped)
        self.assertIsNone(metric["mean_seconds_per_page_scope"])

    def test_later_incomplete_run_does_not_hide_complete_comparable_run(self):
        complete, *_ = self.run_fake(warmup_lines=0)
        interrupted, *_ = self.run_fake(responses=[KeyboardInterrupt()], warmup_lines=0)
        self.assertEqual(complete["protocol_id"], interrupted["protocol_id"])
        row = self.summary()["easyocr"]
        self.assertEqual(row["run_status"], "complete")
        self.assertEqual(row["measured_lines"], "26")
        self.assertAlmostEqual(float(row["processing_s"]), complete["processing_seconds"])

    def test_protocols_are_not_mixed_in_summary(self):
        full, *_ = self.run_fake(engine="tesseract", warmup_lines=0)
        smoke, *_ = self.run_fake(engine="easyocr", line_limit=6, warmup_lines=0)
        self.assertNotEqual(full["protocol_id"], smoke["protocol_id"])
        rows = self.summary()
        self.assertEqual(rows["tesseract"]["run_status"], "not_measured")
        self.assertEqual(rows["easyocr"]["run_status"], "smoke_complete")
        efficiency.write_summary(self.root, full["protocol_id"])
        rows = self.summary()
        self.assertEqual(rows["tesseract"]["run_status"], "complete")
        self.assertEqual(rows["easyocr"]["run_status"], "not_measured")

    def test_import_measure_pack_roundtrip_preserves_original_bytes_and_metrics(self):
        original_zip = efficiency.pack_efficiency(self.root, self.base / "original.zip")
        loaded = self.base / "loaded"
        self.assertEqual(efficiency.import_efficiency_bundle(original_zip, loaded), self.index)
        self.assertEqual(self.hashes(loaded), self.original_hashes)
        with self.assertRaises(FileExistsError):
            efficiency.import_efficiency_bundle(original_zip, loaded)
        metric, *_ = self.run_fake(line_limit=3)
        (self.root / "model_weights.bin").write_bytes(b"not a transfer artifact")
        final_zip = efficiency.pack_efficiency(self.root, self.base / "measured.zip")
        with zipfile.ZipFile(final_zip) as bundle:
            names = bundle.namelist()
            self.assertTrue(any(n.startswith("efficiency/runs/") for n in names))
            self.assertEqual(sum(n.startswith("source/") and n.endswith(".jpg") for n in names), 7)
            self.assertFalse(any(n.endswith((".png", ".bin")) for n in names))
        target = self.base / "roundtrip"
        efficiency.import_efficiency_bundle(final_zip, target)
        self.assertEqual(self.hashes(target), self.original_hashes)
        reloaded = json.loads((target / self.run_directory(metric).relative_to(self.root) / "metrics.json").read_text())
        self.assertEqual(reloaded["protocol_id"], metric["protocol_id"])
        with self.assertRaises(ValueError):
            efficiency.pack_efficiency(self.root, self.root / "transfer.zip")

    def test_missing_source_index_and_absolute_zip_paths_are_rejected(self):
        missing = self.base / "missing.zip"
        with zipfile.ZipFile(missing, "w") as bundle:
            bundle.writestr("results/lines.csv", "text\n")
        with self.assertRaises(ValueError):
            efficiency.import_efficiency_bundle(missing, self.base / "missing-output")
        valid = efficiency.pack_efficiency(self.root, self.base / "valid.zip")
        unsafe = self.base / "unsafe.zip"
        with zipfile.ZipFile(valid) as source, zipfile.ZipFile(unsafe, "w") as bundle:
            for info in source.infolist():
                bundle.writestr(info.filename, source.read(info.filename))
            bundle.writestr("/escape.json", "{}")
        with self.assertRaisesRegex(ValueError, "Unsafe ZIP path"):
            efficiency.import_efficiency_bundle(unsafe, self.base / "unsafe-output")


if __name__ == "__main__":
    unittest.main()
