"""Tests for the traced run behind the Streamlit page. Gold mode needs Ontop and the database (a few seconds).
Run:  .venv/bin/python -m unittest tests.test_demo_run
"""
import json
import sys
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import demo_run  # noqa: E402
import queries  # noqa: E402


class Ids(unittest.TestCase):
    def test_ids_before_a_full_stop_or_in_chinese_punctuation(self):
        self.assertEqual(demo_run.extract_ids("The ids are 2131053, 2204314, 2282865. Please check."), [2131053, 2204314, 2282865])
        self.assertEqual(demo_run.extract_ids("交易 2131053、2204314、2282865。"), [2131053, 2204314, 2282865])
        self.assertEqual(demo_run.extract_ids("2131053 and 2131053 again"), [2131053])
        self.assertEqual(demo_run.extract_ids("version 1.2345 and 12345.6"), [])


class GoldMode(unittest.TestCase):
    def test_full_trace(self):
        t = demo_run.run("Please check 2131053, 2204314, 2282865.", mode="gold", summary="template")
        self.assertEqual(t["status"], "ok")
        self.assertEqual(set(t["roles"]), {"transaction", "account"})
        self.assertTrue(all(r["sql"] and r["rows"] for r in t["roles"].values()))
        self.assertEqual(t["answer"]["order"], [2131053, 2204314, 2282865])
        self.assertIn("ex:LoopCandidate", t["candidate_turtle"])
        self.assertEqual(t["summary"]["source"], "template")

    def test_no_ids_is_said_not_guessed(self):
        t = demo_run.run("is this a loop?", mode="gold")
        self.assertEqual(t["status"], "no_ids")
        self.assertIsNone(t["answer"])


IDS = [2131053, 2204314, 2282865]
QUESTION = "Please check 2131053, 2204314, 2282865."


def fake_reply(**override):
    """What a model would answer if it wrote the gold queries, as one JSON object; override replaces or removes (None) a key."""
    d = {"transaction": queries.legs_bank_sparql(IDS), "account": queries.context_sparql(IDS)}
    d.update(override)
    return json.dumps({k: v for k, v in d.items() if v is not None})


INTENT_OK = {"status": "ok", "technique": "T0039", "name": "Circular Transactions", "tactic": "Layering", "clarify": None, "problems": [],
             "supported": True, "reply": "{}", "seconds": 1.0}


class IntentStep(unittest.TestCase):
    """The intent step in front of the chain (the model and the typology list are replaced; no Ontop, no database)."""

    def run_with(self, intent_result, question="The money goes round in a circle."):
        with mock.patch.object(demo_run.intent, "analyse", return_value=intent_result) as a, \
                mock.patch.object(demo_run.llm, "chat", side_effect=AssertionError("the SPARQL model must not be called")):
            t = demo_run.run(question, mode="model", summary="template")
        return t, a

    def test_unclear_question_stops_with_the_models_question(self):
        t, a = self.run_with({**INTENT_OK, "status": "clarify", "technique": None, "name": None, "tactic": None, "clarify": "What did you see?"})
        self.assertEqual((t["status"], t["status_text"]), ("clarify", "What did you see?"))
        self.assertEqual(t["roles"], {})

    def test_offered_techniques_stop_the_chain_and_travel_in_the_trace(self):
        opts = [{"id": "T0094.002", "name": "Wash Trading", "tactic": "Layering", "parent": "T0094 Market Manipulation", "text": "x", "supported": False},
                {"id": "T0039", "name": "Circular Transactions", "tactic": "Layering", "parent": None, "text": "y", "supported": True}]
        t, _ = self.run_with({**INTENT_OK, "status": "choose", "technique": None, "name": None, "tactic": None, "clarify": "Which of these do you mean?",
                              "options": opts}, "Ids 2131053, 2204314 are linked somehow.")
        self.assertEqual(t["status"], "choose")
        self.assertEqual([o["id"] for o in t["choices"]], ["T0094.002", "T0039"])
        self.assertIn("Wash Trading", t["status_text"])
        self.assertEqual(t["roles"], {})

    def test_a_pick_skips_the_intent_model_and_goes_on(self):
        with mock.patch.object(demo_run.intent, "analyse", side_effect=AssertionError("a pick must not call the model")), \
                mock.patch.object(demo_run.llm, "chat", side_effect=AssertionError("stops before the SPARQL model")):
            t = demo_run.run("The ids are linked somehow.", mode="model", summary="template", pick="T0039")
        self.assertEqual((t["intent"]["source"], t["intent"]["technique"]), ("investigator", "T0039"))
        self.assertEqual(t["status"], "no_ids")                       # the chain went on to the ids; the question has none
        t = demo_run.run("Ids 2131053, 2204314 are linked.", mode="model", summary="template", pick="T0094.002")
        self.assertEqual(t["status"], "unsupported")
        self.assertIn("T0094.002", t["status_text"])

    def test_another_technique_is_named_and_not_checked(self):
        t, _ = self.run_with({**INTENT_OK, "status": "unsupported", "technique": "T0011", "name": "Money Mule Exploitation",
                              "tactic": "Access Facilitation", "supported": False}, "Ids 2131053, 2204314")
        self.assertEqual(t["status"], "unsupported")
        self.assertIn("T0011 Money Mule Exploitation", t["status_text"])
        self.assertIn("T0039", t["status_text"])

    def test_rejected_and_error_stop(self):
        t, _ = self.run_with({**INTENT_OK, "status": "rejected", "technique": None, "problems": ["T9999 is not a technique of the AML typology"]})
        self.assertEqual(t["status"], "intent_rejected")
        self.assertIn("T9999", t["status_text"])
        t, _ = self.run_with({**INTENT_OK, "status": "error", "problems": ["The model could not be reached: x"]})
        self.assertEqual(t["status"], "intent_error")

    def test_technique_found_but_no_ids_asks_for_ids(self):
        t, _ = self.run_with(INTENT_OK)
        self.assertEqual(t["status"], "no_ids")
        self.assertIn("T0039 Circular Transactions", t["status_text"])
        self.assertIn("ids", t["status_text"])

    def test_gold_mode_has_no_intent_step(self):
        with mock.patch.object(demo_run.intent, "analyse", side_effect=AssertionError("not in gold mode")):
            t = demo_run.run("no ids here", mode="gold", summary="template")
        self.assertEqual(t["status"], "no_ids")
        self.assertIsNone(t["intent"])

    def test_the_flow_diagram_marks_the_sparql_box(self):       # intent analysis is part of the model step; no box of its own
        import flow_view
        t, _ = self.run_with({**INTENT_OK, "status": "clarify", "clarify": "What did you see?"})
        self.assertEqual(flow_view.states(t, "intent")["sparql"], "fail")


