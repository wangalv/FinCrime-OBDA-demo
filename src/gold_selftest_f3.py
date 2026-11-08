"""Self-test of the F3 gold: gold SPARQL through Ontop (a two-table join) must return the same rows as the gold SQL.
Run:  "../AML Triage Demo/.venv/bin/python" src/gold_selftest_f3.py
"""
import hashlib, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ontop_run import run_ontop

ROOT = Path(__file__).resolve().parent.parent
ACC = "https://example.org/account/"
CASES = json.loads((ROOT / "gold" / "cases_f3.json").read_text(encoding="utf-8"))["cases"]


def norm_ontop(r):
    return {"account": r["account"].removeprefix(ACC), "customer_type": r["customerType"], "industry": r["industry"] or None,
            "tenure": int(r["tenure"]), "pep": r["pep"] == "true", "risk": r["risk"]}


bad = 0
for c in CASES:
    rows, sql1, s1, err = run_ontop(c["gold_sparql"])
    if err:
        print(f"{c['id']:28s} ONTOP ERROR {err}"); bad += 1; continue
    _, sql2, _, _ = run_ontop(c["gold_sparql"])
    key = lambda x: x["account"]
    got = sorted((norm_ontop(r) for r in rows), key=key)
    want = sorted(c["gold_rows"], key=key)
    same_rows, same_sql = got == want, bool(sql1) and sql1 == sql2
    bad += not (same_rows and same_sql)
    print(f"{c['id']:28s} rows={'ok' if same_rows else 'DIFF'} sql_repeatable={'ok' if same_sql else 'NO'} n={len(got)}/{len(want)} "
          f"{s1:.1f}s sqlhash={hashlib.md5((sql1 or '').encode()).hexdigest()[:8]}")
    if not same_rows:
        print("   got :", got[:2]); print("   want:", want[:2])
print("ALL OK" if not bad else f"{bad} case(s) failed")
sys.exit(1 if bad else 0)
