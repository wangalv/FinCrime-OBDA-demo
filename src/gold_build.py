"""Build the gold cases for family F1 (verify given transaction ids) into gold/cases.json.

Run with the AML Triage venv (it has the DuckDB version that can read features.duckdb):
  "../AML Triage Demo/.venv/bin/python" src/gold_build.py

What is gold here, and how it is kept independent of the pipeline under test:
  - the transaction ids are chosen from the data by the SQL below (criteria written in each case's `provenance`);
  - gold SQL is plain SQL on tx_features;
  - gold rows are read straight from tx_features;
  - the expected verdict comes from `verdict()` below, written by hand from the T0039 / IND02191 reading in PLAN.md,
    not from SHACL or Ontop.
NOT reproducible: a rerun on 2026-11-08 chose different transaction ids for 7 cases (cause not investigated). gold/cases.json is the accepted file;
changes to it are patched in place and logged in meta.changes. Do not regenerate over it.
"""
import json
from datetime import timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT.parent / "AML Triage Demo" / "data" / "features.duckdb"
OUT = ROOT / "gold" / "cases.json"
WINDOW = "interval 7 day"   # all legs of a candidate loop within 7 days of its first leg
NONEXISTENT_ID = 99999999

PREFIX = "PREFIX fcd: <https://example.org/fincrime-data#>"

WORDINGS = [
    "I think these transactions may be Circular Transactions. The ids are {ids}. Please check.",
    "Could you confirm whether transactions {ids} form a circular pattern where the money returns to where it started?",
    "Here are some transaction ids: {ids}. Do they look like a loop of funds going around several accounts?",
    "Check transactions {ids} for signs of circular transfers (technique T0039).",
    "Alert suspects circular transactions on {ids}. Is that supported by the data?",
    "Do transactions {ids} send funds around a cycle of accounts and back to the first one, in time order?",
    "我觉得这几笔交易有循环转账（Circular Transactions）的嫌疑，交易编号是 {ids}，帮我确认一下。",
    "请检查交易 {ids} 是否构成资金在几个账户之间转一圈又回到起点的模式。",
]


def verdict(legs):
    """Check of IND02191 written to follow validation/shapes/t0039.shapes.ttl (the rule authority since 2026-11-08), not Ontop.
    legs: list of dicts with tx_id, ts (datetime), f (payer), t (receiver). Order of input does not matter:
    legs are sorted by (ts, tx_id), the first leg's payer is the origin."""
    L = sorted(legs, key=lambda x: (x["ts"], x["tx_id"]))
    n = len(L)
    rules = {}
    if n == 0:
        return {"structure_matches": False, "rules": {"origin_named": False}, "failed": ["origin_named"], "order": []}
    origin = L[0]["f"]
    rules["first_leg_starts_at_origin"] = True   # by construction: origin is the first leg's payer
    rules["last_leg_returns_to_origin"] = L[-1]["t"] == origin
    rules["consecutive_legs_connect"] = all(L[i]["t"] == L[i + 1]["f"] for i in range(n - 1))
    rules["legs_in_time_order"] = all(L[i]["ts"] <= L[i + 1]["ts"] for i in range(n - 1))   # true after sorting
    rules["at_least_2_accounts"] = len({x["f"] for x in L} | {x["t"] for x in L}) >= 2
    failed = [k for k, v in rules.items() if not v]
    return {"structure_matches": not failed, "rules": rules, "failed": failed, "order": [x["tx_id"] for x in L]}


