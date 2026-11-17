"""Which queries a technique needs, derived from the Alignment, the AML terms and the data ontology. Nothing here is written per technique.

plan(technique) -> list of query specs, one per entity the needed terms belong to:
  - the terms come from ontology/application/typology_requirements.ttl: what the technique's indicators need (evidence, AML terms) and what it says to show as
    background (data terms);
  - only terms the data can speak about are asked for (data_ontology.available_terms(): a data term, or an AML term with a data term under it
    in the bridge); the others are returned in 'missing' so the page can say so;
  - terms are grouped by their rdfs:domain (an AML transfer term goes in the transfer query, an account term in the account query);
  - the variable names, the identifier of an entity and the name of its query come from mapping/query_vars.ttl.
The queries use the AML terms: Ontop, given the merged data ontology (src/data_ontology.py), rewrites them to the data terms and then to SQL.
A spec: key, entity, label, terms, vars, optional, serves, required, task, vocab, missing.
  serves   the indicator ids that need terms of this query, or ['background']
  required True when the query serves an indicator: if it is rejected or fails, there is nothing to judge, so the run stops.
  vocab    the terms the model is shown for this query: its terms, its entity class and the properties that link the entity to the transfers
"""
import sys
from pathlib import Path

from rdflib import Graph, RDFS, URIRef
from rdflib.namespace import OWL, RDF

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_ontology as D  # noqa: E402
import indicators  # noqa: E402
import paths  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
QV = D.FCD  # the query_vars.ttl predicates (queryVar, identifiedBy, queryKey, mayBeAbsent) live in the fcd namespace


def _qv():
    return Graph().parse(paths.QUERY_VARS)


def query_var(term):
    """The SPARQL variable name of a term ('amd:originator' -> 'from'), from mapping/query_vars.ttl; None when the term has none."""
    v = _qv().value(D.full(term), QV.queryVar)
    return str(v) if v is not None else None


def _supers(g, cls):
    """The class and everything above it (rdfs:subClassOf, transitively), as short names."""
    seen, todo = set(), [cls]
    while todo:
        c = todo.pop()
        if c in seen:
            continue
        seen.add(c)
        todo += [D.short(o) for o in g.objects(D.full(c), RDFS.subClassOf)]
    return seen


def plan(technique=None):
    g, qv = D.graph(), _qv()
    reg = indicators.registry()
    technique = technique or reg["technique"]
    avail = D.available_terms()
    prop = {D.short(s) for k in (OWL.ObjectProperty, OWL.DatatypeProperty) for s in g.subjects(RDF.type, k)}
    domain = {t: D.short(g.value(D.full(t), RDFS.domain)) for t in prop if g.value(D.full(t), RDFS.domain) is not None}

    wanted, missing = {}, {}       # term -> ids that want it ('background' for the background terms)
    for ind in reg["indicators"]:
        for t in ind["needs"]:
            if t in prop and t in avail:
                wanted.setdefault(t, set()).add(ind["id"])
            elif t not in avail:
                missing.setdefault(ind["id"], []).append(t)
    for t in indicators.background(technique):
        if t in prop and t in avail:
            wanted.setdefault(t, set()).add("background")

    def var(term):
        return str(qv.value(D.full(term), QV.queryVar))

    entities = sorted({domain[t] for t in wanted if t in domain})
    # the entity the evidence queries are about (the one with an identifier): the others are tied to it through the properties linking them
    main = next((e for e in entities if qv.value(D.full(e), QV.identifiedBy) is not None and any(i != "background" for t in wanted if domain.get(t) == e for i in wanted[t])), None)
    specs = []
    for ent in entities:
        terms = sorted(t for t in wanted if domain.get(t) == ent)
        ident = qv.value(D.full(ent), QV.identifiedBy)
        key_terms = [D.short(ident)] if ident is not None else []
        key_vars = [var(D.short(ident))] if ident is not None else [var(ent)]
        vars_ = key_vars + [var(t) for t in terms if t not in key_terms]
        optional = [var(t) for t in terms if (D.full(t), QV.mayBeAbsent, None) in qv]
        serves = sorted({i for t in terms for i in wanted[t]} - {"background"}) or ["background"]
        key = str(qv.value(D.full(ent), QV.queryKey) or ent.split(":")[1].lower())
        links = []
        if main and ent != main:       # the properties of the main entity whose range is this entity (or a class above it)
            above = _supers(g, ent)
            links = sorted(t for t in prop if domain.get(t) == main and g.value(D.full(t), RDFS.range) is not None
                           and D.short(g.value(D.full(t), RDFS.range)) in above)
        main_id = D.short(qv.value(D.full(main), QV.identifiedBy)) if main else None
        pairs = (", ".join(f"?{var(t)} ({t})" for t in key_terms + terms) if ident is not None else
                 f"?{key_vars[0]} (the {key} itself), " + ", ".join(f"?{var(t)} ({t})" for t in terms))
        if ent == main or not main:
            task = f"Return one row for each {ent.split(':')[1]} the investigator names, with these variables: {pairs}."
        else:
            either = " UNION ".join("{ ?tx " + l + " ?" + key_vars[0] + " }" for l in links)
            task = (f"Return one row for each distinct {key} that is " + " or ".join(links) + f" of a {main.split(':')[1]} the investigator names, "
                    f"with these variables: {pairs}. Write the either-or as {either}, after ?tx a {main}; {main_id} ?txid.")
        if optional:
            task += f" The variable(s) {', '.join('?' + o for o in optional)} can be absent for some rows, so put them inside OPTIONAL."
        vocab = sorted({*key_terms, *terms, ent, *links} | ({main, main_id} if links else set()))
        specs.append({"key": key, "entity": ent, "label": f"{key.capitalize()} · " + ("background" if serves == ["background"] else ", ".join(serves)),
                      "terms": key_terms + terms, "vars": vars_, "optional": optional, "serves": serves,
                      "required": serves != ["background"], "task": task, "vocab": vocab, "missing": {}})
    specs.sort(key=lambda s: (not s["required"], s["key"]))      # evidence queries first, background after
    if specs:
        specs[0]["missing"] = missing
    return specs


if __name__ == "__main__":
    for s in plan():
        print(s["key"], s["serves"], s["vars"])
        print("  ", s["task"])
        print("   vocab:", s["vocab"])
        print("   missing:", s["missing"])
