"""Offline guarantees for the multi-worker Volume-1 OCR runner template."""

from collections import Counter
import contextlib
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

RUNNER = Path(__file__).resolve().parents[1] / "ocr"
sys.path.insert(0, str(RUNNER / "src"))

from bpl_ocr.io import identity, read_json, write_json
from bpl_ocr.manifest import load_manifest
from bpl_ocr.project import load_assignment, run_assignment, verify_project_coverage

PROJECT = RUNNER / "plans/1916/project.json"
ASSIGNMENTS = ("worker-1", "worker-2", "worker-3")


class OcrRunnerIntegrationTest(unittest.TestCase):
    def test_worker_assignments_partition_the_selected_pages(self):
        project = read_json(PROJECT)
        self.assertEqual([a["assignment_id"] for a in project["assignments"]], list(ASSIGNMENTS))
        self.assertEqual(project["total_pages"], 1371)
        verify_project_coverage(PROJECT, repo_root=RUNNER)

        all_leaves = []
        batch_sizes = []
        for assignment_id in ASSIGNMENTS:
            _, assignment, manifest_path, batches = load_assignment(
                PROJECT, assignment_id, repo_root=RUNNER)
            leaves = [leaf for _, _, plan in batches for leaf in plan["leaves"]]
            all_leaves.extend(leaves)
            batch_sizes.extend(len(plan["leaves"]) for _, _, plan in batches)
            self.assertEqual(len(leaves), assignment["pages"])
            self.assertEqual(assignment["model"]["engine_version"], "5.3.4")
            self.assertEqual(assignment["model"]["psm"], 3)
            self.assertEqual(assignment["manifest"], "manifests/vol1/manifest.json")
            self.assertEqual(manifest_path.resolve(),
                             (RUNNER / "manifests/vol1/manifest.json").resolve())

        expected = [n for n in range(162, 1535) if n not in (781, 782)]
        self.assertEqual(all_leaves, expected)
        self.assertEqual(len(set(all_leaves)), 1371)
        self.assertEqual(batch_sizes, [100] * 13 + [71])
        selected = [p for p in load_manifest(RUNNER / "manifests/vol1/manifest.json")["pages"]
                    if p["selected_for_ocr"]]
        self.assertEqual(Counter(p["ocr_role"] for p in selected),
                         {"primary": 1370, "supplementary": 1})

    def test_wrapper_dry_run_uses_its_own_folder_from_unrelated_cwd(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            fixture, elsewhere = root / "runner", root / "elsewhere"
            fixture.mkdir()
            elsewhere.mkdir()
            shutil.copyfile(RUNNER / "run_ocr.py", fixture / "run_ocr.py")
            project = fixture / "plans/1916/project.json"
            project.parent.mkdir(parents=True)
            shutil.copyfile(PROJECT, project)
            files = (fixture / "run_ocr.py", project)
            checksums = {p.relative_to(fixture).as_posix():
                         hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
            write_json(fixture / "CHECKSUMS.json", checksums)
            result = subprocess.run(
                [sys.executable, "-B", str(fixture / "run_ocr.py"),
                 "--assignment", "worker-1", "--dry-run"],
                cwd=elsewhere, capture_output=True, text=True, timeout=15,
                check=True)
            report = json.loads(result.stdout)
            self.assertEqual(report["assignment_id"], "worker-1")
            self.assertEqual(report["physical_pages"], 500)
            self.assertEqual(report["batches"], 5)
            self.assertEqual(report["batch_ids"],
                             [f"vol1-{n:03d}" for n in range(1, 6)])
            self.assertEqual(Path(report["data_directory"]), fixture / "results" / "worker-1")
            self.assertFalse(report["ocr_started"])
            self.assertFalse((fixture / "results").exists())
            self.assertFalse((elsewhere / "results").exists())

    def test_wrapper_check_passes_the_flattened_configuration_path(self):
        spec = importlib.util.spec_from_file_location(
            "integrated_ocr_wrapper", RUNNER / "run_ocr.py")
        wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wrapper)
        assignment = next(a for a in read_json(PROJECT)["assignments"]
                          if a["assignment_id"] == "worker-1")
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp).resolve() / "results"
            with patch.object(wrapper, "verify_package", return_value=(read_json(PROJECT), assignment)), \
                 patch.object(wrapper, "invoke", return_value=0) as invocation, \
                 patch.object(sys, "argv", [str(RUNNER / "run_ocr.py"),
                                            "--assignment", "worker-1",
                                            "--check", "--data-dir", str(data)]):
                self.assertEqual(wrapper.main(), 0)
            command, environment, log = invocation.call_args.args
            self.assertEqual(command[:3], ["doctor", "--config", "config/vol1.json"])
            self.assertTrue((RUNNER / command[2]).is_file())
            self.assertEqual(Path(command[4]), data / "worker-1" / "work")
            self.assertEqual(environment["OMP_THREAD_LIMIT"], "1")
            self.assertEqual(log, data / "worker-1" / "runner.log")

    def test_quarantine_does_not_prevent_later_batches_from_finishing(self):
        calls = []

        def fake_capture(manifest, plan_path, work, batch_dir, **kwargs):
            plan = read_json(plan_path)
            calls.append(plan["batch_id"])
            self.assertTrue(str(Path(manifest).resolve()).startswith(str(RUNNER.resolve())))
            pages = [{"leaf_num": leaf,
                      "status": "quarantined" if leaf == 518 else "completed",
                      "attempts": [{"status": "completed"}]} for leaf in plan["leaves"]]
            write_json(Path(batch_dir) / "checkpoint.json",
                       {"plan_id": identity(plan), "pages": pages,
                        "status": "needs_attention" if 518 in plan["leaves"] else "completed"})

        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            with patch("bpl_ocr.project.run_batch", fake_capture), \
                 patch("bpl_ocr.project.code_provenance",
                       return_value={"code_sha256": {"fixture.py": "a" * 64}}), \
                 contextlib.redirect_stdout(io.StringIO()):
                result = run_assignment(PROJECT, "worker-1", data, repo_root=RUNNER)
            self.assertEqual(calls, [f"vol1-{n:03d}" for n in range(1, 6)])
            self.assertEqual(result["status"], "needs_attention")
            self.assertEqual(result["page_statuses"],
                             {"completed": 499, "quarantined": 1})
            with (data / "worker-1" / "coverage.csv").open(
                    encoding="utf-8-sig", newline="") as handle:
                coverage = list(csv.DictReader(handle))
            self.assertEqual(len(coverage), 500)
            self.assertEqual([int(p["leaf_num"]) for p in coverage
                              if p["status"] == "quarantined"], [518])
            self.assertFalse((data / "worker-1" / "work").exists())


if __name__ == "__main__":
    unittest.main()
