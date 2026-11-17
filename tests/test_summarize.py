"""The investigator's report: five parts in business words, from facts the code builds (no Ontop, no model).

Run:  .venv/bin/python -m unittest tests.test_summarize
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import indicators  # noqa: E402
import summarize as S  # noqa: E402

LEGS = [{"tx_id": 2131053, "ts": "2022-09-04T04:53:00", "from": "812D22980", "to": "811C597B0", "same_bank": False},
        {"tx_id": 2204314, "ts": "2022-09-04T14:05:00", "from": "811C597B0", "to": "811B83280", "same_bank": False},
        {"tx_id": 2282865, "ts": "2022-09-04T23:49:00", "from": "811B83280", "to": "812D22980", "same_bank": False}]


def answer(legs=LEGS, context=True):
    rep = indicators.report(legs)
    return {"asked": [x["tx_id"] for x in legs], "missing_ids": [], "legs": legs, "order": rep["order"], "indicators": rep["indicators"],
            "context": [{"account": "812D22980", "customer_type": "Individual", "industry": None, "tenure": 2299, "pep": False, "risk": "Low"}] if context else [],
            "question": "q", "technique": {"id": "T0039", "name": "Circular Transactions", "tactic": "Layering", "how": "model"}}


NAMES = {i["id"]: i["text"] for i in indicators.registry()["indicators"]}


class Report(unittest.TestCase):
    def test_five_parts_each_with_a_heading(self):
        t = S.template(answer(), NAMES)
        for _, title in S.SECTIONS:
            self.assertIn(f"**{title}**", t)

    def test_the_route_is_told_with_its_accounts(self):
        t = S.template(answer(), NAMES)
        for a in ("812D22980", "811C597B0", "811B83280"):
            self.assertIn(a, t)
        self.assertIn("Payment 1 (transaction 2131053", t)
        self.assertLess(t.index("Payment 1"), t.index("Payment 3"))

    def test_business_words_only(self):
        for ctx in (True, False):
            t = S.template(answer(context=ctx), NAMES)
            self.assertIsNone(S.TECH_WORDS.search(t), S.TECH_WORDS.search(t))
            self.assertIsNone(S.VERDICT_WORDS.search(t))
            self.assertEqual(S.check(t, answer(context=ctx), NAMES), [])

    def test_every_missing_term_has_a_business_label(self):
        reg = indicators.registry()
        terms = {t for i in reg["indicators"] for t in i["needs"]}
        for t in terms:
            if t.startswith("amd:"):
                self.assertIn(t, S.BUSINESS_LABEL, t)

    def test_what_cannot_be_checked_is_named_with_its_missing_information(self):
        t = S.template(answer(), NAMES)
        self.assertIn("IND02192", t)
        self.assertIn("cannot be checked", t)
        self.assertIn("supporting documents", t)
        self.assertIn("legitimate business reason", t)

    def test_a_failing_rule_is_reported_in_business_words(self):
        legs = [dict(LEGS[0]), dict(LEGS[1]), dict(LEGS[2], to="900000001")]          # the last payment does not return to the origin
        t = S.template(answer(legs), NAMES)
        self.assertIn("does not match", t)
        self.assertIn("Rules that were not met", t)

    def test_wrong_time_order_is_explained_as_a_cycle_on_paper(self):
        legs = [{"tx_id": 3286179, "ts": "2022-09-07T01:09:00", "from": "8057E95C0", "to": "8057EA1F0", "same_bank": False},
                {"tx_id": 2843688, "ts": "2022-09-06T03:11:00", "from": "8057EA1F0", "to": "8057EA470", "same_bank": False},
                {"tx_id": 2670088, "ts": "2022-09-05T19:01:00", "from": "8057EA470", "to": "8057E95C0", "same_bank": False}]
        a = answer(legs)
        self.assertEqual(S.cycle_ignoring_time(legs), ["8057EA470", "8057E95C0", "8057EA1F0"])
        t = S.template(a, NAMES)
        self.assertIn("Ignoring the times, these payments do form a cycle", t)
        self.assertIn("in the order they happened they do not link up", t)
        self.assertIn("payment 2 starts at account 8057EA1F0, while the payment before it went to account 8057E95C0", t)
        self.assertEqual(S.check(t, a, NAMES), [])

    def test_a_loop_in_time_order_has_no_wrong_order_story(self):
        t = S.template(answer(), NAMES)
        self.assertNotIn("Ignoring the times", t)
        self.assertIn("first put in the order they happened", t)            # time is always mentioned
        self.assertNotIn("the payments follow each other in time (a rule we added)", t)       # not listed as a check that passed: it holds by construction

    def test_a_chain_is_not_a_cycle_on_paper(self):
        chain = [dict(LEGS[0]), dict(LEGS[1]), dict(LEGS[2], to="900000001")]
        self.assertIsNone(S.cycle_ignoring_time(chain))
        self.assertNotIn("Ignoring the times", S.template(answer(chain), NAMES))

    def test_check_rejects_technical_words_verdicts_and_strange_ids(self):
        a = answer()
        self.assertTrue(any("technical" in p for p in S.check("The mapping shows a loop.", a, NAMES)))
        self.assertTrue(any("verdict" in p for p in S.check("This is money laundering.", a, NAMES)))
        self.assertTrue(any("numbers" in p for p in S.check("Account 811999999 was used.", a, NAMES)))

    def test_model_report_with_all_five_parts_is_kept_and_checked(self):
        a = answer()
        good = {k: "Account 812D22980 sent funds to 811C597B0 and back." if k == "found" else "Fine." for k, _ in S.SECTIONS}
        S.llm.chat, real = (lambda *x, **k: (json.dumps(good), 1.0)), S.llm.chat
        try:
            text, src, problems, _ = S.llm_summary(a, NAMES)
            self.assertEqual((src, problems), ("model", []))
            bad = dict(good, found="The mapping returned three rows.")
            S.llm.chat = lambda *x, **k: (json.dumps(bad), 1.0)
            text2, src2, problems2, _ = S.llm_summary(a, NAMES)
            self.assertEqual(src2, "template")
            self.assertTrue(problems2)
            S.llm.chat = lambda *x, **k: (json.dumps({"found": "only one part"}), 1.0)
            self.assertEqual(S.llm_summary(a, NAMES)[1], "template")
        finally:
            S.llm.chat = real

    def test_rules_off_shows_the_model_report_as_it_is(self):
        a = answer()
        good = {k: "Fine." for k, _ in S.SECTIONS}
        bad = dict(good, found="This looks like suspicious money laundering.")
        S.llm.chat, real = (lambda *x, **k: (json.dumps(bad), 1.0)), S.llm.chat
        try:
            text, src, problems, _ = S.llm_summary(a, NAMES, enforce=False)
            self.assertEqual(src, "model")                         # not replaced by the template
            self.assertIn("suspicious money laundering", text)
            self.assertTrue(any("verdict" in p for p in problems))   # what the rules would have flagged is still reported
            self.assertEqual(S.llm_summary(a, NAMES, enforce=True)[1], "template")
            S.llm.chat = lambda *x, **k: (json.dumps({"found": "only one part"}), 1.0)
            self.assertEqual(S.llm_summary(a, NAMES, enforce=False)[1], "template")      # no usable report at all: still the template
        finally:
            S.llm.chat = real


if __name__ == "__main__":
    unittest.main()
