"""M2 tests: SHACL rules vs gold verdicts, per-indicator report, registry consistency.
Run:  .venv/bin/python -m unittest tests.test_m2 -v     (from the repo root)
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import indicators  # noqa: E402
import loop_check  # noqa: E402
import paths  # noqa: E402

CASES = json.loads((ROOT / "gold" / "cases.json").read_text())["cases"]
SAME_BANK = json.loads((ROOT / "tests" / "fixtures" / "same_bank.json").read_text())
REG = indicators.registry()
BY_ID = {i["id"]: i for i in REG["indicators"]}


def rows_with_bank(case):
    return [dict(r, same_bank=SAME_BANK[str(r["tx_id"])]) for r in case["gold_rows"]]


def leg(i, f, t, minute, bank=False):
    return {"tx_id": i, "ts": f"2022-09-01T00:{minute:02d}:00", "from": f, "to": t, "amount_log": 1.0, "same_bank": bank}


class RegistryAndShapes(unittest.TestCase):
    def test_every_shape_rule_is_in_the_registry_and_back(self):
        in_shapes = set(re.findall(r'sh:message\s+"\[(\w+)\]', paths.SHAPES.read_text()))
        in_registry = {r for i in REG["indicators"] for r in i["rules"]}
        # rules that belong to the leg and candidate scaffolding, not to an indicator
        scaffolding = {"leg_complete"}
        self.assertEqual(in_shapes - scaffolding, in_registry)

    def test_every_rule_has_a_source_and_a_text(self):
        for i in REG["indicators"]:
            for r in i["rules"]:
                self.assertIn(r, REG["rule_info"], r)
                self.assertIn(REG["rule_info"][r]["source"], REG["rule_source_legend"], r)

    def test_computed_answerability_matches_the_m0_marks(self):
        terms = indicators.available_terms()
        for ind in REG["indicators"]:
            ans, _ = indicators.answerability(ind, terms)
            self.assertEqual(ans, indicators.M0_TO_ANSWERABILITY[ind["m0_mark"]], ind["id"])

    def test_nine_indicators_and_a_skeleton_for_each_unanswerable_one(self):
        self.assertEqual(len(REG["indicators"]), 9)
        text = paths.SKELETONS.read_text()
        for ind in REG["indicators"]:
            if ind["m0_mark"] == "no":
                self.assertIn("ex:implementsIndicator amx:" + ind["id"], text)


class AgainstGold(unittest.TestCase):
    def test_ind02191_agrees_with_every_gold_verdict(self):
        rules = set(BY_ID["IND02191"]["rules"])
        for c in CASES:
            out = loop_check.check(c["gold_rows"], rules)
            gv = c["gold_verdict"]
            self.assertEqual(out["structure_matches"], gv["structure_matches"], c["id"])
            self.assertEqual(set(out["failed"]), set(gv["failed"]), c["id"])
            self.assertEqual(out["order"], gv["order"], c["id"])

    def test_ind02195_reports_facts_matching_a_plain_count(self):
        for c in CASES:
            rows = rows_with_bank(c)
            e = next(x for x in indicators.report(rows)["indicators"] if x["id"] == "IND02195")
            self.assertEqual(e["state"], "facts_only", c["id"])
            self.assertEqual(e["facts"], {"hops": len(rows), "interbank_legs": sum(1 for r in rows if not r["same_bank"])}, c["id"])

    def test_ind02195_without_bank_data_reports_hops_only(self):
        e = next(x for x in indicators.report(CASES[0]["gold_rows"])["indicators"] if x["id"] == "IND02195")
        self.assertEqual(e["facts"], {"hops": 3, "interbank_legs": None})


class EveryRuleCanFire(unittest.TestCase):
    def failed(self, legs, ind="IND02191"):
        return set(loop_check.check(legs, set(BY_ID[ind]["rules"]))["failed"])

    def test_account_paying_twice_is_allowed(self):
        legs = [leg(1, "A", "B", 1), leg(2, "B", "C", 2), leg(3, "C", "B", 3), leg(4, "B", "A", 4)]
        self.assertEqual(self.failed(legs), set())

    def test_round_trip_counts(self):
        self.assertEqual(self.failed([leg(1, "A", "B", 1), leg(2, "B", "A", 2)]), set())

    def test_one_account_only(self):
        self.assertEqual(self.failed([leg(1, "A", "A", 1)]), {"at_least_2_accounts"})

    def test_self_transfer_leg_is_not_excluded(self):
        # the typology does not exclude a transfer from an account to itself
        legs = [leg(1, "A", "A", 1), leg(2, "A", "B", 2), leg(3, "B", "A", 3)]
        self.assertTrue(loop_check.check(legs)["structure_matches"])

    def test_same_minute_legs_are_ordered_by_tx_id(self):
        legs = [leg(3, "C", "A", 1), leg(1, "A", "B", 1), leg(2, "B", "C", 1)]
        out = loop_check.check(legs)
        self.assertEqual(out["order"], [1, 2, 3])
        self.assertTrue(out["structure_matches"])

    def test_same_bank_leg_changes_ind02195_facts_not_ind02191(self):
        legs = [leg(1, "A", "B", 1), leg(2, "B", "C", 2, bank=True), leg(3, "C", "A", 3)]
        rep = {e["id"]: e for e in indicators.report(legs)["indicators"]}
        self.assertEqual(rep["IND02191"]["state"], "held")
        self.assertEqual(rep["IND02195"]["state"], "facts_only")
        self.assertEqual(rep["IND02195"]["facts"], {"hops": 3, "interbank_legs": 2})


if __name__ == "__main__":
    unittest.main()
