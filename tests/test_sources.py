"""The data source layer: where each AML term is recorded, which table provides which source, and what follows (src/sources.py, src/typology.py).

Run:  .venv/bin/python -m unittest tests.test_sources
The Ontop test takes a few seconds; the others read files only.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import data_ontology  # noqa: E402
import indicators  # noqa: E402
import paths  # noqa: E402
import sources  # noqa: E402
import typology  # noqa: E402

TECH = "T0039"
NEEDS = {i["id"]: i["needs"] for i in indicators.registry()["indicators"]}


class Declarations(unittest.TestCase):
    def test_the_typology_lists_eight_sources_for_the_technique(self):
        self.assertEqual(sources.technique_sources(TECH),
                         ["DS0004", "DS0013", "DS0019", "DS0030", "DS0036", "DS0039", "DS0047", "DS0049"])

    def test_the_declarations_are_consistent(self):
        self.assertEqual(sources.check(TECH, NEEDS), [])

    def test_every_needed_term_is_recorded_in_a_source_of_the_technique(self):
        rec, ts = sources.recorded_in(), set(sources.technique_sources(TECH))
        for ind, terms in NEEDS.items():
            for t in terms:
                self.assertTrue(set(rec.get(t, [])) & ts, f"{ind} needs {t}")

    def test_states_for_the_technique(self):
        got = {s["id"]: s["state"] for s in sources.derive(TECH)}
        self.assertEqual(got, {"DS0019": "partial", "DS0047": "partial", "DS0039": "background_only",
                               "DS0004": "none", "DS0013": "none", "DS0030": "none", "DS0036": "none", "DS0049": "none"})

    def test_what_is_missing_in_the_partly_available_sources(self):
        by = {s["id"]: s for s in sources.derive(TECH)}
        self.assertEqual(by["DS0019"]["missing"], ["amd:amountRaw"])        # the data has only a logarithm of the amount
        self.assertEqual(by["DS0047"]["missing"], ["amd:Jurisdiction"])     # the data has no country
        self.assertEqual([m["table"] for m in by["DS0047"]["realised_by"]], ["tx"])
        self.assertEqual([m["table"] for m in by["DS0039"]["realised_by"]], ["kyc"])

    def test_a_term_recorded_in_no_source_is_caught(self):
        rec = {k: v for k, v in sources.recorded_in().items() if k != "amd:originator"}
        with mock.patch.object(sources, "recorded_in", return_value=rec):
            problems = sources.check(TECH, NEEDS)
        self.assertTrue(any("amd:originator" in p and "no data source" in p for p in problems), problems)

    def test_a_source_outside_the_technique_is_caught(self):
        rec = dict(sources.recorded_in())
        rec["amd:Invoice"] = ["DS0001"]       # a real typology source, but not one of this technique's
        with mock.patch.object(sources, "recorded_in", return_value=rec):
            problems = sources.check(TECH, NEEDS)
        self.assertTrue(any("amd:Invoice" in p and "none of which" in p for p in problems), problems)

    def test_a_bridged_term_whose_source_no_table_provides_is_caught(self):
        with mock.patch.object(sources, "realises", return_value={}):
            problems = sources.check(TECH, NEEDS)
        self.assertTrue(any("realised by a table" in p for p in problems), problems)


class Verdicts(unittest.TestCase):
    def test_a_gap_is_named_by_data_source(self):
        case = json.load(open(ROOT / "gold" / "cases.json"))["cases"][0]
        same = json.load(open(ROOT / "tests" / "fixtures" / "same_bank.json"))
        for r in case["gold_rows"]:
            r["same_bank"] = same[str(r["tx_id"])]
        rep = {e["id"]: e for e in indicators.report(case["gold_rows"])["indicators"]}
        names = {x["name"] for x in rep["IND02193"]["missing_sources"]}
        self.assertEqual(names, {"Contractual and Invoice Data", "Customs and Border Records", "Trade Documentation"})
        self.assertEqual({x["id"] for x in rep["IND02195"]["missing_sources"]}, {"DS0047"})
        self.assertEqual(rep["IND02191"]["missing_sources"], [])

    def test_the_hand_typed_marks_are_gone_from_the_registry(self):
        reg = json.load(open(paths.REGISTRY))
        self.assertNotIn("data_sources", reg)
        self.assertTrue(all("data_sources" not in i for i in reg["indicators"]))


class BridgeFile(unittest.TestCase):
    def test_the_bridge_moved_out_of_the_aml_vocabulary(self):
        self.assertNotIn("rdfs:subPropertyOf", paths.AML_CORE.read_text())
        self.assertIn("fcd:fromAccount rdfs:subPropertyOf amd:originator", paths.DATA_ALIGNMENT.read_text())
        self.assertEqual(data_ontology.below("amd:originator"), ["fcd:fromAccount"])


class ThroughOntop(unittest.TestCase):
    def test_ontop_reads_the_same_sources_as_the_python_reading(self):
        res = typology.read(force=True)
        self.assertIsNone(res["error"])
        self.assertTrue(res["check"]["ok"], res["check"]["problems"])
        self.assertEqual({s["id"]: s["state"] for s in res["sources"]}, {s["id"]: s["state"] for s in sources.derive(TECH)})
        self.assertIn("8 data sources", typology.sentence(res))


if __name__ == "__main__":
    unittest.main()
