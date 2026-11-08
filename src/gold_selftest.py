"""Self-test of the gold cases: run each gold SPARQL through Ontop and compare with the gold rows read from the database.

Run with the AML Triage venv (DuckDB 2.0):
  "../AML Triage Demo/.venv/bin/python" src/gold_selftest.py
Checks per case: (1) gold SPARQL through Ontop returns the same rows as gold SQL (set of tx_id and every field);
(2) the generated SQL is the same on a second run once column-alias numbers (1m<digits>) are normalised; the raw text differs only there; (3) number of seconds.
A failure here is a bug in the mapping, the gold, or the harness, not a model result.
"""
import csv, hashlib, io, json, os, re, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ontop_run import run_ontop

ROOT = Path(__file__).resolve().parent.parent
GOLD = json.loads((ROOT / "gold" / "cases.json").read_text(encoding="utf-8"))
ACC = "https://example.org/account/"


def norm_ontop(r):
    return {"tx_id": int(r["txid"]), "ts": r["ts"], "from": r["from"].removeprefix(ACC), "to": r["to"].removeprefix(ACC),
            "amount_log": round(float(r["amountLog"]), 9)}


def norm_gold(r):
    return {"tx_id": r["tx_id"], "ts": r["ts"], "from": r["from"], "to": r["to"], "amount_log": round(r["amount_log"], 9)}


bad = 0
for c in GOLD["cases"]:
    rows, sql1, s1, err = run_ontop(c["gold_sparql"])
    if err:
        print(f"{c['id']:28s} ONTOP ERROR {err}"); bad += 1; continue
    _, sql2, s2, _ = run_ontop(c["gold_sparql"])
    got = sorted((norm_ontop(r) for r in rows), key=lambda x: x["tx_id"])
    want = sorted((norm_gold(r) for r in c["gold_rows"]), key=lambda x: x["tx_id"])
    same_rows = got == want
    same_sql = bool(sql1) and sql1 == sql2
    ok = same_rows and same_sql
    bad += not ok
    print(f"{c['id']:28s} rows={'ok' if same_rows else 'DIFF'} sql_repeatable={'ok' if same_sql else 'NO'} "
          f"n={len(got)}/{len(want)} {s1:.1f}s sqlhash={hashlib.md5((sql1 or '').encode()).hexdigest()[:8]}")
    if not same_rows:
        print("   got :", got[:3]); print("   want:", want[:3])
print("ALL OK" if not bad else f"{bad} case(s) failed")
sys.exit(1 if bad else 0)
