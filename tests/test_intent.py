"""Intent analysis: what the model may say is checked against the typology's list (no Ontop, no model: the list and the model are faked).

Run:  .venv/bin/python -m unittest tests.test_intent
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import intent  # noqa: E402

CAT = {"error": None, "seconds": 0.1, "tactics": ["Access Facilitation", "Layering"], "sparql": "",
       "tactic_text": {"Layering": "Layering hides the origin of funds.", "Access Facilitation": "Access facilitation opens entry points."},
       "techniques": {"T0039": {"name": "Circular Transactions", "tactics": ["Layering"], "parent": None, "text": "Funds cycle back to the origin."},
                      "T0011": {"name": "Money Mule Exploitation", "tactics": ["Access Facilitation"], "parent": None},
                      "T0011.002": {"name": "Crypto ATM Mule", "tactics": ["Access Facilitation"], "parent": "T0011"},
                      "T0094": {"name": "Market Manipulation", "tactics": ["Layering"], "parent": None},
                      "T0094.002": {"name": "Wash Trading", "tactics": ["Layering"], "parent": "T0094", "text": "The same asset is traded back and forth."},
                      "T0099": {"name": "Two Homes", "tactics": ["Access Facilitation", "Layering"], "parent": None}}}


def reply(tactic="Layering", technique="T0039", clarify=None, candidates=None):
    return json.dumps({"tactic": tactic, "technique": technique, "clarify": clarify, "candidates": candidates or []})


class Parse(unittest.TestCase):
    def test_object_with_three_keys(self):
        self.assertEqual(intent.parse(reply()), {"tactic": "Layering", "technique": "T0039", "clarify": None, "candidates": []})

    def test_null_words_and_blanks_are_none(self):
        p = intent.parse(json.dumps({"tactic": "null", "technique": " ", "clarify": "What did you see?"}))
        self.assertEqual(p, {"tactic": None, "technique": None, "clarify": "What did you see?", "candidates": []})

    def test_not_an_object(self):
        self.assertIsNone(intent.parse("T0039"))
        self.assertIsNone(intent.parse("[1]"))
        self.assertIsNone(intent.parse(None))


class Candidates(unittest.TestCase):
    """When the question does not point to one technique the model may list up to three; the investigator chooses."""

    def j(self, **kw):
        return intent.judge(intent.parse(reply(tactic=None, technique=None, **kw)), CAT)

    def test_parse_candidates(self):
        self.assertEqual(intent.parse(reply(candidates=["t0039", " T0011 ", 5]))["candidates"], ["T0039", "T0011"])
        self.assertEqual(intent.parse('{"tactic": null, "technique": null}')["candidates"], [])
        self.assertEqual(intent.parse('{"candidates": "T0039"}')["candidates"], [])

    def test_valid_candidates_become_options(self):
        r = self.j(candidates=["T0094.002", "T0039"])
        self.assertEqual(r["status"], "choose")
        self.assertEqual([o["id"] for o in r["options"]], ["T0094.002", "T0039"])
        wash, circ = r["options"]
        self.assertEqual((wash["name"], wash["tactic"], wash["parent"], wash["supported"]), ("Wash Trading", "Layering", "T0094 Market Manipulation", False))
        self.assertEqual((circ["supported"], circ["text"]), (True, "Funds cycle back to the origin."))
        self.assertEqual(r["clarify"], "Which of these do you mean?")

    def test_invented_ids_are_dropped_duplicates_removed_and_three_at_most(self):
        r = self.j(candidates=["T9999", "T0039", "T0039", "T0011", "T0094", "T0099"])
        self.assertEqual([o["id"] for o in r["options"]], ["T0039", "T0011", "T0094"])
        self.assertEqual(self.j(candidates=["T9999"])["status"], "clarify")        # nothing real is left: back to a question

    def test_a_named_technique_wins_over_candidates(self):
        r = intent.judge(intent.parse(reply(candidates=["T0011"])), CAT)
        self.assertEqual((r["status"], r["technique"], r["options"]), ("ok", "T0039", []))

    def test_text_for_the_investigator_names_each_option_and_whether_it_can_be_checked(self):
        t = intent.stop_text(self.j(candidates=["T0094.002", "T0039"], clarify="Which one?"))
        self.assertTrue(t.startswith("Which one?"))
        self.assertIn("**T0094.002 Wash Trading** (Layering, sub-technique of T0094 Market Manipulation)", t)
        self.assertIn("cannot check it", t)
        self.assertIn("this demo can check it", t)
        self.assertIn("the investigator is asked to choose: T0094.002, T0039", intent.sentence(self.j(candidates=["T0094.002", "T0039"])))

    def test_a_pick_needs_no_model(self):
        with mock.patch.object(intent.llm, "chat", side_effect=AssertionError("no model call for a pick")):
            ok = intent.from_pick("T0039", CAT)
            no = intent.from_pick("T0094.002", CAT)
            bad = intent.from_pick("T9999", CAT)
        self.assertEqual((ok["status"], ok["source"], ok["supported"]), ("ok", "investigator", True))
        self.assertEqual((no["status"], no["parent"]), ("unsupported", "T0094 Market Manipulation"))
        self.assertEqual(bad["status"], "rejected")
        self.assertIn("the investigator chose T0039", intent.sentence(ok))
        self.assertEqual(intent.from_pick("T0039", {**CAT, "error": "boom"})["status"], "error")


class Judge(unittest.TestCase):
    def j(self, **kw):
        return intent.judge(intent.parse(reply(**kw)), CAT)

    def test_supported_technique(self):
        r = self.j()
        self.assertEqual((r["status"], r["technique"], r["name"], r["supported"]), ("ok", "T0039", "Circular Transactions", True))

    def test_id_case_is_forgiven(self):
        self.assertEqual(self.j(technique="t0039")["status"], "ok")

    def test_real_technique_this_demo_cannot_check(self):
        r = self.j(tactic="Access Facilitation", technique="T0011")
        self.assertEqual((r["status"], r["supported"]), ("unsupported", False))

    def test_sub_technique_is_found_with_its_parent(self):
        r = self.j(technique="T0094.002")
        self.assertEqual((r["status"], r["name"], r["parent"], r["supported"]), ("unsupported", "Wash Trading", "T0094 Market Manipulation", False))
        self.assertIn("sub-technique of T0094 Market Manipulation", intent.sentence(r))
        self.assertIn("sub-technique of T0094 Market Manipulation", intent.stop_text(r))
        self.assertIsNone(self.j()["parent"])

    def test_technique_not_in_the_typology_is_rejected(self):
        r = self.j(technique="T9999")
        self.assertEqual(r["status"], "rejected")
        self.assertIn("T9999", r["problems"][0])

    def test_technique_under_the_wrong_tactic_is_rejected(self):
        r = self.j(tactic="Access Facilitation", technique="T0039")
        self.assertEqual(r["status"], "rejected")
        self.assertIn("Layering", r["problems"][0])
        self.assertEqual(self.j(tactic="Access Facilitation", technique="T0099")["status"], "unsupported")   # listed under two tactics

    def test_missing_tactic_is_rejected(self):
        self.assertEqual(self.j(tactic=None)["status"], "rejected")

    def test_no_technique_means_clarify(self):
        r = self.j(tactic=None, technique=None, clarify="What did you see?")
        self.assertEqual((r["status"], r["clarify"]), ("clarify", "What did you see?"))
        self.assertIn("could not tell", self.j(tactic=None, technique=None)["clarify"])      # the model gave no question: code supplies one

    def test_unparsable_reply_is_rejected(self):
        self.assertEqual(intent.judge(None, CAT)["status"], "rejected")


class Build(unittest.TestCase):
    def test_prompt_lists_every_technique_under_its_tactic_and_nothing_else(self):
        s, u = intent.build("money goes round", CAT)
        for tid, t in CAT["techniques"].items():
            self.assertIn(f"{tid} {t['name']}", u)
        self.assertIn("Layering - Layering hides the origin of funds.:", u)        # a sentence about the tactic
        self.assertIn("\n    T0094.002 Wash Trading", u)                               # a sub-technique is indented under its technique
        self.assertIn("\n  T0094 Market Manipulation\n    T0094.002", u)
        self.assertIn('Question: "money goes round"', u)
        self.assertNotIn("SELECT", u + s)             # no query is asked for here


class FirstSentence(unittest.TestCase):
    def test_markdown_and_length(self):
        self.assertEqual(intent.first_sentence("**Layering** hides funds. It has more. And more."), "Layering hides funds.")
        self.assertTrue(len(intent.first_sentence("word " * 200)) < 240)


class Analyse(unittest.TestCase):
    def run_with(self, cat=CAT, chat=None):
        with mock.patch.object(intent, "catalog", return_value=cat), mock.patch.object(intent.llm, "chat", **(chat or {"return_value": (reply(), 2.0)})) as c:
            return intent.analyse("q"), c

    def test_ok(self):
        r, c = self.run_with()
        self.assertEqual((r["status"], r["technique"], r["seconds"]), ("ok", "T0039", 2.0))
        self.assertEqual(c.call_count, 1)

    def test_typology_not_readable(self):
        r, c = self.run_with(cat={**CAT, "error": "boom"})
        self.assertEqual(r["status"], "error")
        self.assertIn("boom", r["problems"][0])
        self.assertEqual(c.call_count, 0)

    def test_model_not_reachable(self):
        r, _ = self.run_with(chat={"side_effect": intent.llm.LLMError("down")})
        self.assertEqual(r["status"], "error")

    def test_sentence_for_every_status(self):
        for st in ("ok", "unsupported", "clarify", "rejected", "error"):
            r = {"status": st, "technique": "T0039", "name": "x", "tactic": "Layering", "supported": st == "ok", "problems": ["p"], "clarify": "c"}
            self.assertTrue(intent.sentence(r).startswith("Intent"))


if __name__ == "__main__":
    unittest.main()
