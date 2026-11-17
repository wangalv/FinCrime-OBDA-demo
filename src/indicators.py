"""Per-indicator answer for T0039: held / not held / cannot check, from the registry and the SHACL result.

Run with the project venv:  .venv/bin/python src/indicators.py   (prints the report for the first gold loop case)

answerability(ind)  from the registry (needs: ontology/application/typology_requirements.ttl) and the available terms (data terms + bridged AML terms): 'answerable' | 'partial' | 'unanswerable'
report(rows)        one entry per indicator: state, failed rules, missing terms, parts not checked.
States:
  held           every rule of the indicator held ("structure matches the description", nothing stronger)
  not_held       at least one rule failed; the rule ids are listed
  facts_only     no threshold in the typology: the hops and between-bank legs are reported, no verdict (IND02195)
  cannot_check   a term the indicator needs is not in the ontology, or the candidate lacks data a rule needs
Each entry also has missing_sources: the typology data sources the missing terms are recorded in (src/sources.py), so a gap is named as
"needs Contractual and Invoice Data", not only as a term.
"""
import json
import sys
from pathlib import Path

from rdflib import Graph, Namespace, URIRef

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_ontology  # noqa: E402
import paths  # noqa: E402
import loop_check  # noqa: E402
import sources  # noqa: E402

ROOT = paths.ROOT
REGISTRY = paths.REGISTRY
ONTOLOGY = paths.SOURCE_VOCABULARY
FCD = Namespace("https://example.org/fincrime-data#")


NEEDS = paths.TYPOLOGY_REQUIREMENTS
NEEDS_TERM = URIRef("https://example.org/align#needsTerm")
AMX = "https://example.org/amltrix/"


def needs():
    """{indicator id: [data terms it needs, as 'fcd:name', sorted]} from ontology/application/typology_requirements.ttl, the one place this is written down."""
    g = Graph().parse(NEEDS)
    out = {}
    for s, o in g.subject_objects(NEEDS_TERM):
        out.setdefault(str(s)[len(AMX):], []).append(data_ontology.short(o))
    return {k: sorted(v) for k, v in out.items()}


def registry():
    """The JSON registry with each indicator's 'needs' filled in from ontology/application/typology_requirements.ttl. The two must name the same indicators."""
    reg = json.loads(REGISTRY.read_text())
    n = needs()
    ids = {i["id"] for i in reg["indicators"]}
    if set(n) != ids:
        raise ValueError(f"ontology/application/typology_requirements.ttl and {REGISTRY.name} name different indicators: {sorted(set(n) ^ ids)}")
    for i in reg["indicators"]:
        i["needs"] = n[i["id"]]
    return reg


def available_terms():
    """Terms the data can speak about: every data term and every AML term that has a data term under it in the bridge
    (the data terms in ontology/alignment/source_vocabulary.ttl, the alignment in ontology/alignment/aml_data_alignment.ttl, the AML terms in ontology/core/aml_core.ttl). An indicator's needs are checked against this."""
    return data_ontology.available_terms()


def answerability(ind, terms):
    have = [t for t in ind["needs"] if t in terms]
    missing = [t for t in ind["needs"] if t not in terms]
    if not missing:
        return "answerable", missing
    return ("partial" if have else "unanswerable"), missing


M0_TO_ANSWERABILITY = {"yes": "answerable", "partial": "partial", "no": "unanswerable"}


def report(rows):
    reg, terms = registry(), available_terms()
    raw = loop_check.check(rows)           # all rules, all indicators
    failed, warnings = set(raw["failed"]), set(raw["warnings"])
    out = []
    for ind in reg["indicators"]:
        ans, missing = answerability(ind, terms)
        entry = {"id": ind["id"], "answerability": ans, "missing_terms": missing, "not_checked": ind["not_checked"],
                 "missing_sources": sources.sources_of(missing)}
        if ans == "unanswerable" or not ind["rules"]:
            entry.update(state="cannot_check", failed=[], warnings=[])
        else:
            f = sorted(failed & set(ind["rules"]))
            entry["failed"] = f
            entry["warnings"] = sorted(warnings & set(ind["rules"]))
            if ind.get("mode") == "facts_only":
                bank_known = not (set(f) & set(ind["data_rules"]))
                entry["state"] = "facts_only"
                entry["facts"] = {"hops": len(rows),
                                  "interbank_legs": sum(1 for r in rows if r.get("same_bank") is False) if bank_known else None}
            elif set(f) & set(ind["data_rules"]):
                entry["state"] = "cannot_check"
            else:
                entry["state"] = "not_held" if f else "held"
        out.append(entry)
    return {"order": raw["order"], "indicators": out}


def main():
    case = json.load(open(ROOT / "gold" / "cases.json"))["cases"][0]
    rows = json.load(open(ROOT / "tests" / "fixtures" / "same_bank.json"))
    for r in case["gold_rows"]:
        r["same_bank"] = rows[str(r["tx_id"])]
    rep = report(case["gold_rows"])
    print("case", case["id"], "legs in order", rep["order"])
    for e in rep["indicators"]:
        extra = f" failed={e['failed']}" if e["failed"] else ""
        extra += f" facts={e['facts']}" if e.get("facts") else ""
        miss = f" missing={e['missing_terms']}" if e["missing_terms"] else ""
        print(f"  {e['id']}  {e['state']:12} ({e['answerability']}){extra}{miss}")


if __name__ == "__main__":
    main()


def background(technique=None):
    """Terms the Alignment says to show the investigator for the technique, not as evidence: ['fcd:customerType', ...] (sorted)."""
    technique = technique or registry()["technique"]
    g = Graph().parse(NEEDS)
    p = URIRef("https://example.org/align#backgroundTerm")
    return sorted(data_ontology.short(o) for o in g.objects(URIRef(AMX + technique), p))
