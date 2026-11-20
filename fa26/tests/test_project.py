"""Two-volume scope, disjoint ownership and queue continuation guarantees."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bpl_ocr.io import identity, read_json, write_json
from bpl_ocr.manifest import load_manifest, prepare_manifest
from bpl_ocr.project import assignment_status, load_assignment, partition, run_assignment

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parent
ASSIGNMENTS = [("Katherine", "fa26/manifests/vol1/manifest.json"), ("Yanlun", "fa26/manifests/vol2/manifest.json")]


class ProjectTest(unittest.TestCase):
    def test_two_volume_targets_are_disjoint_complete_and_model_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "plans"
            project = partition(ASSIGNMENTS, out, repo_root=ROOT)
            self.assertEqual(project["total_pages"], 1937)
            self.assertEqual([a["pages"] for a in project["assignments"]], [1371, 566])
            self.assertEqual([len(a["batches"]) for a in project["assignments"]], [14, 6])
            self.assertEqual(project["assignments"][0]["model"], project["assignments"][1]["model"])
            seen = set()
            for a in project["assignments"]:
                _, _, _, batches = load_assignment(out / "project.json", a["assignment_id"], ROOT)
                for _, _, plan in batches:
                    self.assertLessEqual(len(plan["leaves"]), 100)
                    for leaf in plan["leaves"]:
                        self.assertNotIn((a["volume_id"], leaf), seen)
                        seen.add((a["volume_id"], leaf))
            self.assertEqual(len(seen), 1937)
            self.assertEqual(partition(ASSIGNMENTS, out, repo_root=ROOT), project)
            with self.assertRaisesRegex(ValueError, "already in use"):
                partition(ASSIGNMENTS, out, batch_size=50, repo_root=ROOT)

    def test_duplicate_volume_or_tampered_batch_cannot_allocate_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "exactly once"):
                partition([ASSIGNMENTS[0], ("Yanlun", ASSIGNMENTS[0][1])], root / "bad", repo_root=ROOT)
            out = root / "plans"
            project = partition(ASSIGNMENTS, out, repo_root=ROOT)
            plan = out / project["assignments"][1]["batches"][0]["plan_file"]
            changed = read_json(plan)
            changed["leaves"].pop()
            write_json(plan, changed)
            with self.assertRaisesRegex(ValueError, "Batch plan changed"):
                load_assignment(out / "project.json", "yanlun-vol2", ROOT)

    def test_second_volume_composite_label_is_one_scan_and_business_is_excluded(self):
        manifest = load_manifest(BASE / "manifests/vol2/manifest.json")
        pages = {p["leaf_num"]: p for p in manifest["pages"]}
        selected = [p for p in pages.values() if p["selected_for_ocr"]]
        self.assertEqual(len(selected), 566)
        self.assertEqual((pages[7]["printed_page"], pages[7]["bookreader_index"]), ("1535", 6))
        self.assertEqual(pages[571]["printed_page"], "2099–2143")
        self.assertEqual(pages[571]["scandata_page_label"], "2143")
        self.assertTrue(pages[572]["selected_for_ocr"])
        self.assertFalse(pages[573]["selected_for_ocr"])
        self.assertEqual(pages[573]["section"], "business_directory_and_later_reference_sections")
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(BASE / "manifests/vol2/source", root / "source")
            report = prepare_manifest(BASE / "config/vol2.json", root, offline=True)
            self.assertEqual(report["manifest_id"], manifest["manifest_id"])
            self.assertEqual(report["absent_primary_printed_labels"], [])
            self.assertEqual(report["composite_primary_labels"][0]["physical_scans"], 1)

    def test_queue_continues_after_quarantine_and_pause_counts_only_new_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out, data = root / "plans", root / "data"
            partition(ASSIGNMENTS, out, repo_root=ROOT)
            calls = []
            def capture(manifest, plan_path, work, batch_dir, **kwargs):
                plan = read_json(plan_path)
                calls.append(plan["batch_id"])
                pages = [{"leaf_num": n, "status": "quarantined" if n == 7 else "completed", "attempts": [{"status": "completed"}]} for n in plan["leaves"]]
                write_json(Path(batch_dir) / "checkpoint.json", {"plan_id": identity(plan), "status": "needs_attention" if 7 in plan["leaves"] else "completed", "pages": pages})
            with patch("bpl_ocr.project.run_batch", capture):
                first = run_assignment(out / "project.json", "yanlun-vol2", data, repo_root=ROOT, max_batches=2)
                self.assertEqual(first["page_statuses"], {"quarantined": 1, "completed": 199, "not_started": 366})
                second = run_assignment(out / "project.json", "yanlun-vol2", data, repo_root=ROOT, max_batches=1)
                self.assertEqual(second["page_statuses"]["completed"], 299)
                self.assertEqual(len(set(calls)), 3)
                self.assertEqual(len(calls), 5)
            self.assertTrue((data / "yanlun-vol2/coverage.csv").exists())
            other = assignment_status(out / "project.json", "katherine-vol1", data, repo_root=ROOT)
            self.assertEqual(other["page_statuses"], {"not_started": 1371})


if __name__ == "__main__":
    unittest.main()
