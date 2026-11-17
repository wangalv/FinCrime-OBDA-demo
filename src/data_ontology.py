"""The ontology Ontop is given for the transaction data: the source vocabulary (ontology/alignment/source_vocabulary.ttl, module 4a), its alignment to the AML terms
(ontology/alignment/aml_data_alignment.ttl, module 4b) and the AML core ontology (ontology/core/aml_core.ttl, module 2), merged into generated/data_ontology_merged.ttl (a generated file; Ontop takes one -t file).

  merged_path()      builds the merged file if needed and returns its path relative to the repo root (Ontop cannot read a path with spaces)
  graph()            the merged graph
  bridges()          {data term: [AML terms it is a subclass / subproperty of]}   as 'fcd:x' / 'amd:y'
  below(term)        the data terms that sit under an AML term (what can answer it)
  available_terms()  the terms the data can speak about: every data term, and every AML term with a data term under it
  all_terms()        every IRI the ontology declares (data and AML), as full IRIs: what a query may use
  expand(terms)      terms plus everything that sits under them, so "amd:originator was used" also marks fcd:fromAccount
"""
import sys
from pathlib import Path

from rdflib import Graph, Namespace, RDFS, URIRef
from rdflib.namespace import OWL, RDF

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

ROOT = paths.ROOT
FCD = Namespace("https://example.org/fincrime-data#")
AMD = Namespace("https://example.org/aml-data#")
PREFIXES = {"fcd": str(FCD), "amd": str(AMD)}
SRC = [paths.SOURCE_VOCABULARY, paths.DATA_ALIGNMENT, paths.AML_CORE]
MERGED = paths.DATA_ONTOLOGY_MERGED
_cache = {}


def short(iri):
    iri = str(iri)
    for p, ns in PREFIXES.items():
        if iri.startswith(ns):
            return f"{p}:{iri[len(ns):]}"
    return iri


def full(term):
    p, _, name = term.partition(":")
    return URIRef(PREFIXES[p] + name)


def graph():
    if "g" not in _cache:
        g = Graph()
        for p in SRC:
            g.parse(p)
        g.bind("fcd", FCD)
        g.bind("amd", AMD)
        _cache["g"] = g
    return _cache["g"]


def merged_path():
    """Write generated/data_ontology_merged.ttl if its content is out of date; return 'generated/data_ontology_merged.ttl'."""
    new = graph().serialize(format="turtle")
    if not MERGED.exists() or MERGED.read_text(encoding="utf-8") != new:
        MERGED.parent.mkdir(exist_ok=True)
        MERGED.write_text(new, encoding="utf-8")
    return str(MERGED.relative_to(ROOT))


def bridges():
    out = {}
    for pred in (RDFS.subClassOf, RDFS.subPropertyOf):
        for s, o in graph().subject_objects(pred):
            if str(s).startswith(PREFIXES["fcd"]) and str(o).startswith(PREFIXES["amd"]):
                out.setdefault(short(s), []).append(short(o))
    return {k: sorted(v) for k, v in out.items()}


def below(term):
    return sorted(d for d, ups in bridges().items() if term in ups)


def _declared(ns):
    g = graph()
    kinds = (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty)
    return {short(s) for k in kinds for s in g.subjects(RDF.type, k) if str(s).startswith(ns)}


def available_terms():
    data = _declared(PREFIXES["fcd"])
    return data | {t for t in _declared(PREFIXES["amd"]) if below(t)}


def all_terms():
    return {str(full(t)) for t in _declared(PREFIXES["fcd"]) | _declared(PREFIXES["amd"])}


def expand(terms):
    out = set(terms)
    for t in terms:
        out.update(below(t))
    return out
