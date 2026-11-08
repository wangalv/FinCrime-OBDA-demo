"""Per-indicator answer for T0039: held / not held / cannot check, from the registry and the SHACL result.

Run with the project venv:  .venv/bin/python src/indicators.py   (prints the report for the first gold loop case)

answerability(ind)  from the registry and mapping/tx_ontology.ttl: 'answerable' | 'partial' | 'unanswerable'
report(rows)        one entry per indicator: state, failed rules, missing terms, parts not checked.
States:
  held           every rule of the indicator held ("structure matches the description", nothing stronger)
  not_held       at least one rule failed; the rule ids are listed
  facts_only     no threshold in the typology: the hops and between-bank legs are reported, no verdict (IND02195)
  cannot_check   a term the indicator needs is not in the ontology, or the candidate lacks data a rule needs
"""
import json
import sys
from pathlib import Path

from rdflib import Graph, Namespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import loop_check  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "shapes" / "t0039.indicators.json"
ONTOLOGY = ROOT / "mapping" / "tx_ontology.ttl"
FCD = Namespace("https://example.org/fincrime-data#")


def registry():
    return json.loads(REGISTRY.read_text())


def ontology_terms():
    g = Graph().parse(ONTOLOGY)
    return {"fcd:" + str(s)[len(FCD):] for s in set(g.subjects()) if str(s).startswith(str(FCD))}


def answerability(ind, terms):
    have = [t for t in ind["needs"] if t in terms]
    missing = [t for t in ind["needs"] if t not in terms]
    if not missing:
        return "answerable", missing
    return ("partial" if have else "unanswerable"), missing


M0_TO_ANSWERABILITY = {"yes": "answerable", "partial": "partial", "no": "unanswerable"}


def report(rows):
    reg, terms = registry(), ontology_terms()
    raw = loop_check.check(rows)           # all rules, all indicators
    failed, warnings = set(raw["failed"]), set(raw["warnings"])
    out = []
    for ind in reg["indicators"]:
        ans, missing = answerability(ind, terms)
        entry = {"id": ind["id"], "answerability": ans, "missing_terms": missing, "not_checked": ind["not_checked"]}
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
