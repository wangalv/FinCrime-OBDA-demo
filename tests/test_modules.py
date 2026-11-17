"""The six modules of the semantic layer each hold one kind of knowledge, and src/paths.py is the only place that names the files.

Run:  .venv/bin/python -m unittest tests.test_modules      (reads files only: no Ontop, no model)
"""
import re
import sys
import unittest
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import paths  # noqa: E402

AMD = "https://example.org/aml-data#"
FCD = "https://example.org/fincrime-data#"
ALIGN = "https://example.org/align#"
RR = "http://www.w3.org/ns/r2rml#"


def g(p):
    return Graph().parse(p)


class Files(unittest.TestCase):
    def test_every_named_file_exists(self):
        for name in ("AMLO", "TYPOLOGY_ADAPTER", "TYPOLOGY_CSV_MAPPING", "AML_CORE", "TYPOLOGY_REQUIREMENTS", "SOURCE_VOCABULARY", "DATA_ALIGNMENT",
                     "TX_MAPPING", "CUSTOMER_MAPPING", "LENS", "ONTOP_PROPS", "ONTOP_MEMORY_PROPS", "ONTOP_SH", "SHAPES", "REGISTRY", "QUERY_VARS"):
            self.assertTrue(getattr(paths, name).exists(), name)

    def test_the_old_merged_files_are_gone(self):
        for old in ("aml_layer.ttl", "data_layer.ttl", "typology_needs.ttl", "aml_data_vocab.ttl", "tx_ontology.ttl", "bridge.ttl", "typology_declarations.ttl"):
            self.assertFalse((paths.MAPPING_DIR / old).exists(), old)

    def test_the_old_mapping_directory_holds_only_the_runtime_helper(self):
        self.assertEqual(sorted(p.name for p in paths.MAPPING_DIR.iterdir()), ["query_vars.ttl"])

    def test_the_files_sit_in_their_module_directories(self):
        expect = {"AML_CORE": "ontology/core", "TYPOLOGY_REQUIREMENTS": "ontology/application", "SOURCE_VOCABULARY": "ontology/alignment",
                  "DATA_ALIGNMENT": "ontology/alignment", "TYPOLOGY_ADAPTER": "ontology/external/amltrix", "TX_MAPPING": "mappings/transaction",
                  "CUSTOMER_MAPPING": "mappings/customer", "LENS": "mappings/lenses", "ONTOP_PROPS": "config/ontop", "ONTOP_MEMORY_PROPS": "config/ontop",
                  "ALIGNMENT": "generated", "TYPOLOGY_CSV_MAPPING": "generated", "SHAPES": "validation/shapes", "SKELETONS": "validation/shapes",
                  "REGISTRY": "validation"}
        for name, d in expect.items():
            self.assertEqual(str(getattr(paths, name).parent.relative_to(paths.ROOT)), d, name)

    def test_no_code_builds_a_knowledge_file_path_by_hand(self):
        """Paths to the knowledge, mapping and validation files are written in src/paths.py only (comments and strings in docs are fine)."""
        pat = re.compile(r'ROOT\s*/\s*"(mapping|shapes)"\s*/\s*"')
        offenders = [str(p.relative_to(ROOT)) for d in ("src", "app") for p in (ROOT / d).rglob("*.py") if p.name != "paths.py" and pat.search(p.read_text())]
        self.assertEqual(offenders, [])


class Modules(unittest.TestCase):
    def test_module_2_core_has_terms_and_nothing_else(self):
        core = g(paths.AML_CORE)
        preds = {str(p) for p in core.predicates()}
        self.assertFalse(any(x.startswith(ALIGN) for x in preds), "no requirements in the core ontology")
        self.assertNotIn(str(RDFS.subClassOf), preds)
        self.assertNotIn(str(RDFS.subPropertyOf), preds)
        subjects = {str(s) for s in core.subjects()}
        self.assertTrue(all(s.startswith(AMD) for s in subjects))

    def test_module_3_requirements_have_only_requirement_facts(self):
        req = g(paths.TYPOLOGY_REQUIREMENTS)
        preds = {str(p) for p in req.predicates()}
        self.assertEqual(preds, {ALIGN + "needsTerm", ALIGN + "recordedIn", ALIGN + "backgroundTerm"})

    def test_module_4a_vocabulary_is_data_terms_only(self):
        voc = g(paths.SOURCE_VOCABULARY)
        for s in voc.subjects(RDF.type, None):
            self.assertTrue(str(s).startswith(FCD.rstrip("#")), s)
        self.assertEqual(list(voc.subject_objects(RDFS.subClassOf)), [])
        self.assertEqual(list(voc.subject_objects(RDFS.subPropertyOf)), [])

    def test_module_4b_alignment_is_data_term_below_aml_term(self):
        al = g(paths.DATA_ALIGNMENT)
        self.assertEqual(len(al), 7)
        for s, p, o in al:
            self.assertIn(p, (RDFS.subClassOf, RDFS.subPropertyOf))
            self.assertTrue(str(s).startswith(FCD) and str(o).startswith(AMD), (s, o))

    def test_module_5_each_mapping_file_holds_its_own_tables(self):
        def tables(p):
            m = g(p)
            return {str(m.value(lt, URIRef(RR + "tableName"))) for lt in m.objects(None, URIRef(RR + "logicalTable"))}
        self.assertEqual(tables(paths.TX_MAPPING), {"tx"})
        self.assertEqual(tables(paths.CUSTOMER_MAPPING), {"kyc"})

    def test_every_table_provides_a_data_source(self):
        for p in paths.DATA_MAPPINGS:
            m = g(p)
            self.assertTrue(list(m.subject_objects(URIRef(ALIGN + "realisesSource"))), p.name)

    def test_the_split_kept_every_data_term_in_the_vocabulary_and_the_mapping(self):
        """Each source-vocabulary term that a mapping reads is declared in the vocabulary."""
        declared = {str(s) for k in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty) for s in g(paths.SOURCE_VOCABULARY).subjects(RDF.type, k)}
        for p in paths.DATA_MAPPINGS:
            m = g(p)
            for pred in m.objects(None, URIRef(RR + "predicate")):
                self.assertIn(str(pred), declared, f"{pred} in {p.name}")


if __name__ == "__main__":
    unittest.main()
