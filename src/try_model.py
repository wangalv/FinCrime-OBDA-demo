"""Small exploratory trial (NOT a measurement): the model writes the three queries for a few questions; each goes through the SPARQL
guard, Ontop, the candidate and SHACL, and the answer is compared with the gold. Everything is saved to generated/.

Run:  .venv/bin/python src/try_model.py [case_id:wording_index ...]
"""
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge, llm, pipeline, prompt, sparql_guard  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
F1 = {c["id"]: c for c in json.loads((ROOT / "gold" / "cases.json").read_text())["cases"]}
F3 = {c["from_f1_case"]: c for c in json.loads((ROOT / "gold" / "cases_f3.json").read_text())["cases"]}
DEFAULT = ["F1-loop3-01:0", "F1-chain-01:1", "F1-roundtrip:2", "F1-missing-id:3", "F1-loop4-01:6"]


def run_one(case_id, wi, model=llm.DEFAULT_MODEL, temperature=0.3):
    c = F1[case_id]
    q = c["questions"][wi]
    rec = {"case": case_id, "wording": wi, "question": q, "queries": {}, "raw": {}, "guard": {}, "seconds": {}}
    for role in prompt.ROLES:
        s, u = prompt.build(q, role)
        try:
            text, secs = llm.chat(s, u, model=model, temperature=temperature)
        except llm.LLMError as e:
            rec["outcome"] = f"model_error: {e}"
            return rec
        rec["raw"][role], rec["seconds"][role] = text, round(secs, 1)
        sp = prompt.extract_sparql(text)
        if sp is None:
            rec["guard"][role] = [("no_sparql", "the reply was not the expected JSON with a sparql field")]
            continue
        rec["queries"][role] = sp
        rec["guard"][role] = sparql_guard.check(sp, prompt.ROLES[role]["vars"], c["tx_ids"])
    bad = {r: g for r, g in rec["guard"].items() if g}
    if bad:
        rec["outcome"] = "rejected_by_guard: " + "; ".join(f"{r}:{g[0][0]}" for r, g in bad.items())
        return rec
    try:
        ans = pipeline.answer(c["tx_ids"], rec["queries"])
    except (pipeline.MissingColumns, pipeline.OntopError) as e:
        rec["outcome"] = f"rejected_later: {type(e).__name__}: {str(e)[:200]}"
        return rec
    diff = judge.differences(ans, c, F3.get(case_id))
    rec["differences"] = diff
    rec["outcome"] = "correct" if not diff else "silently_wrong"
    return rec


def main():
    picks = sys.argv[1:] or DEFAULT
    out = {"model": llm.DEFAULT_MODEL, "prompt_version": prompt.PROMPT_VERSION, "temperature": 0.3,
           "date": datetime.datetime.now().isoformat(timespec="seconds"), "note": "exploratory trial, not a measurement", "runs": []}
    for p in picks:
        cid, wi = p.rsplit(":", 1)
        r = run_one(cid, int(wi))
        out["runs"].append(r)
        print(f"{cid:22} w{wi}  {r['outcome']}  {sum(r['seconds'].values()):.0f}s", flush=True)
        for d in r.get("differences", []):
            print("      ", d)
    path = ROOT / "generated" / f"trial_{prompt.PROMPT_VERSION}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print("saved", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
