"""The AML typology read through Ontop must agree with the registry and indicators.py (slow: two Ontop runs, about 5 s).
Run:  .venv/bin/python -m unittest tests.test_typology
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import indicators  # noqa: E402
import typology  # noqa: E402


class TypologyThroughOntop(unittest.TestCase):
    def test_ontop_agrees_with_the_code(self):
        res = typology.read(force=True)
        self.assertIsNone(res["error"], res["error"])
        self.assertEqual(res["check"]["problems"], [])
        self.assertEqual(res["technique"], "Circular Transactions")
        self.assertEqual(res["tactic"], "Layering")
        self.assertEqual(len(res["indicators"]), 9)

    def test_alignment_file_is_the_generated_one(self):
        old = typology.T.ALIGNMENT.read_text(encoding="utf-8") if typology.T.ALIGNMENT.exists() else None
        typology.build_alignment()
        self.assertEqual(typology.T.ALIGNMENT.read_text(encoding="utf-8"), old)

    def test_a_wrong_registry_need_is_caught(self):
        """If the registry said an indicator needs something else than the alignment says, the check must fail."""
        res = typology.read()
        bad = {**res, "indicators": [dict(e) for e in res["indicators"]]}
        bad["indicators"][0]["missing"] = ["fcd:Invented"]
        self.assertTrue(typology.check(bad)["problems"])


if __name__ == "__main__":
    unittest.main()
