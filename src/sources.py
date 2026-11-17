"""Data sources of the AML typology, as a layer of the OBDA knowledge (python side; src/typology.py asks Ontop the same questions and compares).

The typology links data sources (DS0019 Transaction Logs, ...) to a technique, not to an indicator and not to a term. This module holds the rest of
the chain, all of it OUR reading (draft, not reviewed by a domain expert):
  ontology/application/typology_requirements.ttl  "amd:Invoice align:recordedIn amx:DS0013"        which source a term is recorded in
  mappings/transaction/tx_features.r2rml.ttl, customer.r2rml.ttl   "map:TransactionMap align:realisesSource amx:DS0019"   which source a table provides
  ontology/alignment/aml_data_alignment.ttl     the data terms under each AML term               so which terms the database can answer

  recorded_in()        {AML term: [DS ids]}
  realises()           {DS id: [{"map": triples map name, "table": table name}]}
  names()              {DS id: name}                                   from the typology CSV files (vendor/, not modified)
  technique_sources(t) [DS ids] the typology itself lists for the technique
  status(...)          'available' | 'partial' | 'background_only' | 'none' for one source (see its docstring)
  derive(technique)    per source of the technique: terms, covered, missing, realised_by, state
  check(technique, needs)   problems found in the declarations (an empty list is fine)
  sources_of(terms)    the sources (id, name) a set of terms is recorded in: names the gap when an indicator cannot be checked
"""
import csv
import sys
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import RDF

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_ontology  # noqa: E402
import paths  # noqa: E402

ROOT = paths.ROOT
VOCAB = paths.TYPOLOGY_REQUIREMENTS
MAPPINGS = paths.DATA_MAPPINGS
CSV_DIR = paths.TYPOLOGY_CSV_DIR
AMX = "https://example.org/amltrix/"
ALIGN = "https://example.org/align#"
RECORDED_IN = URIRef(ALIGN + "recordedIn")
REALISES = URIRef(ALIGN + "realisesSource")
RR = "http://www.w3.org/ns/r2rml#"
_cache = {}


def _ds_id(iri):
    iri = str(iri)
    return iri[len(AMX):] if iri.startswith(AMX) else iri


def recorded_in():
    """{AML term 'amd:x': [DS ids, sorted]}"""
    g = Graph().parse(VOCAB)
    out = {}
    for s, o in g.subject_objects(RECORDED_IN):
        out.setdefault(data_ontology.short(s), []).append(_ds_id(o))
    return {k: sorted(set(v)) for k, v in out.items()}


def realises():
    """{DS id: [{'map': 'TransactionMap', 'table': 'tx'}]} from the triples maps of the mapping."""
    g = Graph()
    for m in MAPPINGS:
        g.parse(m)
    out = {}
    for tm, ds in g.subject_objects(REALISES):
        lt = g.value(tm, URIRef(RR + "logicalTable"))
        table = str(g.value(lt, URIRef(RR + "tableName"))) if lt is not None else None
        out.setdefault(_ds_id(ds), []).append({"map": str(tm).rsplit("#", 1)[-1], "table": table})
    return {k: sorted(v, key=lambda x: x["map"]) for k, v in out.items()}


def _csv(name):
    with open(CSV_DIR / f"amltrix-ml-1.0-beta.4-{name}.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def names():
    """{DS id: name} for every data source of the typology."""
    if "names" not in _cache:
        _cache["names"] = {r["External ID"]: r["Data Source Name"] for r in _csv("datasources")}
    return _cache["names"]


def technique_sources(technique):
    """The DS ids the typology itself lists for the technique (relationship 'is-identified-in')."""
    key = ("ts", technique)
    if key not in _cache:
        stix = {r["STIX ID"] for r in _csv("techniques") if r["External ID"] == technique}
        ds = {r["STIX ID"]: r["External ID"] for r in _csv("datasources")}
        _cache[key] = sorted(ds[r["Target"]] for r in _csv("relationships")
                             if r["Relationship Type"] == "is-identified-in" and r["Source"] in stix and r["Target"] in ds)
    return _cache[key]


def status(terms, covered, realised_by):
    """One source: 'available' every term recorded in it has a data term under it; 'partial' some do; 'background_only' none does but a table realises
    the source (our KYC table: shown as account background, no AML term is answered from it); 'none' nothing in this database."""
    if terms and len(covered) == len(terms):
        return "available"
    if covered:
        return "partial"
    return "background_only" if realised_by else "none"


def build(source_ids, recorded, realised, covered_terms, nm=None):
    """The per-source table from plain inputs (so the same function serves the python side and the rows Ontop returned)."""
    nm = nm or names()
    out = []
    for ds in source_ids:
        terms = sorted(t for t, srcs in recorded.items() if ds in srcs)
        covered = [t for t in terms if t in covered_terms]
        missing = [t for t in terms if t not in covered_terms]
        rb = realised.get(ds, [])
        out.append({"id": ds, "name": nm.get(ds, ds), "terms": terms, "covered": covered, "missing": missing,
                    "realised_by": rb, "state": status(terms, covered, rb)})
    return out


def derive(technique):
    return build(technique_sources(technique), recorded_in(), realises(), data_ontology.available_terms())


def sources_of(terms):
    """[{'id', 'name', 'terms': [...]}] the data sources the given terms are recorded in, in id order (names the gap for a missing term)."""
    rec, nm = recorded_in(), names()
    by = {}
    for t in terms:
        for ds in rec.get(t, []):
            by.setdefault(ds, []).append(t)
    return [{"id": ds, "name": nm.get(ds, ds), "terms": sorted(ts)} for ds, ts in sorted(by.items())]


def check(technique, needs):
    """Problems in the declarations. needs = {indicator id: [AML terms]}. Empty list: consistent.
    1. every term an indicator needs is recorded in at least one source, and one of them is a source the typology lists for the technique;
    2. every source named (recorded or realised) exists in the typology;
    3. every AML term that has a data term under it is recorded in a source that some table realises (the bridge and 'realises' agree)."""
    problems = []
    rec, real, nm, ts = recorded_in(), realises(), names(), set(technique_sources(technique))
    for ind, terms in sorted(needs.items()):
        for t in terms:
            srcs = rec.get(t)
            if not srcs:
                problems.append(f"{ind} needs {t}, which is recorded in no data source")
            elif not set(srcs) & ts:
                problems.append(f"{ind} needs {t}, recorded only in {srcs}, none of which the typology lists for {technique}")
    for t, srcs in rec.items():
        for ds in srcs:
            if ds not in nm:
                problems.append(f"{t} is recorded in {ds}, which is not a data source of the typology")
    for ds in real:
        if ds not in nm:
            problems.append(f"a table realises {ds}, which is not a data source of the typology")
    for t in sorted(data_ontology.available_terms()):
        if not t.startswith("amd:") or not data_ontology.below(t):
            continue
        if not any(ds in real for ds in rec.get(t, [])):
            problems.append(f"{t} has a data term under it, but none of its sources ({rec.get(t, [])}) is realised by a table")
    return problems


def main():
    import indicators
    tech = indicators.registry()["technique"]
    for s in derive(tech):
        rb = ", ".join(f"{x['table']}" for x in s["realised_by"]) or "-"
        print(f"{s['id']}  {s['state']:16} {s['name'][:44]:44}  recorded {s['terms']}  missing {s['missing']}  realised by {rb}")
    p = check(tech, {i["id"]: i["needs"] for i in indicators.registry()["indicators"]})
    print("check:", "ok" if not p else p)
    return 0 if not p else 1


if __name__ == "__main__":
    sys.exit(main())
