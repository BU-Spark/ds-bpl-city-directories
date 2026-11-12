"""Regression checks for record boundaries, ditto meanings and review isolation."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import extract_a_sample as pilot


def entry(text, column="left"):
    return {"working_text": text, "column": column,
            "overflow_received": "", "overflow_passed_forward": ""}


def line(line_id, text, x=100):
    return {"line_id": line_id, "text": text, "x": x, "column": "left"}


class ParsingRulesTest(unittest.TestCase):
    def test_raised_continuation_keeps_donor_provenance(self):
        entries = pilot.segment_entries([
            line("L001", "Aalto J tailor h 61 Myrtle [ren Rox"),
            line("L002", "Aaron Abraham L jeweler 1915 Wash h 624 War-"),
        ])
        self.assertEqual(entries[0]["working_text"], "Aalto J tailor h 61 Myrtle")
        self.assertIn("[ren Rox", entries[0]["raw_ocr_text"])
        self.assertTrue(entries[1]["working_text"].endswith("624 Warren Rox"))
        self.assertEqual(entries[1]["source_line_ids"], ["L001", "L002"])

    def test_balanced_multiline_affiliation_does_not_leak_forward(self):
        entries = pilot.segment_entries([
            line("L001", '" & Bartlett (David J Aaron, Charles E Bart-'),
            line("L002", "lett) lawyers 40 Court rm 1002", x=155),
            line("L003", "Aarons Loring E tel opr h 406 W Broadway S B"),
        ])
        self.assertIn("Charles E Bartlett)", entries[0]["working_text"])
        self.assertEqual(entries[1]["overflow_received"], "")
        fields, _ = pilot.parse_fields(entries[1], "Aaron")
        self.assertEqual(fields["occupation_normalized"], "telegraph operator")
        self.assertEqual(fields["residence_address_normalized"], "406 West Broadway, South Boston")

    def test_whole_address_ditto_and_neighborhood_ditto_are_distinct(self):
        full, _ = pilot.parse_fields(entry("Abbe Elizabeth M physician 45 Dale Rox h do"), "")
        suffix, _ = pilot.parse_fields(entry("Aaron Herman mgr 628 E Fourth S B bds 737 E Broadway do"), "")
        self.assertEqual(full["residence_address_raw"], "do")
        self.assertEqual(full["residence_address_normalized"], "45 Dale, Roxbury")
        self.assertEqual(full["neighborhood_raw"], "")
        self.assertEqual(full["neighborhood_normalized"], "Roxbury")
        self.assertEqual(suffix["residence_address_normalized"], "737 East Broadway, South Boston")
        self.assertEqual(suffix["neighborhood_raw"], "do")

    def test_unresolved_ditto_is_not_guessed(self):
        for text, flag in [
            ("Aaron John tailor h do", "unresolved_address_ditto"),
            ("Aaron John tailor 10 Main h 20 Pine do", "unresolved_neighborhood_ditto"),
        ]:
            with self.subTest(text=text):
                fields, flags = pilot.parse_fields(entry(text), "")
                self.assertEqual(fields["residence_address_normalized"], "")
                self.assertIn(flag, flags)

    def test_missing_surname_stays_missing_and_affiliation_does_not_invent_role(self):
        fields, flags = pilot.parse_fields(entry('" Manuel H (Aarons & Golosov) 162 Hanover h 884 Harrison av'), "")
        self.assertEqual(fields["surname"], "")
        self.assertEqual(fields["occupation_raw"], "")
        self.assertEqual(fields["affiliation_raw"], "Aarons & Golosov")
        self.assertIn("surname_context_missing", flags)

    def test_status_notice_does_not_become_current_residence(self):
        for text, status in [("Aaronson Barnard died Aug 31 1915", "deceased"),
                             ("Abber Annie Mrs rem to Malden", "removed")]:
            with self.subTest(text=text):
                fields, _ = pilot.parse_fields(entry(text), "")
                self.assertEqual(fields["record_status"], status)
                self.assertEqual(fields["residence_address_raw"], "")

    def test_missing_entry_is_not_filled_from_selection(self):
        selection = [{"locator_label": "Abate Angelo", "column": "right"}]
        _, candidate, flags = pilot.locate_samples([], selection)[0]
        self.assertIsNone(candidate)
        self.assertIn("selected_entry_not_found_in_ocr", flags)

    def test_matching_does_not_steal_another_person_with_same_given_name(self):
        candidate = entry("Abatto Salvatore laborer h 71 Lubec E B", "right")
        candidate["fields"], candidate["flags"] = pilot.parse_fields(candidate, "")
        selection = [{"locator_label": name, "column": "right"}
                     for name in ("Abate Salvatore", "Abatto Salvatore")]
        matches = pilot.locate_samples([candidate], selection)
        self.assertIsNone(matches[0][1])
        self.assertIs(matches[1][1], candidate)

    def test_image_checks_never_overwrite_baseline(self):
        record = {"sample_id": "A003", "source_page_url": "example",
                  "residence_address_raw": "668 Blue Hill av Dor"}
        before = copy.deepcopy(record)
        checks = {"reviewer": "test", "review_scope": "test", "entries": [
            {"sample_id": "A003", "note": "number differs",
             "expected": {"residence_address_raw": "568 Blue Hill av Dor"}}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "checks.json"
            path.write_text(json.dumps(checks))
            results, _ = pilot.run_checks([record], path)
        self.assertEqual(record, before)
        self.assertEqual(results[0]["agreement"], "no")


@unittest.skipUnless((pilot.OUTPUT / "source/p161_ocr.json").exists(),
                     "Run step 2 once to cache the page OCR for this integration check")
class CachedPageTest(unittest.TestCase):
    def test_selected_records_remain_traceable_without_label_imputation(self):
        annotations = json.loads((pilot.OUTPUT / "source/p161_ocr.json").read_text())
        lines = pilot.reconstruct_lines(annotations)
        candidates = pilot.segment_entries(lines)
        previous = {"left": "", "right": ""}
        for candidate in candidates:
            fields, flags = pilot.parse_fields(candidate, previous[candidate["column"]])
            previous[candidate["column"]] = fields["surname"]
            candidate.update(fields=fields, flags=flags)
        matches = pilot.locate_samples(candidates, pilot.read_csv(pilot.OUTPUT / "sample_index.csv"))
        self.assertEqual(len(matches), 53)
        self.assertEqual({sample["sample_id"] for sample, candidate, _ in matches if candidate is None},
                         {"A031", "A049"})
        selected = {sample["sample_id"]: candidate for sample, candidate, _ in matches}
        self.assertEqual(selected["A003"]["fields"]["residence_address_raw"], "668 Blue Hill av Dor")
        self.assertEqual(selected["A020"]["fields"]["surname"], "")
        line_ids = {line["line_id"] for line in lines}
        for candidate in selected.values():
            if candidate:
                self.assertTrue(set(candidate["source_line_ids"]) <= line_ids)
        # The raised continuation is on a physical line above Aaron Abraham L.
        self.assertGreater(len(selected["A002"]["source_line_ids"]), len(selected["A002"]["lines"]))


if __name__ == "__main__":
    unittest.main()
