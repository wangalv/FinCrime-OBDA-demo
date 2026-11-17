"""The 'intent' mode: the model writes only intent-level queries (technique + ids); the Alignment decides what Ontop fetches, over one virtual
graph (src/unified.py). The model and the intent analysis are replaced by fakes; Ontop and the database are real (a few seconds each).
Run:  .venv/bin/python -m unittest tests.test_intent_mode
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import demo_run  # noqa: E402
import pivot  # noqa: E402
import prompt  # noqa: E402
import sparql_guard as g  # noqa: E402
import unified  # noqa: E402

IDS = [2131053, 2204314, 2282865]
IDS_TEXT = " ".join(str(i) for i in IDS)
QUESTION = "Please check 2131053, 2204314, 2282865."
EVIDENCE = (unified.PREFIXES + "SELECT DISTINCT ?ind ?txid ?term ?v WHERE { amx:T0039 amlo:isIndicatedBy ?i . ?i skos:prefLabel ?ind ; align:needsTerm ?term . "
            f"VALUES ?txid {{ {IDS_TEXT} }} ?tx a amd:FundsTransfer ; amd:transferId ?txid ; ?term ?v . }}")
BACKGROUND = (unified.PREFIXES + f"SELECT DISTINCT ?account ?term ?v WHERE {{ amx:T0039 align:backgroundTerm ?term . VALUES ?txid {{ {IDS_TEXT} }} "
              "?tx a amd:FundsTransfer ; amd:transferId ?txid . { ?tx amd:originator ?account } UNION { ?tx amd:beneficiary ?account } ?account ?term ?v . }")
INTENT_OK = {"status": "ok", "technique": "T0039", "name": "Circular Transactions", "tactic": "Layering", "clarify": None, "problems": [],
             "supported": True, "reply": "{}", "seconds": 1.0}


def run_with(reply):
    with mock.patch.object(demo_run.intent, "analyse", return_value=INTENT_OK), \
            mock.patch.object(demo_run.llm, "chat", return_value=(reply, 9.0)) as chat:
        return demo_run.run(QUESTION, mode="intent", summary="template"), chat


class Pivot(unittest.TestCase):
    def test_long_rows_become_one_row_per_transfer(self):
        long = [{"ind": "IND02191", "txid": "7", "term": "https://example.org/aml-data#originator", "v": "A"},
                {"ind": "IND02191", "txid": "7", "term": "https://example.org/aml-data#beneficiary", "v": "B"},
                {"ind": "IND02195", "txid": "7", "term": "https://example.org/aml-data#sameInstitution", "v": "false"},
                {"ind": "IND02191", "txid": "8", "term": "https://example.org/aml-data#originator", "v": "B"}]
        rows = pivot.evidence(long)
        self.assertEqual(rows, [{"txid": "7", "from": "A", "to": "B", "sameBank": "false"}, {"txid": "8", "from": "B"}])
        self.assertEqual(pivot.terms_in(long), ["amd:beneficiary", "amd:originator", "amd:sameInstitution"])

    def test_an_absent_value_is_an_absent_column(self):
        long = [{"account": "X", "term": "https://example.org/fincrime-data#customerType", "v": "Individual"}]
        self.assertEqual(pivot.background(long), [{"account": "X", "customerType": "Individual"}])      # no industry for an individual: no row, no OPTIONAL


class IntentGuard(unittest.TestCase):
    def names(self, q, kind="evidence"):
        return [n for n, _ in g.check_intent(q, kind, "T0039", IDS)]

    def test_the_two_queries_pass(self):
        self.assertEqual(self.names(EVIDENCE), [])
        self.assertEqual(self.names(BACKGROUND, "background"), [])

    def test_a_query_that_names_the_data_itself_is_refused(self):
        self.assertEqual(self.names(EVIDENCE.replace("?term ?v .", "amd:originator ?v .")), ["unknown_term"])
        self.assertEqual(self.names(EVIDENCE.replace("?term ?v .", "fcd:fromAccount ?v .")), ["unknown_term"])

    def test_a_query_that_does_not_ask_the_alignment_or_the_technique_is_refused(self):
        self.assertIn("missing_term", self.names(EVIDENCE.replace("align:needsTerm", "skos:altLabel")))
        self.assertIn("missing_term", self.names(EVIDENCE.replace("amx:T0039", "amx:T0001")))
        self.assertIn("ids_differ", self.names(EVIDENCE.replace("2131053", "9999999")))


class IntentPrompt(unittest.TestCase):
    def test_the_prompt_gives_the_technique_and_no_data_terms_to_fetch(self):
        s, u = prompt.build_intent("round and round 2131053", "T0039")
        self.assertIn("Technique: T0039", u)
        for term in ("amd:sameInstitution", "amd:transferTime", "fcd:", "customerType"):
            self.assertNotIn(term, u)
        example = json.loads(u.split("Answer: ", 1)[1].split("\n\nTechnique:", 1)[0])
        self.assertEqual(set(example), {"evidence", "background"})
        self.assertEqual(g.check_intent(example["evidence"], "evidence", "T0001", [1111111, 2222222]), [])      # the example itself passes the checks

    def test_extract(self):
        self.assertEqual(prompt.extract_intent('{"evidence": "A", "background": {"sparql": "B"}}'), {"evidence": "A", "background": "B"})
        self.assertEqual(prompt.extract_intent("no"), {"evidence": None, "background": None})


class UnifiedGraph(unittest.TestCase):
    def test_one_query_joins_the_alignment_with_the_data(self):
        rows, _sql, _t, err = unified.run(EVIDENCE)
        self.assertIsNone(err)
        self.assertEqual(sorted(pivot.terms_in(rows)), ["amd:beneficiary", "amd:originator", "amd:sameInstitution", "amd:transferTime"])
        self.assertEqual(len(rows), 12)                          # 3 transfers x the 4 terms the indicators need that the data answers
        # a term the data cannot answer (amd:Jurisdiction) is asked for by IND02195 and silently returns no value
        self.assertNotIn("amd:Jurisdiction", pivot.terms_in(rows))

    def test_the_background_comes_back_without_an_optional(self):
        rows, _sql, _t, err = unified.run(BACKGROUND)
        self.assertIsNone(err)
        accounts = pivot.background(rows)
        self.assertEqual(len(accounts), 3)
        self.assertTrue(all(a["customerType"] == "Individual" and "industry" not in a for a in accounts))      # an individual has no industry: no value came back, no OPTIONAL was needed


class IntentMode(unittest.TestCase):
    def test_the_answer_is_the_same_as_in_gold_mode(self):
        t, chat = run_with(json.dumps({"evidence": EVIDENCE, "background": BACKGROUND}))
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(t["status"], "ok", t["status_text"])
        self.assertEqual(t["prompt_version"], prompt.PROMPT_VERSION_INTENT)
        gold = demo_run.run(QUESTION, mode="gold", summary="template")
        self.assertEqual([(e["id"], e["state"]) for e in t["answer"]["indicators"]], [(e["id"], e["state"]) for e in gold["answer"]["indicators"]])
        self.assertEqual(t["answer"]["order"], gold["answer"]["order"])
        self.assertEqual(len(t["answer"]["context"]), len(gold["answer"]["context"]))
        self.assertEqual(sorted(t["roles"]["evidence"]["used_terms"]), ["amd:beneficiary", "amd:originator", "amd:sameInstitution", "amd:transferTime"])

    def test_a_query_that_names_the_data_is_stopped_before_ontop(self):
        t, _ = run_with(json.dumps({"evidence": EVIDENCE.replace("?term ?v .", "amd:originator ?v ."), "background": BACKGROUND}))
        self.assertEqual(t["status"], "rejected_by_guard")
        self.assertIsNone(t["roles"]["evidence"]["sql"])

    def test_a_missing_background_query_only_loses_the_background(self):
        t, _ = run_with(json.dumps({"evidence": EVIDENCE}))
        self.assertEqual(t["status"], "ok")
        self.assertEqual(t["answer"]["context"], [])
        self.assertIn("background query rejected", t["status_text"])

    def test_the_graph_lights_the_terms_the_alignment_made_ontop_fetch(self):
        import graph_view
        t, _ = run_with(json.dumps({"evidence": EVIDENCE, "background": BACKGROUND}))
        lit = graph_view.lit(t)
        for term in ("amd:originator", "amd:sameInstitution", "amd:transferTime"):
            self.assertEqual(lit["nodes"][term], "used", term)
        self.assertEqual(lit["nodes"]["amd:Jurisdiction"], "missing")        # asked for by an indicator, not fetched: stays red


if __name__ == "__main__":
    unittest.main()
