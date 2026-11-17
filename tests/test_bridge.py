"""The bridge from the data ontology up to the AML terms (src/data_ontology.py, ontology/alignment/aml_data_alignment.ttl, ontology/core/aml_core.ttl).
The first class needs no Ontop; the second runs Ontop against the database (a few seconds).
Run:  .venv/bin/python -m unittest tests.test_bridge
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import data_ontology as D  # noqa: E402
import indicators  # noqa: E402
import sparql_guard  # noqa: E402
from ontop_run import run_ontop  # noqa: E402

P = "PREFIX amd: <https://example.org/aml-data#>\nPREFIX fcd: <https://example.org/fincrime-data#>\n"
IDS = "2131053 2204314 2282865"
AML = P + f"SELECT ?txid ?ts ?from ?to ?sameBank WHERE {{ VALUES ?txid {{ {IDS} }} ?tx a amd:FundsTransfer ; amd:transferId ?txid ; amd:transferTime ?ts ; amd:originator ?from ; amd:beneficiary ?to ; amd:sameInstitution ?sameBank . }}"
DATA = P + f"SELECT ?txid ?ts ?from ?to ?sameBank WHERE {{ VALUES ?txid {{ {IDS} }} ?tx a fcd:Transaction ; fcd:txId ?txid ; fcd:timestamp ?ts ; fcd:fromAccount ?from ; fcd:toAccount ?to ; fcd:sameBank ?sameBank . }}"


class Bridge(unittest.TestCase):
    def test_the_bridge_goes_from_a_data_term_up_to_an_aml_term_that_exists(self):
        declared = D._declared(D.PREFIXES["amd"]) | D._declared(D.PREFIXES["fcd"])
        for data, ups in D.bridges().items():
            self.assertTrue(data.startswith("fcd:") and data in declared, data)
            for up in ups:
                self.assertTrue(up.startswith("amd:") and up in declared, up)

    def test_every_need_is_an_aml_term_the_vocabulary_declares(self):
        declared = D._declared(D.PREFIXES["amd"])
        for ind, needs in indicators.needs().items():
            for t in needs:
                self.assertIn(t, declared, f"{ind} needs {t}, which ontology/core/aml_core.ttl does not declare")

    def test_a_term_without_a_bridge_is_not_available(self):
        av = D.available_terms()
        self.assertIn("amd:originator", av)
        self.assertNotIn("amd:Jurisdiction", av)
        self.assertEqual(D.below("amd:originator"), ["fcd:fromAccount"])
        self.assertEqual(D.expand({"amd:originator"}), {"amd:originator", "fcd:fromAccount"})

    def test_the_guard_accepts_both_vocabularies(self):
        self.assertEqual(sparql_guard.check(AML, ["txid", "ts", "from", "to", "sameBank"]), [])
        self.assertEqual(sparql_guard.check(DATA, ["txid", "ts", "from", "to", "sameBank"]), [])
        self.assertEqual([n for n, _ in sparql_guard.check(AML.replace("amd:originator", "amd:origin"), ["from"])], ["unknown_term"])

    def test_the_merged_file_holds_both_vocabularies(self):
        text = (D.ROOT / D.merged_path()).read_text(encoding="utf-8")
        self.assertIn("amd:originator", text)
        self.assertIn("fcd:fromAccount", text)


class OntopRewrites(unittest.TestCase):
    def test_a_query_in_aml_terms_returns_what_the_data_terms_return(self):
        a, _s, _t, ea = run_ontop(AML, ontology=D.merged_path())
        d, _s, _t, ed = run_ontop(DATA, ontology=D.merged_path())
        self.assertIsNone(ea or ed)
        key = lambda r: r["txid"]
        self.assertEqual(sorted(a, key=key), sorted(d, key=key))
        self.assertEqual(len(a), 3)

    def test_without_the_ontology_an_aml_term_silently_returns_nothing(self):
        rows, _s, _t, err = run_ontop(AML)
        self.assertIsNone(err)
        self.assertEqual(rows, [])             # why the ontology must be given, and why the guard checks the terms

    def test_data_terms_still_work_with_and_without_the_ontology(self):
        with_t, *_ = run_ontop(DATA, ontology=D.merged_path())
        without, *_ = run_ontop(DATA)
        self.assertEqual(len(with_t), 3)
        self.assertEqual(sorted(r["txid"] for r in with_t), sorted(r["txid"] for r in without))


if __name__ == "__main__":
    unittest.main()
