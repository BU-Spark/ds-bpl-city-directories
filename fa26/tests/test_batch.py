"""Recovery, retry budgets and quarantine exercised with tiny native fixtures."""

from copy import deepcopy
import csv
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from PIL import Image
import psutil

from bpl_ocr.batch import CaptureQuarantined, batch_lock, checked_page, load_plan, review_batch, run_batch
from bpl_ocr.engine import run_tesseract
from bpl_ocr.io import read_json, sha256_file, write_json
from bpl_ocr.manifest import load_manifest
from bpl_ocr.pipeline import recognize_page
from bpl_ocr.source import SourceUnavailable, fetch_page

BASE = Path(__file__).resolve().parents[1]
MANIFEST = BASE / "manifests/vol1/manifest.json"
HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
INFO = {"binary": "fixture", "version_text": "tesseract 5.3.4 fixture"}


class BatchTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.work, self.batch = self.root / "work", self.root / "batch"
        self.plan = read_json(BASE / "quality/stage4/plan.json")
        self.plan["leaves"] = [164, 165]
        self.plan_path = self.root / "plan.json"
        write_json(self.plan_path, self.plan)
        self.manifest = load_manifest(MANIFEST)
        self.page = next(p for p in self.manifest["pages"] if p["leaf_num"] == 164)
        self.calls = 0
        self.interrupt_call = None
        self.merge_columns = False
        for name in ("bpl_ocr.batch.inspect_engine", "bpl_ocr.pipeline.inspect_engine"):
            patcher = patch(name, return_value=INFO)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ("bpl_ocr.batch.prepare_model", "bpl_ocr.pipeline.prepare_model"):
            patcher = patch(name, return_value=self.work)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, replacement in (("bpl_ocr.pipeline.fetch_page", self.source),
                                  ("bpl_ocr.pipeline.run_tesseract", self.native),
                                  ("bpl_ocr.pipeline.preprocess", lambda image, dest, settings: dest.write_bytes(b"fixture"))):
            patcher = patch(name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def source(self, page, work, **kwargs):
        image = Path(work) / "source" / page["volume_id"] / f"leaf{page['leaf_num']:04d}.jpg"
        image.parent.mkdir(parents=True, exist_ok=True)
        Image.new("L", (page["expected_width"], page["expected_height"]), 255).save(image)
        return image, {"sha256": sha256_file(image), "source_image_url": page["source_image_url"]}, True

    def native(self, binary, model, prepared, output, settings, timeout, **kwargs):
        self.calls += 1
        if self.calls == self.interrupt_call:
            raise KeyboardInterrupt("fixture interruption")
        words = []
        for block, x in ((1, 260), (2, 1000)):
            for line in range(1, 5):
                for word in range(1, 6):
                    words.append(f"5\t1\t{block}\t1\t{line}\t{word}\t{2*(x+100*(word-1))+10}\t{2*(200+line*30)+10}\t180\t40\t80\tWord{word}\n")
        if self.merge_columns:
            for line in range(1, 4):
                for word in range(1, 6):
                    words.append(f"5\t1\t3\t1\t{line}\t{word}\t{2*(260+250*(word-1))+10}\t{2*(500+line*30)+10}\t180\t40\t80\tMerged{word}\n")
        output.with_suffix(".tsv").write_text(HEADER + "".join(words))
        output.with_suffix(".txt").write_text("Native fixture text\n")
        output.with_suffix(".hocr").write_text("<html></html>")
        return subprocess.CompletedProcess([], 0, b"", b""), ["fixture"] * 8

    def run_plan(self, **kwargs):
        return run_batch(MANIFEST, self.plan_path, self.work, self.batch, **kwargs)

    def test_interrupted_page_retries_but_completed_page_is_not_recognized_again(self):
        self.interrupt_call = 2
        with self.assertRaises(KeyboardInterrupt):
            self.run_plan()
        state = read_json(self.batch / "checkpoint.json")
        self.assertEqual([p["status"] for p in state["pages"]], ["completed", "interrupted"])
        first_id = state["pages"][0]["run_id"]
        summary = self.run_plan()
        state = read_json(self.batch / "checkpoint.json")
        self.assertEqual(self.calls, 3)
        self.assertEqual(state["pages"][0]["run_id"], first_id)
        self.assertEqual(summary["attempt_statuses"], {"completed": 2, "interrupted": 1})
        self.assertEqual(summary["detected_lines"], 16)
        self.run_plan()
        self.assertEqual(self.calls, 3)

    def test_completed_native_run_before_checkpoint_is_adopted_without_rerun(self):
        self.run_plan(max_pages=1)
        state = read_json(self.batch / "checkpoint.json")
        state["pages"][0]["status"] = state["pages"][0]["attempts"][-1]["status"] = "running"
        state["sessions"][0]["status"] = "running"
        write_json(self.batch / "checkpoint.json", state)
        self.run_plan()
        state = read_json(self.batch / "checkpoint.json")
        self.assertEqual(self.calls, 2)
        self.assertEqual(state["recovery_events"][0]["event"], "adopted_completed_run_before_checkpoint")
        self.assertIsNone(state["sessions"][0]["wall_s"])

    def test_changed_plan_and_modified_completed_output_do_not_silently_resume(self):
        self.run_plan()
        changed = deepcopy(self.plan)
        changed["policy"]["engine_timeout_s"] += 1
        write_json(self.plan_path, changed)
        with self.assertRaisesRegex(ValueError, "changed; create a new batch"):
            self.run_plan()
        write_json(self.plan_path, self.plan)
        with patch("bpl_ocr.batch.code_provenance", return_value={"code_sha256": {"changed.py": "a" * 64}}):
            with self.assertRaisesRegex(ValueError, "changed; create a new batch"):
                self.run_plan()
        state = read_json(self.batch / "checkpoint.json")
        raw = self.work / state["pages"][0]["run_directory"] / "raw/page.txt"
        raw.write_text("changed output")
        summary = self.run_plan()
        self.assertEqual(summary["page_statuses"], {"quarantined": 1, "completed": 1})
        self.assertEqual(summary["detected_lines"], 8)
        self.assertEqual(self.calls, 2)

    def test_interrupt_after_native_completion_is_adopted_without_recognition(self):
        self.run_plan(max_pages=1)
        state = read_json(self.batch / "checkpoint.json")
        state["pages"][0]["status"] = state["pages"][0]["attempts"][-1]["status"] = "interrupted"
        write_json(self.batch / "checkpoint.json", state)
        self.run_plan()
        self.assertEqual(self.calls, 2)
        state = read_json(self.batch / "checkpoint.json")
        self.assertEqual(state["recovery_events"][0]["event"], "adopted_completed_run_before_checkpoint")

    def test_source_failure_budget_is_bounded_and_later_pages_continue(self):
        def fail_one(manifest, leaf, work, **kwargs):
            if leaf == 164:
                raise SourceUnavailable([{"error": "fixture timeout"}])
            return recognize_page(manifest, leaf, work, **kwargs)
        with patch("bpl_ocr.batch.recognize_page", fail_one), patch("bpl_ocr.batch.time.sleep"):
            summary = self.run_plan()
        self.assertEqual(summary["page_statuses"], {"failed": 1, "completed": 1})
        self.assertEqual(summary["attempt_statuses"], {"failed": 2, "completed": 1})
        self.assertEqual(summary["status"], "needs_attention")

    def test_single_writer_lock_and_out_of_scope_plan_are_enforced(self):
        with batch_lock(self.batch):
            with self.assertRaisesRegex(RuntimeError, "Another worker"):
                with batch_lock(self.batch):
                    self.fail("Concurrent worker was allowed")
        self.plan["leaves"] = [781]
        write_json(self.plan_path, self.plan)
        with self.assertRaisesRegex(ValueError, "out-of-scope"):
            load_plan(self.plan_path, self.manifest)

    def test_fallback_records_failed_request_and_exact_member_not_printed_page(self):
        def retrieval(url, dest, **kwargs):
            if "iiif.archive.org" in url:
                raise urllib.error.URLError("fixture timeout")
            dest.parent.mkdir(parents=True, exist_ok=True)
            Image.new("L", (self.page["expected_width"], self.page["expected_height"]), 255).save(dest)
            return {"sha256": sha256_file(dest), "bytes": dest.stat().st_size, "request_url": url, "final_url": url}
        with patch("bpl_ocr.source.download", retrieval), patch("bpl_ocr.source.time.sleep"):
            image, receipt, cached = fetch_page(self.page, self.work, policy=self.plan["policy"]["source"])
        self.assertFalse(cached)
        self.assertEqual(len(receipt["acquisition_attempts"]), 2)
        self.assertIn("_0164.jp2", receipt["retrieval_url"])
        self.assertIn("scale=1", receipt["retrieval_url"])
        self.assertEqual(receipt["source_image_url"], self.page["source_image_url"])
        self.assertTrue(image.exists())

    def test_wrong_source_dimensions_are_quarantined_without_trying_another_rendering(self):
        def retrieval(url, dest, **kwargs):
            dest.parent.mkdir(parents=True, exist_ok=True)
            Image.new("L", (20, 30), 255).save(dest)
            return {"sha256": sha256_file(dest)}
        with patch("bpl_ocr.source.download", side_effect=retrieval) as download:
            with self.assertRaisesRegex(ValueError, "dimensions differ"):
                fetch_page(self.page, self.work, policy=self.plan["policy"]["source"])
        self.assertEqual(download.call_count, 1)
        self.assertFalse(list(self.work.rglob("*.candidate.jpg")))
        self.assertFalse(list(self.work.rglob("leaf0164.json")))

    def test_native_timeout_preserves_stderr_and_stops_child(self):
        executable = self.root / "sleeping-engine"
        executable.write_text("import sys,time\nprint('timeout fixture',file=sys.stderr,flush=True)\ntime.sleep(30)\n")
        pids = []
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            run_tesseract(sys.executable, self.root, executable, self.root / "out", self.manifest["config"]["ocr"], .15, on_start=pids.append)
        self.assertIn(b"timeout fixture", caught.exception.stderr)
        self.assertFalse(psutil.pid_exists(pids[0]))

    def test_systematic_column_merges_are_quarantined_and_raw_rows_retained(self):
        self.merge_columns = True
        summary = self.run_plan()
        self.assertEqual(summary["page_statuses"], {"quarantined": 2})
        self.assertEqual(summary["captured_native_lines"], 22)
        self.assertEqual(summary["exported_lines"], 0)
        self.assertEqual(summary["quarantined_lines"], 22)
        with (self.batch / "quarantined_lines.csv").open(encoding="utf-8-sig") as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 22)

    def test_new_offline_diagnostics_do_not_recognize_or_change_original_checkpoint(self):
        self.merge_columns = True
        def earlier_policy(*args):
            try:
                return checked_page(*args)
            except CaptureQuarantined as error:
                return error.review
        with patch("bpl_ocr.batch.checked_page", earlier_policy):
            self.assertEqual(self.run_plan()["page_statuses"], {"completed": 2})
        before = sha256_file(self.batch / "checkpoint.json")
        native_before = {p: sha256_file(p) for p in self.work.rglob("raw/page.*")}
        with patch("bpl_ocr.batch.recognize_page") as recognition:
            result = review_batch(MANIFEST, self.work, self.batch, self.root / "review")
            recognition.assert_not_called()
        self.assertEqual(result["page_statuses"], {"quarantined": 2})
        self.assertEqual(self.calls, 2)
        self.assertEqual(sha256_file(self.batch / "checkpoint.json"), before)
        self.assertEqual({p: sha256_file(p) for p in self.work.rglob("raw/page.*")}, native_before)


if __name__ == "__main__":
    unittest.main()