class OneModelCall(unittest.TestCase):
    """The model is called once and writes the queries the Alignment asks for (the model is replaced by a fake here)."""

    def run_with(self, reply):
        # the intent step is replaced too (it has its own tests in test_intent.py): these tests are about the SPARQL call
        with mock.patch.object(demo_run.intent, "analyse", return_value=INTENT_OK), \
                mock.patch.object(demo_run.llm, "chat", return_value=(reply, 12.0)) as chat:
            t = demo_run.run(QUESTION, mode="model", summary="template")
        return t, chat

    def test_one_call_for_all_the_queries(self):
        t, chat = self.run_with(fake_reply())
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(t["status"], "ok")
        self.assertTrue(all(r["sql"] and r["rows"] for r in t["roles"].values()))
        self.assertEqual({r["llm_seconds"] for r in t["roles"].values()}, {12.0})
        self.assertEqual(t["llm_seconds"], 12.0)

    def test_queries_in_aml_terms_give_the_same_answer_through_the_bridge(self):
        """The model answers in AML terms (amd:); Ontop, given the merged data ontology, rewrites them to the data terms."""
        P = "PREFIX amd: <https://example.org/aml-data#>\nPREFIX fcd: <https://example.org/fincrime-data#>\n"
        ids = " ".join(str(i) for i in IDS)
        tx = (P + f"SELECT ?txid ?ts ?from ?to ?sameBank WHERE {{ VALUES ?txid {{ {ids} }} ?tx a amd:FundsTransfer ; amd:transferId ?txid ; "
              "amd:transferTime ?ts ; amd:originator ?from ; amd:beneficiary ?to ; amd:sameInstitution ?sameBank . }")
        acc = (P + f"SELECT DISTINCT ?account ?customerType ?industry ?tenure ?pep ?risk WHERE {{ VALUES ?txid {{ {ids} }} "
               "?tx a amd:FundsTransfer ; amd:transferId ?txid . { ?tx amd:originator ?account } UNION { ?tx amd:beneficiary ?account } "
               "?account fcd:customerType ?customerType ; fcd:onboardingTenureDays ?tenure ; fcd:pepFlag ?pep ; fcd:riskRating ?risk . "
               "OPTIONAL { ?account fcd:industry ?industry } }")
        t, _ = self.run_with(json.dumps({"transaction": tx, "account": acc}))
        self.assertEqual(t["status"], "ok", t["status_text"])
        self.assertEqual([len(r["rows"]) for r in t["roles"].values()], [3, 3])
        gold = demo_run.run(QUESTION, mode="gold", summary="template")
        self.assertEqual([(e["id"], e["state"]) for e in t["answer"]["indicators"]], [(e["id"], e["state"]) for e in gold["answer"]["indicators"]])
        self.assertEqual(t["answer"]["order"], gold["answer"]["order"])

    def test_missing_account_query_only_loses_the_background(self):
        t, _ = self.run_with(fake_reply(account=None))
        self.assertEqual(t["status"], "ok")
        self.assertEqual(t["roles"]["account"]["guard"][0][0], "no_sparql")
        self.assertIsNone(t["roles"]["account"]["rows"])
        self.assertEqual(t["answer"]["context"], [])
        self.assertIn("account query rejected", t["status_text"])

    def test_missing_transaction_query_stops_before_the_database(self):
        t, _ = self.run_with(fake_reply(transaction=None))
        self.assertEqual(t["status"], "rejected_by_guard")
        self.assertIsNone(t["roles"]["transaction"]["sql"])

    def test_reply_that_is_not_json_is_rejected_for_all(self):
        t, _ = self.run_with("here are the queries: ...")
        self.assertEqual(t["status"], "rejected_by_guard")
        self.assertTrue(all(r["guard"] and r["guard"][0][0] == "no_sparql" for r in t["roles"].values()))

    def test_events_carry_a_stage_the_flow_diagram_knows(self):
        import flow_view
        with mock.patch.object(demo_run.intent, "analyse", return_value=INTENT_OK), \
                mock.patch.object(demo_run.llm, "chat", return_value=(fake_reply(), 1.0)):
            stages = [e["stage"] for _t, e in demo_run.steps(QUESTION, mode="model", summary="template")]
        self.assertTrue(all(s in flow_view.STAGE_NODE for s in stages), stages)
        self.assertEqual(stages[0], "intent")
        self.assertEqual(stages.count("sparql"), 2)      # "is writing" and "written", once for all the queries


if __name__ == "__main__":
    unittest.main()
