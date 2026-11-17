"""What each indicator needs is written once, in ontology/application/typology_requirements.ttl (no Ontop, no model).
Run:  .venv/bin/python -m unittest tests.test_needs
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import indicators  # noqa: E402
import typology  # noqa: E402


class NeedsHaveOneHome(unittest.TestCase):
    def test_the_json_registry_does_not_hold_needs(self):
        raw = json.loads(indicators.REGISTRY.read_text())
        self.assertTrue(all("needs" not in i for i in raw["indicators"]))

    def test_registry_fills_needs_from_the_ttl(self):
        reg = indicators.registry()
        n = indicators.needs()
        self.assertEqual(len(reg["indicators"]), 9)
        for i in reg["indicators"]:
            self.assertEqual(i["needs"], n[i["id"]])
        self.assertEqual(n["IND02191"], ["amd:FundsTransfer", "amd:beneficiary", "amd:originator", "amd:transferTime"])     # AML terms, not data terms

    def test_the_generated_alignment_follows_the_ttl(self):
        text = typology.build_alignment().read_text(encoding="utf-8")
        for ind, terms in indicators.needs().items():
            self.assertIn(f"amx:{ind} align:needsTerm " + " , ".join(terms) + " .", text)

    def test_a_mismatch_between_ttl_and_json_is_an_error(self):
        real = indicators.needs
        indicators.needs = lambda: {k: v for k, v in real().items() if k != "IND02191"}
        try:
            with self.assertRaises(ValueError):
                indicators.registry()
        finally:
            indicators.needs = real


if __name__ == "__main__":
    unittest.main()
