"""End to end with the gold SPARQL standing in for the model: Ontop output -> candidate -> SHACL -> per-indicator answer.
Needs Ontop and the real database (about 1.5 minutes).  Run:  .venv/bin/python -m unittest tests.test_pipeline -v
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import pipeline  # noqa: E402
import queries  # noqa: E402

F1 = json.loads((ROOT / "gold" / "cases.json").read_text())["cases"]
F3 = json.loads((ROOT / "gold" / "cases_f3.json").read_text())["cases"]
SAME_BANK = json.loads((ROOT / "tests" / "fixtures" / "same_bank.json").read_text())
F3_BY_F1 = {c["from_f1_case"]: c for c in F3}


class QueriesEqualGold(unittest.TestCase):
    def test_builders_reproduce_the_gold_sparql(self):
        for c in F1:
            self.assertEqual(queries.legs_sparql(c["tx_ids"]), c["gold_sparql"], c["id"])
        for c in F3:
            self.assertEqual(queries.context_sparql(c["tx_ids"]), c["gold_sparql"], c["id"])


class EndToEnd(unittest.TestCase):
    def test_every_f1_case(self):
        for c in F1:
            ans = pipeline.answer(c["tx_ids"])
            gv = c["gold_verdict"]
            e191 = next(e for e in ans["indicators"] if e["id"] == "IND02191")
            self.assertEqual(e191["state"], "held" if gv["structure_matches"] else "not_held", c["id"])
            self.assertEqual(set(e191["failed"]), set(gv["failed"]), c["id"])
            self.assertEqual(ans["order"], gv["order"], c["id"])
            self.assertEqual(ans["missing_ids"], c["missing_ids"], c["id"])
            e195 = next(e for e in ans["indicators"] if e["id"] == "IND02195")
            self.assertEqual(e195["facts"], {"hops": len(c["gold_rows"]),
                                             "interbank_legs": sum(1 for r in c["gold_rows"] if not SAME_BANK[str(r["tx_id"])])}, c["id"])
            if c["id"] in F3_BY_F1:
                self.assertEqual(ans["context"], sorted(F3_BY_F1[c["id"]]["gold_rows"], key=lambda x: x["account"]), c["id"])
            for e in ans["indicators"]:
                if e["id"] not in ("IND02191", "IND02195"):
                    self.assertEqual(e["state"], "cannot_check", c["id"] + " " + e["id"])


class BadQueries(unittest.TestCase):
    def test_missing_column_is_reported_not_ignored(self):
        ids = F1[0]["tx_ids"]
        bad = queries.legs_sparql(ids).replace("?to ?amountLog WHERE", "?amountLog WHERE").replace(" fcd:toAccount ?to ;", "")
        qs = {"legs": bad, "legs_bank": queries.legs_bank_sparql(ids), "context": queries.context_sparql(ids)}
        with self.assertRaises(pipeline.MissingColumns):
            pipeline.answer(ids, qs)


if __name__ == "__main__":
    unittest.main()
