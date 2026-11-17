"""The 'Without OBDA' comparison: rows read by code, the model sees only the table, nothing from the OBDA side."""
import json
import unittest

import baseline
import llm


def fake_rows(ids):
    cols = ["tx_id", "ts", "from_account", "to_account"]
    return cols, [{"tx_id": i, "ts": "2022-09-07 07:22:00", "from_account": f"A{i}", "to_account": f"A{i + 1}"} for i in ids]


class Baseline(unittest.TestCase):
    def test_prompt_has_question_and_rows_and_nothing_from_the_obda_side(self):
        s, u = baseline.build("Is this circular? ids 1, 2", *fake_rows([1, 2]))
        self.assertIn("Is this circular? ids 1, 2", u)
        self.assertIn("tx_id,ts,from_account,to_account", u)
        for word in ("IND0", "T0039", "SHACL", "ontology", "amd:", "fcd:", "Circular Transactions"):
            self.assertNotIn(word, s + u)

    def test_parse(self):
        self.assertEqual(baseline.parse('{"answer": "Yes", "found": "x"}'), ("yes", {"found": "x"}))
        self.assertEqual(baseline.parse('{"answer": "maybe", "found": "x", "bogus": "y"}'), (None, {"found": "x"}))
        self.assertEqual(baseline.parse("not json"), (None, {}))

    def test_the_five_parts_are_the_same_as_the_other_side(self):
        import summarize
        self.assertEqual(baseline.SECTIONS, summarize.SECTIONS)
        for key, _ in baseline.SECTIONS:
            self.assertIn(f'"{key}"', baseline.SYSTEM)

    def test_run_with_a_fake_model(self):
        calls = []

        def chat(s, u, **kw):
            calls.append(u)
            return json.dumps({"answer": "no", "found": "no loop"}), 1.26
        r = baseline.run("q", [1, 2, 3], rows_fn=fake_rows, chat_fn=chat)
        self.assertEqual((r["answer"], r["parts"], r["seconds"], r["error"]), ("no", {"found": "no loop"}, 1.3, None))
        self.assertIn("What the records show", r["explanation"])
        self.assertIn("no loop", r["explanation"])
        self.assertEqual(len(calls), 1)

    def test_missing_ids_are_reported(self):
        r = baseline.run("q", [1, 2, 3], rows_fn=lambda ids: fake_rows([1, 2]), chat_fn=lambda *a, **k: ('{"answer":"yes","explanation":"e"}', 1))
        self.assertEqual(r["missing_ids"], [3])

    def test_no_rows_and_model_down_are_errors_not_crashes(self):
        self.assertIn("None of these", baseline.run("q", [9], rows_fn=lambda ids: (["tx_id"], []))["error"])

        def down(*a, **k):
            raise llm.LLMError("down")
        self.assertIn("could not be reached", baseline.run("q", [1], rows_fn=fake_rows, chat_fn=down)["error"])

    def test_real_table_hides_the_answer_columns(self):
        cols, rows = baseline.fetch([2131053, 2204314, 2282865])
        self.assertEqual(len(rows), 3)
        for c in baseline.HIDDEN:
            self.assertNotIn(c, cols)
        self.assertIn("from_account", cols)


if __name__ == "__main__":
    unittest.main()