def main():
    c = duckdb.connect(str(DB), read_only=True)
    q = lambda s: c.execute(s).fetchall()

    c.execute("""create temp table tx as
        select tx_id, ts, label, from_account f, to_account t from tx_features where from_account <> to_account""")

    # --- 3-leg loops, strictly increasing time, 3 distinct accounts, within the window
    c.execute(f"""create temp table l3 as
        select a.tx_id i1, b.tx_id i2, c3.tx_id i3, a.label + b.label + c3.label lab, c3.ts - a.ts span
        from tx a join tx b on a.t = b.f and b.ts > a.ts and b.ts <= a.ts + {WINDOW} and b.t <> a.f
        join tx c3 on b.t = c3.f and c3.t = a.f and c3.ts > b.ts and c3.ts <= a.ts + {WINDOW}""")
    # --- 4-leg loops
    c.execute(f"""create temp table l4 as
        select a.tx_id i1, b.tx_id i2, c3.tx_id i3, d.tx_id i4, a.label + b.label + c3.label + d.label lab
        from tx a join tx b on a.t = b.f and b.ts > a.ts and b.ts <= a.ts + {WINDOW} and b.t <> a.f
        join tx c3 on b.t = c3.f and c3.ts > b.ts and c3.ts <= a.ts + {WINDOW} and c3.t <> a.f and c3.t <> b.f
        join tx d on c3.t = d.f and d.t = a.f and d.ts > c3.ts and d.ts <= a.ts + {WINDOW}""")
    # --- chains A>B>C>D that do not return (D is a new account), labelled none
    c.execute(f"""create temp table ch as
        select a.tx_id i1, b.tx_id i2, c3.tx_id i3
        from tx a join tx b on a.t = b.f and b.ts > a.ts and b.ts <= a.ts + {WINDOW} and b.t <> a.f
        join tx c3 on b.t = c3.f and c3.ts > b.ts and c3.ts <= a.ts + {WINDOW} and c3.t not in (a.f, a.t, b.t)
        where a.label + b.label + c3.label = 0""")
    # --- three legs that sit on a cycle of accounts but whose time order is not a rotation of the cycle
    c.execute(f"""create temp table oo as
        select x.tx_id i1, y.tx_id i2, z.tx_id i3 from tx x join tx y on x.t = y.f and y.t <> x.f
        join tx z on y.t = z.f and z.t = x.f
        where x.ts <> y.ts and y.ts <> z.ts and x.ts <> z.ts
          and greatest(x.ts, y.ts, z.ts) - least(x.ts, y.ts, z.ts) <= {WINDOW}
          and not ((x.ts < y.ts and y.ts < z.ts) or (y.ts < z.ts and z.ts < x.ts) or (z.ts < x.ts and x.ts < y.ts))""")
    # --- round trips A>B>A, both legs labelled laundering
    c.execute(f"""create temp table rt as
        select a.tx_id i1, b.tx_id i2 from tx a join tx b on a.t = b.f and b.t = a.f and b.ts > a.ts and b.ts <= a.ts + {WINDOW}
        where a.label + b.label = 2""")

    def pick(sql, k):
        return [list(r) for r in q(f"{sql} order by hash(i1 * 7919 + i2) limit {k}")]

    pos3_short = pick("select i1, i2, i3 from l3 where lab = 3 and span < interval 1 day", 3)
    pos3_long = pick("select i1, i2, i3 from l3 where lab = 3 and span >= interval 1 day", 2)
    near3 = pick("select i1, i2, i3 from l3 where lab = 0", 3)
    pos4 = pick("select i1, i2, i3, i4 from l4 where lab = 4", 2)
    chains = pick("select i1, i2, i3 from ch", 2)
    outorder = pick("select i1, i2, i3 from oo", 2)
    roundtrip = pick("select i1, i2 from rt", 1)
    cand = q("select tx_id, f, t from tx where label = 0 order by hash(tx_id) limit 200")
    chosen, used = [], set()
    for tid, f, t in cand:
        if f not in used and t not in used:
            chosen.append(tid)
            used |= {f, t}
        if len(chosen) == 3:
            break
    unrelated = [chosen]

    cases = []

    def add(cid, role, ids, what, provenance, missing_ok=False):
        ids = [int(i) for i in ids]
        real = [i for i in ids if i != NONEXISTENT_ID]
        rows = q(f"select tx_id, ts, from_account, to_account, amount_log from tx_features where tx_id in ({','.join(map(str, real))}) order by tx_id")
        gold_rows = [{"tx_id": r[0], "ts": r[1].isoformat(), "from": r[2], "to": r[3], "amount_log": r[4]} for r in rows]
        legs = [{"tx_id": r[0], "ts": r[1], "f": r[2], "t": r[3]} for r in rows]
        v = verdict(legs)
        missing = sorted(set(ids) - {r[0] for r in rows})
        in_list = ", ".join(map(str, ids))
        cases.append({
            "id": cid, "family": "F1", "role": role, "what": what, "provenance": provenance,
            "tx_ids": ids,
            "gold_sparql": f"{PREFIX}\nSELECT ?txid ?ts ?from ?to ?amountLog WHERE {{\n  VALUES ?txid {{ {' '.join(map(str, ids))} }}\n"
                           f"  ?tx a fcd:Transaction ; fcd:txId ?txid ; fcd:timestamp ?ts ; fcd:fromAccount ?from ; fcd:toAccount ?to ; fcd:amountLog ?amountLog .\n}}",
            "gold_sql": f"SELECT tx_id, ts, from_account, to_account, amount_log FROM tx_features WHERE tx_id IN ({in_list}) ORDER BY tx_id",
            "gold_rows": gold_rows, "missing_ids": missing,
            "gold_verdict": v,
            "questions": [w.format(ids=in_list) for w in WORDINGS],
            "review": "written by Claude; accepted by the user 2026-11-08; not reviewed by a domain expert",
        })

    for i, ids in enumerate(pos3_short + pos3_long, 1):
        add(f"F1-loop3-{i:02d}", "positive", ids, "Three-leg loop in time order; all legs labelled laundering.",
            "From the data: A>B>C>A, strictly increasing time, 3 distinct accounts, within 7 days, label = 1 on every leg.")
    for i, ids in enumerate(pos4, 1):
        add(f"F1-loop4-{i:02d}", "positive", ids, "Four-leg loop in time order; all legs labelled laundering.",
            "From the data: A>B>C>D>A, strictly increasing time, 4 distinct accounts, within 7 days, label = 1 on every leg.")
    for i, ids in enumerate(near3, 1):
        add(f"F1-loop3-unlabelled-{i:02d}", "near_positive", ids,
            "Three-leg loop in time order whose legs carry no laundering label: the structure holds, nobody labelled it.",
            "From the data: same pattern as F1-loop3 but label = 0 on every leg.")
    for i, ids in enumerate(chains, 1):
        add(f"F1-chain-{i:02d}", "negative", ids, "A chain A>B>C>D in time order that never returns to its start.",
            "From the data: three consecutive legs, strictly increasing time, last receiver is a new account, label = 0.")
    add("F1-open-from-loop3", "negative", pos3_short[0][:2], "Two legs of a labelled 3-leg loop: the loop is missing its last leg.",
        "First two legs (by time) of " + "F1-loop3-01.")
    add("F1-open-from-loop4", "negative", pos4[0][:3], "Three legs of a labelled 4-leg loop: the loop is missing its last leg.",
        "First three legs (by time) of F1-loop4-01.")
    for i, ids in enumerate(outorder, 1):
        add(f"F1-out-of-order-{i:02d}", "negative", ids,
            "Legs lie on a cycle of three accounts, but their time order is not a rotation of the cycle, so the money cannot have gone round in time order.",
            "From the data: x>y>z>x as account edges, three distinct timestamps within 7 days, time order is neither x,y,z nor a rotation of it.")
    add("F1-roundtrip", "positive", roundtrip[0], "Two-leg round trip A>B>A in time order; both legs labelled laundering. Counts since 2026-11-08: the typology gives no minimum number of legs.",
        "From the data: A>B then B>A, strictly increasing time, within 7 days, label = 1 on both.")
    add("F1-unrelated", "negative", unrelated[0], "Three unrelated transactions, no shared account.",
        "From the data: three label-0 transactions whose accounts are all different.")
    add("F1-missing-id", "partial_ids", list(pos3_short[1]) + [NONEXISTENT_ID],
        "A real 3-leg loop plus an id that does not exist. Expected: the missing id is reported, the other three are judged.",
        f"F1-loop3-02 ids plus {NONEXISTENT_ID}, which is not in tx_features.")

    out = {
        "meta": {
            "database": "AML Triage Demo/data/features.duckdb (tx_features)",
            "window_days": 7,
            "rules": "legs sorted by (ts, tx_id); origin = first leg's payer; last leg returns to origin; consecutive legs connect; time order; more than one account (no minimum number of legs, as in validation/shapes/t0039.shapes.ttl)",
            "note": "Timestamps have minute resolution. Cases were chosen with distinct timestamps so that tie-breaking by tx_id does not matter. "
                    "Expected verdicts come from src/gold_build.py verdict(), written to follow validation/shapes/t0039.shapes.ttl; the SHACL is the rule authority, the gold follows it.",
            "status": "ACCEPTED by the user 2026-11-08 (no domain-expert review). Frozen: log every later change here.",
            "changes": ["2026-11-08, user's decision: the typology gives no minimum number of legs, so min_3_legs and at_least_3_accounts_each_paying_once were dropped and at_least_2_accounts added. F1-roundtrip changes from negative to positive; F1-open-from-loop3 now fails only last_leg_returns_to_origin. Selection of cases and gold rows unchanged."],
        },
        "cases": cases,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(cases)} cases -> {OUT}")
    for k in cases:
        print(f"{k['id']:28s} {k['role']:13s} ids={len(k['tx_ids'])} missing={k['missing_ids']} match={k['gold_verdict']['structure_matches']} failed={k['gold_verdict']['failed']}")


if __name__ == "__main__":
    main()
