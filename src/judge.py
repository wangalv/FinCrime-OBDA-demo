"""Compare a pipeline answer with the gold. Used for the outcome: correct / silently wrong.

differences(ans, f1_case, f3_case=None) -> list of strings; empty = the answer matches the gold on every point the gold covers:
  legs order and missing ids, IND02191 verdict and failed rules, IND02195 facts, account background (when an F3 gold exists).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAME_BANK = json.loads((ROOT / "tests" / "fixtures" / "same_bank.json").read_text())


def differences(ans, f1, f3=None):
    d = []
    gv = f1["gold_verdict"]
    e191 = next(e for e in ans["indicators"] if e["id"] == "IND02191")
    if ans["order"] != gv["order"]:
        d.append(f"legs/order {ans['order']} != gold {gv['order']}")
    if ans["missing_ids"] != f1["missing_ids"]:
        d.append(f"missing ids {ans['missing_ids']} != gold {f1['missing_ids']}")
    if e191["state"] != ("held" if gv["structure_matches"] else "not_held"):
        d.append(f"IND02191 {e191['state']} but gold structure_matches={gv['structure_matches']}")
    elif set(e191["failed"]) != set(gv["failed"]):
        d.append(f"IND02191 failed rules {sorted(e191['failed'])} != gold {sorted(gv['failed'])}")
    e195 = next(e for e in ans["indicators"] if e["id"] == "IND02195")
    want = {"hops": len(f1["gold_rows"]), "interbank_legs": sum(1 for r in f1["gold_rows"] if not SAME_BANK[str(r["tx_id"])])}
    if e195.get("facts") != want:
        d.append(f"IND02195 facts {e195.get('facts')} != gold {want}")
    if f3 is not None and ans["context"] != sorted(f3["gold_rows"], key=lambda x: x["account"]):
        d.append("account background differs from the F3 gold")
    return d
