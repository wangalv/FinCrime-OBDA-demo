"""Back half of the chain with the gold SPARQL standing in for the model:
   transaction ids -> SPARQL -> Ontop -> rows -> candidate -> SHACL -> one answer per indicator, plus account background.

Run (project venv):  .venv/bin/python src/pipeline.py 2131053 2204314 2282865

parse_legs(csv_rows)      Ontop CSV rows -> the rows loop_check wants. Raises MissingColumns if the query did not return a needed column
                          (a bad query must be visible, not turned into an empty value).
answer(tx_ids, queries)   `queries` maps a role to a SPARQL string; default = queries.py (gold stand-in).
render(ans)               plain-text card. Wording: "structure matches the description", never "this is money laundering".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indicators  # noqa: E402
import queries  # noqa: E402
from ontop_run import run_ontop  # noqa: E402

ACC = "https://example.org/account/"
LEG_COLUMNS = ["txid", "ts", "from", "to"]            # amountLog and sameBank are read when the query returns them
CONTEXT_COLUMNS = ["account", "customerType", "tenure", "pep", "risk"]   # industry is optional (absent for individuals)


class MissingColumns(Exception):
    pass


class OntopError(Exception):
    pass


def _need(csv_rows, cols, what):
    have = set(csv_rows[0].keys()) if csv_rows else set(cols)
    miss = [c for c in cols if c not in have]
    if miss:
        raise MissingColumns(f"{what}: the query did not return {miss}; got {sorted(have)}")


def _acc(iri):
    return iri[len(ACC):] if iri.startswith(ACC) else iri


def parse_legs(csv_rows):
    _need(csv_rows, LEG_COLUMNS, "legs")
    out = []
    for r in csv_rows:
        row = {"tx_id": int(r["txid"]), "ts": r["ts"], "from": _acc(r["from"]), "to": _acc(r["to"])}
        if r.get("amountLog") not in (None, ""):
            row["amount_log"] = float(r["amountLog"])
        if "sameBank" in r:
            row["same_bank"] = r["sameBank"] == "true"
        out.append(row)
    return out


def parse_context(csv_rows):
    _need(csv_rows, CONTEXT_COLUMNS, "context")
    rows = [{"account": _acc(r["account"]), "customer_type": r["customerType"], "industry": r.get("industry") or None,
             "tenure": int(r["tenure"]), "pep": r["pep"] == "true", "risk": r["risk"]} for r in csv_rows]
    return sorted(rows, key=lambda x: x["account"])


def _run(sparql):
    rows, _sql, _secs, err = run_ontop(sparql)
    if err:
        raise OntopError(err)
    return rows


def answer(tx_ids, qs=None):
    qs = qs or {"legs": queries.legs_sparql(tx_ids), "legs_bank": queries.legs_bank_sparql(tx_ids),
                "context": queries.context_sparql(tx_ids)}
    legs = parse_legs(_run(qs["legs"]))
    bank = {r["tx_id"]: r["same_bank"] for r in parse_legs(_run(qs["legs_bank"]))}
    for r in legs:
        if r["tx_id"] in bank:
            r["same_bank"] = bank[r["tx_id"]]
    rep = indicators.report(legs)
    return {"asked": list(tx_ids), "missing_ids": sorted(set(tx_ids) - {r["tx_id"] for r in legs}),
            "legs": legs, "order": rep["order"], "indicators": rep["indicators"],
            "context": parse_context(_run(qs["context"]))}


WORDS = {"held": "structure matches the description", "not_held": "does not match", "cannot_check": "cannot be checked here",
         "facts_only": "facts only (the typology gives no threshold)"}


def render(ans):
    reg = {i["id"]: i for i in indicators.registry()["indicators"]}
    out = [f"Transactions asked: {ans['asked']}"]
    if ans["missing_ids"]:
        out.append(f"Not found in the data: {ans['missing_ids']} (the rest were judged)")
    out.append("Legs in time order: " + " -> ".join(str(t) for t in ans["order"]))
    for e in ans["indicators"]:
        line = f"{e['id']}  {WORDS[e['state']]}"
        if e["state"] == "not_held":
            line += f"  [{', '.join(e['failed'])}]"
        if e.get("facts"):
            f = e["facts"]
            line += f"  hops={f['hops']}, between-bank legs={f['interbank_legs'] if f['interbank_legs'] is not None else 'unknown'}"
        if e["state"] == "cannot_check" and e["missing_terms"]:
            line += f"  missing: {', '.join(e['missing_terms'])}"
        if e["state"] in ("held", "facts_only") and e["not_checked"]:
            line += "  | not checked: " + "; ".join(e["not_checked"])
        out.append(line + "   # " + reg[e["id"]]["text"][:70] + "...")
    out.append("Account background (synthetic KYC, context only):")
    for c in ans["context"]:
        out.append(f"  {c['account']}  {c['customer_type']}" + (f", {c['industry']}" if c["industry"] else "")
                   + f", open {c['tenure']} days, PEP={'yes' if c['pep'] else 'no'}, risk {c['risk']}")
    return "\n".join(out)


if __name__ == "__main__":
    ids = [int(a) for a in sys.argv[1:]] or [2131053, 2204314, 2282865]
    print(render(answer(ids)))
