"""Offline tests (no model, no Ontop): the SPARQL guard and the prompt.   Run:  .venv/bin/python -m unittest tests.test_guard
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import prompt  # noqa: E402
import queries  # noqa: E402
import queryplan  # noqa: E402
import sparql_guard as g  # noqa: E402

IDS = [2131053, 2204314, 2282865]
V = prompt.ROLES["legs"]["vars"]
OK = queries.legs_sparql(IDS)


class Guard(unittest.TestCase):
    def names(self, q, vars_=V, ids=IDS):
        return [n for n, _ in g.check(q, vars_, ids)]

    def test_the_gold_queries_pass_for_every_p1_role(self):
        for role, f in (("legs", queries.legs_sparql), ("legs_bank", queries.legs_bank_sparql), ("context", queries.context_sparql)):
            self.assertEqual(g.check(f(IDS), prompt.ROLES[role]["vars"], IDS), [], role)

    def test_unknown_term_is_caught_because_ontop_would_return_nothing(self):
        self.assertEqual(self.names(OK.replace("fcd:fromAccount", "fcd:fromAcount")), ["unknown_term"])
        self.assertEqual(self.names(OK.replace("fcd:amountLog", "<http://schema.org/price>")), ["unknown_term"])

    def test_wrong_variable_name(self):
        self.assertIn("missing_output", self.names(OK.replace("?from", "?payer")))

    def test_wrong_ids(self):
        self.assertEqual(self.names(OK.replace("2204314", "2204315")), ["ids_differ"])
        self.assertEqual(self.names(OK.replace("2282865", "")), ["ids_differ"])

    def test_id_followed_by_a_dot_is_still_an_id(self):
        q = OK.replace("VALUES ?txid { 2131053 2204314 2282865 }", "FILTER (?txid = 2131053 || ?txid = 2204314 || ?txid = 2282865.)")
        self.assertNotIn("ids_differ", self.names(q))

    def test_syntax_and_form(self):
        self.assertEqual(self.names("SELECT ?x WHERE { ?x a }"), ["syntax"])
        self.assertEqual(self.names("SELECT * FROM tx_features"), ["syntax"])
        self.assertEqual(self.names("DELETE WHERE { ?s ?p ?o }"), ["syntax"])
        self.assertEqual(self.names("PREFIX fcd: <https://example.org/fincrime-data#> CONSTRUCT {?s a fcd:Account} WHERE {?s a fcd:Account}"),
                         ["query_form"])


class Prompt(unittest.TestCase):
    def test_vocabulary_comes_from_the_ontology_file(self):
        v = prompt.vocabulary()
        for t in ("fcd:Transaction", "fcd:sameBank", "fcd:riskRating"):
            self.assertIn(t, v)
        self.assertEqual(len(prompt.terms()), len(v.splitlines()))

    def test_prompt_names_the_required_variables_and_does_not_leak_the_rules(self):
        s, u = prompt.build("Check 1, 2, 3", "legs")
        self.assertIn("?txid, ?ts, ?from, ?to, ?amountLog", u)
        self.assertNotIn("origin", (s + u).lower())

    def test_the_plan_prompt_names_every_variable_and_the_example_is_valid_json(self):
        specs = queryplan.plan()
        s, u = prompt.build_plan("Check 1, 2, 3", specs)
        for sp in specs:
            self.assertIn(sp["key"] + ":", u)
            for v in sp["vars"]:
                self.assertIn("?" + v, u)
        self.assertIn("Check 1, 2, 3", u)
        example = json.loads(u.split("Answer: ", 1)[1].split("\n\nQuestion:", 1)[0])
        self.assertEqual(set(example), {sp["key"] for sp in specs})
        for word in ("circular", "loop", "cycle", "returns to"):
            self.assertNotIn(word, (s + u.replace("Check 1, 2, 3", "")).lower())        # the rules of the typology are not told to the model

    def test_the_gold_queries_pass_the_checks_of_the_plan(self):
        gold = {"transaction": queries.legs_bank_sparql, "account": queries.context_sparql}
        for sp in queryplan.plan():
            self.assertEqual(g.check(gold[sp["key"]](IDS), sp["vars"], IDS), [], sp["key"])

    def test_extract_plan(self):
        specs = queryplan.plan()
        got = prompt.extract_plan('{"transaction": "A", "account": {"sparql": "B"}}', specs)
        self.assertEqual(got, {"transaction": "A", "account": "B"})
        self.assertEqual(prompt.extract_plan('{"transaction": "A", "account": ""}', specs), {"transaction": "A", "account": None})
        self.assertEqual(prompt.extract_plan("not json", specs), {"transaction": None, "account": None})
        self.assertEqual(prompt.extract_plan('["transaction"]', specs)["transaction"], None)

    def test_extract_sparql(self):
        self.assertEqual(prompt.extract_sparql('{"sparql": "SELECT 1"}'), "SELECT 1")
        self.assertIsNone(prompt.extract_sparql("not json"))
        self.assertIsNone(prompt.extract_sparql('{"query": "x"}'))


if __name__ == "__main__":
    unittest.main()
