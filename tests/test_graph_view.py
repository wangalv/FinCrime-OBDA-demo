"""The typology graph: built from the registry, the data ontology and the mapping, lit from a trace (no Ontop, no model: fast).

Run:  .venv/bin/python -m unittest tests.test_graph_view
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import graph_view as G  # noqa: E402
import data_ontology  # noqa: E402
import indicators  # noqa: E402
import queries  # noqa: E402

IDS = [1, 2, 3]


def trace(typology=True, rows=True, answer=True, guard=None):
    roles = {r: {"sparql": f(IDS), "serves": serves, "guard": guard or [], "rows": [{}] if rows else None, "error": None}
             for r, f, serves in (("legs", queries.legs_sparql, ["IND02191"]), ("legs_bank", queries.legs_bank_sparql, ["IND02195"]),
                                  ("context", queries.context_sparql, ["background"]))}
    state = {"IND02191": "held", "IND02195": "facts_only"}
    ans = {"indicators": [{"id": i["id"], "state": state.get(i["id"], "cannot_check")} for i in indicators.registry()["indicators"]]}
    return {"typology": {"error": None} if typology else None, "roles": roles, "answer": ans if answer else None}


class GraphView(unittest.TestCase):
    def test_graph_follows_registry_and_ontology(self):
        g = G.build()
        reg = indicators.registry()
        for ind in reg["indicators"]:
            self.assertIn(ind["id"], g["nodes"])
            for t in ind["needs"]:
                self.assertIn((ind["id"], t, "needs"), g["edges"])
        hidden = {d for ind in reg["indicators"] for t in ind["needs"] for d in data_ontology.below(t)}
        for t in indicators.available_terms():          # every term the data can speak about is a node (or sits behind an AML term that is), and is read from some column
            if t.startswith("amd:") and not any(t in ind["needs"] for ind in reg["indicators"]):
                continue                                  # an AML term nobody needs is not drawn
            if t not in hidden:
                self.assertIn(t, g["nodes"])
            self.assertTrue(g["cols"].get(t), t)

    def test_nothing_is_lit_before_the_chain_starts(self):
        self.assertEqual(G.lit(None), {"nodes": {}, "edges": {}})

    def test_typology_read_lights_indicators_and_marks_missing_terms(self):
        cur = G.lit(trace(typology=True, rows=False, answer=False, guard=["x"]))
        self.assertEqual(cur["nodes"]["technique"], "read")
        self.assertEqual(cur["nodes"]["IND02192"], "read")
        self.assertEqual(cur["nodes"]["amd:originator"], "present")
        self.assertEqual(cur["nodes"]["amd:Jurisdiction"], "missing")
        self.assertNotIn("shacl", cur["nodes"])

    def test_queries_light_terms_then_columns_then_answers(self):
        q = G.lit(trace(rows=False, answer=False))
        self.assertEqual(q["nodes"]["amd:originator"], "used")
        self.assertNotIn("col:tx_features.from_account", q["nodes"])
        r = G.lit(trace(answer=False))
        self.assertEqual(r["nodes"]["col:tx_features.from_account"], "used")
        a = G.lit(trace())
        self.assertEqual(a["nodes"]["IND02191"], "held")
        self.assertEqual(a["nodes"]["IND02192"], "cannot_check")
        self.assertEqual(a["nodes"]["shacl"], "shacl")
        self.assertEqual(a["nodes"]["amd:Jurisdiction"], "missing")     # what the data lacks stays dark red

    def test_rejected_query_lights_nothing(self):
        cur = G.lit(trace(typology=False, rows=False, answer=False, guard=["unknown term"]))
        self.assertEqual(cur["nodes"], {})

    def test_changed_and_render(self):
        before, after = G.lit(trace(rows=False, answer=False)), G.lit(trace())
        new = G.changed(after, before)
        self.assertIn("IND02191", new["nodes"])
        self.assertNotIn("amd:originator", new["nodes"])
        page = G.render(after, new, tactic="Layering", technique="Circular Transactions")
        self.assertIn("s-held", page)
        self.assertIn("new", page)
        self.assertIn("Circular Transactions", page)


if __name__ == "__main__":
    unittest.main()
