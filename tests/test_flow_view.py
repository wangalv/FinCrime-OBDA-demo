"""The flow diagram: which boxes are done / active / failed at each point of a run (no Ontop, no model).

Run:  .venv/bin/python -m unittest tests.test_flow_view
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import flow_view as F  # noqa: E402


def trace(**kw):
    t = {"question": "q", "ids": [1], "mode": "gold", "typology": None, "roles": {"transaction": {"required": True, "sparql": None, "guard": [], "sql": None, "rows": None, "error": None}},
         "answer": None, "summary": None, "status": "ok"}
    t.update(kw)
    return t


class FlowView(unittest.TestCase):
    def test_idle_before_a_question(self):
        self.assertEqual(F.states(None, None), {})

    def test_ontop_lights_early_for_the_typology_and_again_for_the_sql(self):
        t = trace(typology={"error": None})
        s = F.states(t, "typology")                  # Ontop is reading AMLO + AMLTRIX
        self.assertEqual((s["question"], s["ontop"]), ("done", "active"))
        self.assertEqual(F.input_states(t, "typology", s)["l1"], "on")       # L1 (AMLO + AMLTRIX) is read now
        self.assertEqual(F.input_states(t, "typology", s)["l5"], "")         # the mapping (L5) is not read yet
        t["roles"]["transaction"]["sparql"] = "SELECT 1"
        s = F.states(t, "sparql")
        self.assertEqual((s["sparql"], s["ontop"]), ("active", "done"))      # Ontop stays green between its two runs
        s = F.states(t, "ontop")                      # now Ontop writes the SQL
        self.assertEqual((s["sparql"], s["ontop"]), ("done", "active"))
        self.assertEqual([F.input_states(t, "ontop", s)[k] for k in ("l2", "l4", "l5")], ["on"] * 3)
        t["roles"]["transaction"].update(sql="select", rows=[{}])
        s = F.states(t, "db")
        self.assertEqual((s["ontop"], s["sql"]), ("done", "active"))

    def test_second_query_does_not_unlight_earlier_boxes(self):
        t = trace(typology={"error": None})
        t["roles"]["transaction"].update(sparql="x", sql="s", rows=[{}])
        s = F.states(t, "sparql")                    # the bank query is being written
        self.assertEqual((s["sparql"], s["sql"], s["ontop"]), ("active", "done", "done"))

    def test_tail_boxes_are_one_after_the_other(self):
        t = trace(typology={"error": None}, answer={"indicators": []}, summary={"text": "x"})
        t["roles"]["transaction"].update(sparql="x", sql="s", rows=[{}])
        s = F.states(t, "candidate")                 # the answer exists in the trace, but the chain is only at the candidate / SHACL step
        self.assertEqual((s["shacl"], s.get("result")), ("active", None))
        s = F.states(t, "answer")
        self.assertEqual((s["shacl"], s["result"]), ("done", "done"))

    def test_finished_run_is_all_done(self):
        t = trace(typology={"error": None}, answer={"indicators": []}, summary={"text": "x"})
        t["roles"]["transaction"].update(sparql="x", sql="s", rows=[{}])
        s = F.states(t, "answer")
        self.assertEqual(set(s.values()), {"done"})
        self.assertEqual(set(s), set(F.ORDER))

    def test_failures_are_marked_and_stop_the_chain(self):
        t = trace(typology={"error": None}, status="rejected_by_guard")
        t["roles"]["transaction"].update(sparql="x", guard=[("unknown_term", "x")])
        s = F.states(t, "guard")
        self.assertEqual(s["sparql"], "fail")
        self.assertNotIn("sql", s)
        t = trace(typology={"error": None}, status="ontop_error")
        t["roles"]["transaction"].update(sparql="x", error="boom")
        self.assertEqual(F.states(t, "ontop")["ontop"], "fail")

    def test_every_stage_of_demo_run_has_a_box(self):
        import re
        src = (Path(__file__).resolve().parent.parent / "src" / "demo_run.py").read_text(encoding="utf-8")
        for stage in set(re.findall(r'stage="(\w+)"', src)):
            self.assertIn(stage, F.STAGE_NODE, stage)

    def test_the_six_layers_light_in_the_run_that_reads_them(self):
        t = trace(typology={"error": None})
        s = F.states(t, "sparql")
        inp = F.input_states(t, "sparql", s, mode="intent")
        self.assertEqual((inp["l2"], inp["l3"], inp["l5"], inp["l6"]), ("on", "on", "", ""))       # the model's vocabulary (L2) and the requirements (L3)
        t["roles"]["transaction"].update(sparql="x", sql="s", rows=[{}])
        inp = F.input_states(t, "ontop", F.states(t, "ontop"), mode="intent")
        self.assertEqual([inp[k] for k in ("l1", "l2", "l3", "l4", "l5", "l6")], ["on"] * 5 + [""])   # one graph: the SQL run reads L1 to L5
        t["answer"] = {"indicators": []}
        self.assertEqual(F.input_states(t, "candidate", F.states(t, "candidate"), mode="intent")["l6"], "on")
        t0 = trace()                                                                                  # before the typology is read nothing of L1 or L3 is lit
        inp = F.input_states(t0, "ids", F.states(t0, "ids"), mode="gold")
        self.assertEqual([inp[k] for k in ("l1", "l2", "l3", "l4", "l5", "l6")], [""] * 6)

    def test_layer_table_is_consistent(self):
        self.assertEqual([l[0] for l in F.LAYERS], ["l1", "l2", "l3", "l4", "l5", "l6"])
        for lid, tag, title, what, color, owners in F.LAYERS:
            self.assertTrue(set(owners) <= set(F.ORDER), lid)
        self.assertEqual(set(F.input_states(None, None, {}, None)), {l[0] for l in F.LAYERS})

    def test_render(self):
        page = F.render(trace(typology={"error": None}), "typology", new={"ontop"}, mode="gold")
        self.assertIn("active", page)
        self.assertIn("gold, no model", page)
        for tag in ("L1", "L2", "L3", "L4", "L5", "L6"):
            self.assertIn(tag, page)
        self.assertIn("AMLO + AMLTRIX", page)
        self.assertIn("R2RML + lens", page)
        self.assertIn("semantic and data-access layers", page)


class WithoutObdaLane(unittest.TestCase):
    def test_no_lane_unless_asked_and_the_chain_is_unchanged(self):
        self.assertNotIn("WITHOUT OBDA", F.render(trace(), "ontop", mode="gold"))
        self.assertEqual(F.render(trace(), "ontop", mode="gold"), F.render(trace(), "ontop", mode="gold", lane=None))
        self.assertEqual(F.height("gold"), F.height("gold", None))

    def test_lane_is_drawn_and_makes_the_diagram_taller(self):
        page = F.render(trace(), "ontop", mode="gold", lane="waiting")
        self.assertIn("WITHOUT OBDA", page)
        self.assertIn("reads the table rows", page)
        self.assertGreater(F.height("gold", "waiting"), F.height("gold"))

    def test_lane_states_follow_the_one_call(self):
        self.assertEqual(F.lane_states("waiting"), {})
        self.assertEqual(F.lane_states("active"), {"lq": "done", "lm": "active"})
        self.assertEqual(F.lane_states("done"), {"lq": "done", "lm": "done", "la": "done"})
        self.assertEqual(F.lane_states("fail")["lm"], "fail")
        self.assertEqual(F.lane_states(None), {})

    def test_lane_does_not_change_the_boxes_of_the_chain(self):
        import re
        t = trace(typology={"error": None})
        chain = lambda page: re.findall(r'<g class="(b[^"]*)"', page)[:6]
        self.assertEqual(chain(F.render(t, "typology")), chain(F.render(t, "typology", lane="active")))
        self.assertIn("active", chain(F.render(t, "typology", lane="active"))[2])      # Ontop is still the active box of the chain


if __name__ == "__main__":
    unittest.main()
