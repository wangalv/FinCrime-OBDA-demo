"""Candidate assembly and SHACL check for T0039 (rules of all indicators in validation/shapes/t0039.shapes.ttl).

Run with the project venv:  .venv/bin/python src/loop_check.py   (checks all gold cases)

assemble(rows)  rows = list of dicts {tx_id, ts (ISO string), from, to, same_bank (optional), amount_log (optional)}, e.g. what Ontop returns.
                Code, not the model, sorts the legs by (ts, tx_id) and sets the origin to the first leg's payer.
check(rows)     builds the RDF candidate, validates it with pyshacl against validation/shapes/t0039.shapes.ttl and returns
                {"structure_matches": bool, "failed": [rule ids], "warnings": [rule ids], "order": [tx_ids]}.
"""
import json
import re
import sys
from pathlib import Path

from pyshacl import validate
from rdflib import RDF, Graph, Literal, Namespace, URIRef
from rdflib.namespace import SH, XSD

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

ROOT = paths.ROOT
SHAPES = paths.SHAPES
EX = Namespace("https://example.org/rules#")
ACCOUNT = "https://example.org/account/"
TX = "https://example.org/transaction/"

_shapes = None


def assemble(rows):
    """Return (graph, ordered tx ids). The candidate node is ex:candidate."""
    legs = sorted(rows, key=lambda r: (r["ts"], r["tx_id"]))
    g = Graph()
    cand = URIRef("https://example.org/candidate")
    g.add((cand, RDF.type, EX.LoopCandidate))
    if legs:
        g.add((cand, EX.origin, URIRef(ACCOUNT + legs[0]["from"])))
    for i, r in enumerate(legs, start=1):
        leg = URIRef(TX + str(r["tx_id"]))
        g.add((cand, EX.leg, leg))
        g.add((leg, RDF.type, EX.Leg))
        g.add((leg, EX.seq, Literal(i, datatype=XSD.integer)))
        g.add((leg, EX["from"], URIRef(ACCOUNT + r["from"])))
        g.add((leg, EX.to, URIRef(ACCOUNT + r["to"])))
        g.add((leg, EX.at, Literal(r["ts"], datatype=XSD.dateTime)))
        if r.get("amount_log") is not None:      # no rule reads the amount; the query asks for it only if the Alignment says an indicator needs it
            g.add((leg, EX.amountLog, Literal(float(r["amount_log"]), datatype=XSD.double)))
        if r.get("same_bank") is not None:
            g.add((leg, EX.sameBank, Literal(bool(r["same_bank"]), datatype=XSD.boolean)))
    return g, [r["tx_id"] for r in legs]


def check(rows, rules=None):
    """rules: optional set of rule ids to keep (one indicator's rules, see validation/indicator_registry.json); default all."""
    global _shapes
    if _shapes is None:
        _shapes = Graph().parse(SHAPES)
    g, order = assemble(rows)
    conforms, rgraph, _ = validate(g, shacl_graph=_shapes, inference="none", advanced=True)
    failed, warnings = set(), set()
    for res in rgraph.subjects(RDF.type, SH.ValidationResult):
        msg = str(rgraph.value(res, SH.resultMessage))
        sev = rgraph.value(res, SH.resultSeverity)
        m = re.match(r"\[(\w+)\]", msg)
        rule = m.group(1) if m else msg
        if rules is not None and rule not in rules:
            continue
        (warnings if sev == SH.Warning else failed).add(rule)
    return {"structure_matches": not failed, "failed": sorted(failed), "warnings": sorted(warnings), "order": order}


def main():
    reg = json.load(open(paths.REGISTRY))
    rules191 = set(next(i for i in reg["indicators"] if i["id"] == "IND02191")["rules"])
    cases = json.load(open(ROOT / "gold" / "cases.json"))["cases"]
    bad = 0
    print(f"{'case':26} {'gold':8} {'shacl':8} agree  failed rules (SHACL)")
    for c in cases:
        rows = c["gold_rows"]
        out = check(rows, rules191)
        gv = c["gold_verdict"]
        same = (out["structure_matches"] == gv["structure_matches"]
                and set(out["failed"]) == set(gv["failed"])
                and out["order"] == gv["order"])
        bad += not same
        print(f"{c['id']:26} {str(gv['structure_matches']):8} {str(out['structure_matches']):8} "
              f"{'ok' if same else 'DIFF':6} {out['failed']}"
              + ("" if same else f"   gold failed: {gv['failed']}"))
    print(f"\n{len(cases) - bad}/{len(cases)} agree with gold_verdict")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
