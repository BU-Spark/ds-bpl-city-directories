"""Offline guarantees for the dev-compatible, fixed-scope OCR runner."""

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
from bpl_ocr.project import load_assignment, run_assignment

PROJECT = RUNNER / "plans/1916/project.json"
ASSIGNMENT = "worker-vol1"


class OcrRunnerIntegrationTest(unittest.TestCase):
    def test_all_fourteen_batches_cover_only_the_selected_physical_pages(self):
        project, assignment, manifest_path, batches = load_assignment(
            PROJECT, ASSIGNMENT, repo_root=RUNNER)
        manifest = load_manifest(manifest_path)
        leaves = [leaf for _, _, plan in batches for leaf in plan["leaves"]]
        expected = [n for n in range(162, 1535) if n not in (781, 782)]
        self.assertEqual(project["total_pages"], 1371)
        self.assertEqual(leaves, expected)
        self.assertEqual(len(set(leaves)), 1371)
        self.assertEqual([len(plan["leaves"]) for _, _, plan in batches],
                         [100] * 13 + [71])
        selected = [p for p in manifest["pages"] if p["selected_for_ocr"]]
        self.assertEqual(Counter(p["ocr_role"] for p in selected),
                         {"primary": 1370, "supplementary": 1})
        self.assertEqual(next(p for p in selected if p["leaf_num"] == 162)["ocr_role"],
                         "supplementary")
        self.assertEqual(assignment["model"], manifest["config"]["ocr"])
        self.assertEqual(assignment["model"]["engine_version"], "5.3.4")
        self.assertEqual(assignment["model"]["psm"], 3)

    def test_flattened_manifest_and_plan_paths_resolve_inside_feature_folder(self):
        _, assignment, manifest_path, batches = load_assignment(
            PROJECT, ASSIGNMENT, repo_root=RUNNER)
        self.assertEqual(assignment["manifest"], "manifests/vol1/manifest.json")
        self.assertEqual(manifest_path.resolve(),
                         (RUNNER / "manifests/vol1/manifest.json").resolve())
        self.assertEqual(read_json(RUNNER / "config/vol1.json")["ocr"],
                         assignment["model"])
        for _, path, _ in batches:
            self.assertTrue(path.is_file())
            self.assertTrue(path.resolve().is_relative_to(RUNNER.resolve()))

    def test_wrapper_dry_run_uses_its_own_folder_from_unrelated_cwd(self):
        # Build fixture checksums, avoiding dependence on live documentation or
        # checksum values while the integration package is being prepared.
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
                [sys.executable, "-B", str(fixture / "run_ocr.py"), "--dry-run"],
                cwd=elsewhere, capture_output=True, text=True, timeout=15,
                check=True)
            report = json.loads(result.stdout)
            self.assertEqual(report["assignment_id"], ASSIGNMENT)
            self.assertEqual(report["physical_pages"], 1371)
            self.assertEqual(report["batches"], 14)
            self.assertEqual(Path(report["data_directory"]), fixture / "results")
            self.assertFalse(report["ocr_started"])
            self.assertFalse((fixture / "results").exists())
            self.assertFalse((elsewhere / "results").exists())

    def test_wrapper_check_passes_the_flattened_configuration_path(self):
        spec = importlib.util.spec_from_file_location(
            "integrated_ocr_wrapper", RUNNER / "run_ocr.py")
        wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wrapper)
        assignment = read_json(PROJECT)["assignments"][0]
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp).resolve() / "results"
            with patch.object(wrapper, "verify_package", return_value=assignment), \
                 patch.object(wrapper, "invoke", return_value=0) as invocation, \
                 patch.object(sys, "argv", [str(RUNNER / "run_ocr.py"),
                                            "--check", "--data-dir", str(data)]):
                self.assertEqual(wrapper.main(), 0)
            command, environment, log = invocation.call_args.args
            self.assertEqual(command[:3], ["doctor", "--config", "config/vol1.json"])
            self.assertTrue((RUNNER / command[2]).is_file())
            self.assertEqual(Path(command[4]), data / ASSIGNMENT / "work")
            self.assertEqual(environment["OMP_THREAD_LIMIT"], "1")
            self.assertEqual(log, data / ASSIGNMENT / "runner.log")

    def test_quarantine_does_not_prevent_later_batches_from_finishing(self):
        calls = []

        def fake_capture(manifest, plan_path, work, batch_dir, **kwargs):
            plan = read_json(plan_path)
            calls.append(plan["batch_id"])
            self.assertTrue(Path(manifest).resolve().is_relative_to(RUNNER.resolve()))
            pages = [{"leaf_num": leaf,
                      "status": "quarantined" if leaf == 518 else "completed",
                      "attempts": [{"status": "completed"}]} for leaf in plan["leaves"]]
            write_json(Path(batch_dir) / "checkpoint.json",
                       {"plan_id": identity(plan), "pages": pages,
                        "status": "needs_attention" if 518 in plan["leaves"] else "completed"})

        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            # Stub provenance too: its real implementation runs Git commands.
            # This test invokes neither Git, Tesseract, model preparation nor HTTP.
            with patch("bpl_ocr.project.run_batch", fake_capture), \
                 patch("bpl_ocr.project.code_provenance",
                       return_value={"code_sha256": {"fixture.py": "a" * 64}}), \
                 contextlib.redirect_stdout(io.StringIO()):
                result = run_assignment(PROJECT, ASSIGNMENT, data, repo_root=RUNNER)
            self.assertEqual(calls, [f"vol1-{n:03d}" for n in range(1, 15)])
            self.assertEqual(result["status"], "needs_attention")
            self.assertEqual(result["page_statuses"],
                             {"completed": 1370, "quarantined": 1})
            with (data / ASSIGNMENT / "coverage.csv").open(
                    encoding="utf-8-sig", newline="") as handle:
                coverage = list(csv.DictReader(handle))
            self.assertEqual(len(coverage), 1371)
            self.assertEqual([int(p["leaf_num"]) for p in coverage
                              if p["status"] == "quarantined"], [518])
            self.assertEqual(len({p["page_id"] for p in read_json(
                RUNNER / "manifests/vol1/manifest.json")["pages"]}), 1544)
            self.assertFalse((data / ASSIGNMENT / "work").exists())


if __name__ == "__main__":
    unittest.main()
