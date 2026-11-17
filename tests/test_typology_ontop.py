"""AML typology through Ontop: both routes must give the same rows as rdflib on data/amltrix.ttl (slow: about 25 Ontop runs).

Run:  .venv/bin/python -m unittest tests.test_typology_ontop
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import typology_ontop as T  # noqa: E402


class TypologyThroughOntop(unittest.TestCase):
    def check_route(self, route):
        for qid, text, q_ontop, q_gold in T.QUESTIONS:
            with self.subTest(route=route, question=qid):
                got, _, err = T.run_ontop(q_ontop, route)
                self.assertIsNone(err, err)
                self.assertEqual(sorted(got), sorted(T.gold(q_gold or q_ontop)), text)

    def test_merged_file(self):
        self.check_route("merged")

    def test_csv_mapping(self):
        self.check_route("csv")

    def test_mapping_is_the_generated_one(self):
        """generated/amltrix.r2rml.ttl is generated: it must match what src/build_amltrix_mapping.py would write now."""
        import build_amltrix_mapping as B
        old = B.OUT.read_text(encoding="utf-8")
        try:
            B.main()
            self.assertEqual(B.OUT.read_text(encoding="utf-8"), old)
        finally:
            B.OUT.write_text(old, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
