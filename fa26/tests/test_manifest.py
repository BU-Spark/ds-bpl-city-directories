"""Provenance and pagination safeguards; no network or OCR engine required."""

import json
from pathlib import Path
import tempfile
import unittest

from bpl_ocr.io import load_config, write_json
from bpl_ocr.manifest import load_manifest, prepare_manifest

BASE = Path(__file__).resolve().parents[1]


class ManifestTest(unittest.TestCase):
    def test_all_source_leaves_and_access_indices_are_distinct(self):
        manifest = load_manifest(BASE / "manifests/vol1/manifest.json")
        pages = manifest["pages"]
        self.assertEqual(len(pages), 1544)
        self.assertEqual(len({p["page_id"] for p in pages}), 1544)
        access = [p for p in pages if p["access_available"]]
        self.assertEqual([p["bookreader_index"] for p in access], list(range(1538)))
        first = next(p for p in pages if p["leaf_num"] == 163)
        self.assertEqual((first["printed_page"], first["bookreader_index"]), ("161", 162))
        self.assertIn("/page/n162/", first["source_page_url"])
        self.assertIn("_0163.jp2/", first["source_image_url"])

    def test_ads_supplement_and_composite_page_do_not_become_residents(self):
        manifest = load_manifest(BASE / "manifests/vol1/manifest.json")
        pages = {p["leaf_num"]: p for p in manifest["pages"]}
        for leaf in (781, 782):
            self.assertEqual(pages[leaf]["section"], "inserted_advertisement")
            self.assertFalse(pages[leaf]["selected_for_ocr"])
        self.assertEqual(pages[162]["ocr_role"], "supplementary")
        self.assertEqual(pages[161]["printed_page"], "153–159")
        self.assertEqual(pages[161]["scandata_page_label"], "159")
        primary = [p for p in pages.values() if p["ocr_role"] == "primary"]
        self.assertEqual(len(primary), 1370)
        labels = {p["printed_page"] for p in primary}
        self.assertTrue({"775", "776", "777", "778"}.isdisjoint(labels))

    def test_offline_rebuild_preserves_manifest_identity_and_label_conflicts(self):
        checked = load_manifest(BASE / "manifests/vol1/manifest.json")
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "manifest"
            shutil.copytree(BASE / "manifests/vol1/source", destination / "source")
            report = prepare_manifest(BASE / "config/vol1.json", destination, offline=True)
            self.assertEqual(report["manifest_id"], checked["manifest_id"])
            self.assertEqual(report["absent_primary_printed_labels"], [775, 776, 777, 778])
            conflict = next(i for i in report["issues"] if i["type"] == "page_label_sources_disagree" and i["leaf_num"] == 163)
            self.assertEqual((conflict["scandata"], conflict["page_numbers_json"]), ("161", "155"))

    def test_changed_manifest_and_corrupt_cached_snapshot_are_rejected(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            changed = json.loads((BASE / "manifests/vol1/manifest.json").read_text())
            changed["pages"][163]["selected_for_ocr"] = False
            write_json(destination / "manifest.json", changed)
            with self.assertRaisesRegex(ValueError, "Manifest changed"):
                load_manifest(destination / "manifest.json")
            shutil.copytree(BASE / "manifests/vol1/source", destination / "source")
            with (destination / "source" / changed["config"]["scandata_file"]).open("ab") as handle:
                handle.write(b"\n")
            with self.assertRaisesRegex(ValueError, "MD5 validation"):
                prepare_manifest(BASE / "config/vol1.json", destination, offline=True)

    def test_line_crop_settings_are_rejected_as_a_production_baseline(self):
        config = load_config(BASE / "config/vol1.json")
        config["ocr"]["psm"] = 7
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            write_json(path, config)
            with self.assertRaisesRegex(ValueError, "full-page baseline"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
