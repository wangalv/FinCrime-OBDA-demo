"""The queries a technique needs come from the Alignment and the data ontology (no Ontop, no model).
Run:  .venv/bin/python -m unittest tests.test_queryplan
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import indicators  # noqa: E402
import queryplan  # noqa: E402


class QueryPlan(unittest.TestCase):
    def setUp(self):
        self.specs = {s["key"]: s for s in queryplan.plan()}

    def test_one_query_per_entity_evidence_first(self):
        self.assertEqual([s["key"] for s in queryplan.plan()], ["transaction", "account"])
        self.assertTrue(self.specs["transaction"]["required"])
        self.assertFalse(self.specs["account"]["required"])

    def test_the_transaction_query_is_what_the_indicators_need_that_the_data_has(self):
        sp = self.specs["transaction"]
        self.assertEqual(sp["serves"], ["IND02191", "IND02195"])
        self.assertEqual(sorted(sp["vars"]), sorted(["txid", "ts", "from", "to", "sameBank"]))
        self.assertEqual(sorted(sp["terms"]), sorted(["amd:transferId", "amd:transferTime", "amd:originator", "amd:beneficiary", "amd:sameInstitution"]))
        self.assertEqual(sp["vars"][0], "txid")                       # the key first
        needed = {t for i in indicators.registry()["indicators"] for t in i["needs"]}
        self.assertTrue(set(sp["terms"]) <= needed | {"amd:transferId"})   # nothing the Alignment did not ask for (the identifier is the key)

    def test_terms_the_data_ontology_lacks_are_reported_not_asked_for(self):
        sp = self.specs["transaction"]
        self.assertNotIn("amd:Jurisdiction", sp["terms"])
        self.assertEqual(sp["missing"]["IND02195"], ["amd:Jurisdiction"])
        self.assertNotIn("IND02191", sp["missing"])

    def test_the_account_query_is_the_background_the_alignment_declares(self):
        sp = self.specs["account"]
        self.assertEqual(sp["serves"], ["background"])
        self.assertEqual(sorted(sp["terms"]), sorted(indicators.background()))
        self.assertEqual(sp["vars"][0], "account")
        self.assertEqual(sp["optional"], ["industry"])
        self.assertIn("OPTIONAL", sp["task"])
        self.assertIn("amd:beneficiary or amd:originator", sp["task"])    # tied to the named transfers through the ontology's range (fcd:Account is below amd:Account)

    def test_a_term_dropped_from_the_alignment_drops_out_of_the_query(self):
        real = indicators.registry
        def without_bank():
            reg = real()
            for i in reg["indicators"]:
                i["needs"] = [t for t in i["needs"] if t != "amd:sameInstitution"]
            return reg
        indicators.registry = without_bank
        try:
            sp = {s["key"]: s for s in queryplan.plan()}["transaction"]
        finally:
            indicators.registry = real
        self.assertNotIn("sameBank", sp["vars"])
        self.assertEqual(sp["serves"], ["IND02191"])


if __name__ == "__main__":
    unittest.main()
