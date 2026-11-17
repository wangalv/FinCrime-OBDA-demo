"""One virtual graph over the AML typology and the transaction data, for the 'intent' mode of the demo.

Ontop is given ONE mapping and ONE ontology, so the files for both sides are merged into generated/ files (generated, git-ignored):
  mapping   mappings/transaction/tx_features.r2rml.ttl + mappings/customer/customer.r2rml.ttl + generated/amltrix.r2rml.ttl   (the lens of the transaction data is passed as -v by ontop_run)
  ontology  ontology/amlo.ttl (AML framework) + ontology/external/amltrix/typology_adapter.ttl + the Alignment facts (generated/typology_alignment.ttl, generated from
            ontology/application/typology_requirements.ttl) + the source vocabulary, the alignment and the AML core ontology (src/data_ontology.py)
  props     the JDBC properties of the transaction database, plus ontop.inferDefaultDatatype (the AMLTRIX mapping reads CSV files with read_csv())
Both mappings run on the same DuckDB connection; the AMLTRIX one reads the CSV files, the other reads the tables.
With it a single SPARQL query can join what an indicator needs (typology + Alignment) with the data, for example
    amx:IND02191 align:needsTerm ?term .  ?tx a amd:FundsTransfer ; ?term ?v        (the predicate is a variable bound by the Alignment)
Ontop rewrites ?term by the bridge (amd:originator -> fcd:fromAccount) and unfolds it by the mapping into SQL.

paths()  builds the files if out of date and returns {'mapping', 'ontology', 'props'} (relative to the repo root: Ontop cannot read a path with spaces)
run(sparql)   run_ontop over the unified graph: (rows, sql, seconds, error)
"""
import sys
from pathlib import Path

from rdflib import Graph

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_ontology  # noqa: E402
import ontop_run  # noqa: E402
import paths as P  # noqa: E402   (this module has its own paths() function)
import typology  # noqa: E402

ROOT = P.ROOT
GEN = P.GEN
MAPPING = P.UNIFIED_MAPPING
ONTOLOGY = P.UNIFIED_ONTOLOGY
PROPS = P.UNIFIED_PROPS
PREFIXES = """PREFIX amlo: <https://example.org/amlo#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX align: <https://example.org/align#>
PREFIX amx: <https://example.org/amltrix/>
PREFIX amd: <https://example.org/aml-data#>
PREFIX fcd: <https://example.org/fincrime-data#>
"""


def _write(path, text):
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        GEN.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")


def paths():
    typology.build_alignment()
    m = Graph()
    for p in (*P.DATA_MAPPINGS, P.TYPOLOGY_CSV_MAPPING):
        m.parse(p)
    _write(MAPPING, m.serialize(format="turtle"))
    o = Graph()
    for p in (P.AMLO, P.TYPOLOGY_ADAPTER, P.ALIGNMENT):
        o.parse(p)
    o += data_ontology.graph()
    _write(ONTOLOGY, o.serialize(format="turtle"))
    _write(PROPS, P.ONTOP_PROPS.read_text(encoding="utf-8") + "\nontop.inferDefaultDatatype=true\n")
    rel = P.rel
    return {"mapping": rel(MAPPING), "ontology": rel(ONTOLOGY), "props": rel(PROPS)}


def run(sparql, normalize=False):
    p = paths()
    return ontop_run.run_ontop(sparql, normalize=normalize, ontology=p["ontology"], mapping=p["mapping"], props=p["props"])
