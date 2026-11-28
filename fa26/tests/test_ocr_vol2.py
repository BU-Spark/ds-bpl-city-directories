"""Volume-2 scope, isolated validation and compatibility with published Volume 1."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

RUNNER = Path(__file__).resolve().parents[1] / "ocr"
sys.path.insert(0, str(RUNNER / "src"))
sys.path.insert(0, str(RUNNER))

from bpl_ocr.batch import load_plan
from bpl_ocr.io import read_json
from bpl_ocr.manifest import load_manifest
from bpl_ocr.project import load_assignment, verify_project_coverage
import run_ocr
import validate_vol2

PROJECT = RUNNER / "plans/1916/vol2-project.json"


class Volume2IntegrationTest(unittest.TestCase):
    def test_published_volume1_files_and_core_hash_set_are_unchanged(self):
        baseline = read_json(Path(__file__).parent / "fixtures/ocr_vol1_baseline.json")
        self.assertEqual(baseline["upstream_commit"],
                         "750d0f68779fe8000da7f506dc8dff15ac309b42")
        for name, digest in baseline["sha256"].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((RUNNER / name).read_bytes()).hexdigest(), digest)
        expected_core = {Path(p).name for p in baseline["sha256"]
                         if p.startswith("src/bpl_ocr/")}
        self.assertEqual({p.name for p in (RUNNER / "src/bpl_ocr").glob("*.py")}, expected_core)
        self.assertEqual(read_json(RUNNER / "plans/1916/project.json")["project_id"],
                         baseline["project_id"])

    def test_six_batches_cover_exactly_566_selected_pages(self):
        project, assignment, manifest_path, batches = load_assignment(
            PROJECT, "worker-vol2", repo_root=RUNNER)
        self.assertTrue(verify_project_coverage(PROJECT, repo_root=RUNNER))
        self.assertEqual(project["total_pages"], 566)
        self.assertEqual([a["assignment_id"] for a in project["assignments"]], ["worker-vol2"])
        leaves = [leaf for _, _, plan in batches for leaf in plan["leaves"]]
        self.assertEqual(leaves, list(range(7, 573)))
        self.assertEqual(len(set(leaves)), 566)
        self.assertEqual([b["batch_id"] for b, _, _ in batches],
                         [f"vol2-{n:03d}" for n in range(1, 7)])
        self.assertEqual([len(p["leaves"]) for _, _, p in batches], [100] * 5 + [66])
        self.assertEqual(manifest_path, RUNNER / "manifests/vol2/manifest.json")
        selected = [p for p in load_manifest(manifest_path)["pages"] if p["selected_for_ocr"]]
        self.assertTrue(all(p["ocr_role"] == "primary" for p in selected))
        for volume in ("vol1", "vol2"):
            self.assertEqual(assignment["model"], read_json(RUNNER / f"config/{volume}.json")["ocr"])
        for _, _, plan in batches:
            self.assertEqual(plan["policy"]["source"]["bookreader_base"],
                             "https://ia601603.us.archive.org/BookReader/BookReaderImages.php")
            self.assertEqual(plan["policy"]["source"]["bookreader_zip"],
                             "/5/items/bostonmassachuse19162112samp/bostonmassachuse19162112samp_jp2.zip")

    def test_composite_label_and_business_boundary_remain_explicit(self):
        manifest = load_manifest(RUNNER / "manifests/vol2/manifest.json")
        self.assertEqual(manifest["manifest_id"],
                         "7819b7078ed7092ad3dae02f2ba6c4e602558cdea81ff6c8e5c15a7460cdb1ab")
        pages = {p["leaf_num"]: p for p in manifest["pages"]}
        self.assertEqual(pages[7]["printed_page"], "1535")
        self.assertEqual(pages[571]["printed_page"], "2099–2143")
        self.assertEqual(pages[571]["page_label_source"], "visual_override")
        self.assertTrue(pages[571]["selected_for_ocr"])
        self.assertEqual(pages[572]["printed_page"], "2144")
        self.assertEqual(pages[573]["printed_page"], "2145")
        self.assertFalse(pages[573]["selected_for_ocr"])

    def test_wrong_volume_assignment_is_rejected_before_creating_data(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp).resolve() / "results"
            for arguments in (["--assignment", "worker-vol2"],
                              ["--volume", "vol2", "--assignment", "worker-1"]):
                result = subprocess.run([sys.executable, "-B", str(RUNNER / "run_ocr.py"),
                                         *arguments, "--dry-run", "--data-dir", str(data)],
                                        cwd=temp, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 1)
                self.assertIn("Unknown assignment", result.stderr)
                self.assertFalse(data.exists())

    def test_both_volume_dry_runs_work_from_an_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp).resolve() / "results"
            for volume, assignment, pages, batches in (
                    ("vol1", "worker-1", 500, 5), ("vol2", "worker-vol2", 566, 6)):
                result = subprocess.run([sys.executable, "-B", str(RUNNER / "run_ocr.py"),
                                         "--volume", volume, "--assignment", assignment,
                                         "--dry-run", "--data-dir", str(data)],
                                        cwd=temp, capture_output=True, text=True, timeout=15, check=True)
                report = json.loads(result.stdout)
                self.assertEqual((report["physical_pages"], report["batches"]), (pages, batches))
                self.assertEqual(Path(report["data_directory"]), data / assignment)
                self.assertFalse(report["ocr_started"])
                self.assertFalse(data.exists())

    def test_volume2_modes_use_the_correct_registry_config_and_directory(self):
        for mode in ("--check", "--status", "--max-batches"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                arguments = [str(RUNNER / "run_ocr.py"), "--volume", "vol2",
                             "--assignment", "worker-vol2", "--data-dir", temp, mode]
                if mode == "--max-batches":
                    arguments.append("1")
                with patch.object(run_ocr, "invoke", return_value=0) as invocation, \
                     patch.object(sys, "argv", arguments):
                    self.assertEqual(run_ocr.main(), 0)
                calls = [call.args[0] for call in invocation.call_args_list]
                if mode == "--check":
                    self.assertEqual(calls[0][:3], ["doctor", "--config", "config/vol2.json"])
                    self.assertEqual(len(calls), 1)
                else:
                    command = "assignment-status" if mode == "--status" else "run-assignment"
                    self.assertEqual(calls[-1][:3], [command, "--project", "plans/1916/vol2-project.json"])
                for call in invocation.call_args_list:
                    self.assertEqual(call.args[1]["OMP_THREAD_LIMIT"], "1")
                    self.assertEqual(call.args[2], Path(temp).resolve() / "worker-vol2/runner.log")

    def test_validation_is_four_pages_and_has_no_production_receipt(self):
        manifest = load_manifest(RUNNER / "manifests/vol2/manifest.json")
        plan = load_plan(RUNNER / validate_vol2.PLAN, manifest)
        self.assertEqual(plan["leaves"], [7, 288, 571, 572])
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp).resolve() / "sample"
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(validate_vol2.main(["--dry-run", "--data-dir", str(data)]), 0)
            self.assertFalse(json.loads(output.getvalue())["production_queue_started"])
            self.assertFalse(data.exists())
            with patch("bpl_ocr.batch.run_batch", return_value={"status": "paused"}) as capture, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(validate_vol2.main(["--run", "--max-pages", "2",
                                                     "--data-dir", str(data)]), 0)
            capture.assert_called_once_with(RUNNER / validate_vol2.MANIFEST,
                                            RUNNER / validate_vol2.PLAN,
                                            data / "work", data / "batch", max_pages=2)
            self.assertFalse((data / "assignment.json").exists())
            with self.assertRaisesRegex(ValueError, "separate validation"):
                validate_vol2.main(["--run", "--data-dir", str(Path(temp) / "worker-vol2")])


if __name__ == "__main__":
    unittest.main()
