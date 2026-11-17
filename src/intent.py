"""Intent analysis: which AML technique is the investigator describing? The model only picks from the typology's own list.

The list (each tactic with one sentence of its definition; under it every technique and sub-technique with its id and name) is read from
AMLO + AMLTRIX through Ontop, so it is the typology's vocabulary, not ours. The model answers {"tactic", "technique", "candidates", "clarify"}; code then checks what it said:
  - the technique id must be in the list, and listed under the tactic the model named        -> otherwise status 'rejected'
  - the model may name no technique but up to three candidate ids, for the investigator to pick -> status 'choose' (each candidate
    is checked against the list, described with the typology's own first sentence, and marked as checkable or not in this demo)
  - the model may name nothing and ask one question instead ('clarify')                       -> status 'clarify'
  - the technique is real but this demo can only check the one in validation/indicator_registry.json -> status 'unsupported'
  - otherwise                                                                                  -> status 'ok'
The model never sees transaction data and writes no query here. Nothing in this module decides an AML verdict.

Run with the project venv:  .venv/bin/python src/intent.py "<question>"   (asks the model once and prints the checked result)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indicators  # noqa: E402
import llm  # noqa: E402
import typology_ontop as T  # noqa: E402

PROMPT_VERSION = "i3-2026-11-09"            # i1: techniques, names only. i2: + sub-techniques, a sentence per tactic. i3: + candidates when unsure

CATALOG_SPARQL = """SELECT ?tactic ?tid ?tech ?pid ?def WHERE {
  ?t a amlo:Technique ; skos:prefLabel ?tech ; skos:notation ?tid ; amlo:achievesTactic ?tac .
  ?tac skos:prefLabel ?tactic .
  OPTIONAL { ?t skos:broader ?p . ?p skos:notation ?pid }
  OPTIONAL { ?t skos:definition ?def }
} ORDER BY ?tactic ?tid"""

TACTIC_SPARQL = """SELECT ?tactic ?def WHERE { ?tac a amlo:Tactic ; skos:prefLabel ?tactic ; skos:definition ?def } ORDER BY ?tactic"""

_cache = {}


def first_sentence(text, limit=230):
    t = " ".join((text or "").replace("*", "").split())
    cut = t.find(". ")
    t = t[:cut + 1] if 0 < cut < limit else t[:limit].rsplit(" ", 1)[0] + "..."
    return t


def catalog(force=False):
    """The typology's tactics, techniques and sub-techniques, asked of Ontop once per process. Never raises; 'error' is set when Ontop failed.
    {'error', 'seconds', 'tactics': [name], 'tactic_text': {name: one sentence}, 'techniques': {id: {'name', 'tactics': [name], 'parent': id or None, 'text': one sentence}}}"""
    if _cache and not force:
        return _cache["c"]
    res = {"error": None, "seconds": 0.0, "tactics": [], "tactic_text": {}, "techniques": {}, "sparql": CATALOG_SPARQL + "\n\n" + TACTIC_SPARQL}
    try:
        rows, s1, err = T.run_ontop(CATALOG_SPARQL, "csv")
        tac_rows, s2, err2 = T.run_ontop(TACTIC_SPARQL, "csv")
    except Exception as e:  # noqa: BLE001 - the page must go on and say why
        res["error"] = f"{type(e).__name__}: {e}"
        return res
    res["seconds"] = round(s1 + s2, 1)
    if err or err2 or not rows:
        res["error"] = (err or err2 or "Ontop returned no rows")[-300:]
        return res
    for tactic, tid, name, pid, definition in rows:
        e = res["techniques"].setdefault(tid, {"name": name, "tactics": [], "parent": pid or None, "text": first_sentence(definition) if definition else ""})
        e["tactics"].append(tactic)
        if tactic not in res["tactics"]:
            res["tactics"].append(tactic)
    res["tactic_text"] = {t: first_sentence(d) for t, d in tac_rows}
    _cache["c"] = res
    return res


def listing(cat):
    """The list as the model sees it: one block per tactic (with a sentence about it), one line per technique, its sub-techniques indented."""
    by_tactic = {}
    for tid, t in cat["techniques"].items():
        for tac in t["tactics"]:
            by_tactic.setdefault(tac, []).append((tid, t["name"]))
    blocks = []
    for tac in sorted(by_tactic):
        head = f"{tac} - {cat['tactic_text'][tac]}" if cat.get("tactic_text", {}).get(tac) else tac
        lines = [("    " if "." in tid else "  ") + f"{tid} {name}" for tid, name in sorted(by_tactic[tac])]
        blocks.append(head + ":\n" + "\n".join(lines))
    return "\n\n".join(blocks)


EXAMPLES = '''Examples of the answer format (the ids and the question below are placeholders, not advice).
One technique:   {"tactic": "<tactic of the technique>", "technique": "<id from the list>", "candidates": [], "clarify": null}
Several could fit: {"tactic": null, "technique": null, "candidates": ["<id from the list>", "<another id from the list>"], "clarify": null}
Nothing to go on:  {"tactic": null, "technique": null, "candidates": [], "clarify": "<one short question for the investigator>"}

One worked example.
Question: "A pensioner keeps letting a stranger put money into his account and then sends it on for a small fee."
Answer: {"tactic": "Access Facilitation", "technique": "T0011", "candidates": [], "clarify": null}'''


def build(question, cat):
    system = ("You help an anti-money-laundering investigator. You are given the AML typology's techniques and their sub-techniques (indented), grouped by tactic. "
              "Decide which technique the investigator's question describes. Use only ids from the list, copied exactly, never one of your own; "
              "prefer the sub-technique when the question fits it better than its parent.\n"
              "- If the question clearly describes ONE technique, put its id in technique and its tactic in tactic.\n"
              "- If it does not point to one but up to THREE could fit, set technique and tactic to null and list their ids in candidates, most likely first.\n"
              "- If the investigator names transactions or accounts but does not say how they are linked, do not ask: list up to THREE techniques about patterns among bank transactions "
              "that could link them, most likely first, in candidates.\n"
              "- Only if the question says nothing about transactions or money movements, set technique and tactic to null, candidates to an empty list, and put ONE short question for the investigator in clarify.\n"
              "Answer with one JSON object with the keys tactic, technique, candidates and clarify, and nothing else.")
    user = f"AML typology:\n\n{listing(cat)}\n\n{EXAMPLES}\n\nQuestion: \"{question}\"\nAnswer:"
    return system, user


def parse(text):
    """The model's reply -> {'tactic', 'technique', 'clarify'} (each a string or None) and 'candidates' (a list of strings), or None when it is not that JSON object."""
    try:
        v = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(v, dict):
        return None
    out = {}
    for k in ("tactic", "technique", "clarify"):
        x = v.get(k)
        out[k] = x.strip() if isinstance(x, str) and x.strip() and x.strip().lower() not in ("null", "none") else None
    c = v.get("candidates")
    out["candidates"] = [x.strip().upper() for x in c if isinstance(x, str) and x.strip()] if isinstance(c, list) else []
    return out


def option(tid, cat):
    """One technique as the investigator is shown it: name, tactic, parent, the typology's first sentence, and whether this demo can check it."""
    tech = cat["techniques"][tid]
    parent = cat["techniques"].get(tech.get("parent") or "")
    return {"id": tid, "name": tech["name"], "tactic": tech["tactics"][0], "parent": f"{tech['parent']} {parent['name']}" if parent else None,
            "text": tech.get("text") or "", "supported": tid == indicators.registry()["technique"]}


def judge(parsed, cat):
    """Check what the model said against the typology. Returns {'status', 'technique', 'name', 'tactic', 'clarify', 'problems', 'supported'}."""
    out = {"status": "ok", "technique": None, "name": None, "tactic": None, "parent": None, "clarify": None, "problems": [], "supported": False, "options": []}
    if parsed is None:
        out.update(status="rejected", problems=["the reply was not a JSON object with the keys tactic, technique and clarify"])
        return out
    tid = (parsed["technique"] or "").upper()
    if not tid:
        seen = []
        for c in parsed.get("candidates") or []:
            if c in cat["techniques"] and c not in seen:
                seen.append(c)
        if seen:                                    # ids the model made up are dropped; real ones are offered to the investigator
            out.update(status="choose", options=[option(c, cat) for c in seen[:3]], clarify=parsed["clarify"] or "Which of these do you mean?")
            return out
        out.update(status="clarify", clarify=parsed["clarify"] or
                   "I could not tell which AML technique you mean. Describe how the money moves, or name the technique, and include transaction ids if you have them.")
        return out
    tech = cat["techniques"].get(tid)
    if not tech:
        out.update(status="rejected", problems=[f"{tid} is not a technique of the AML typology"])
        return out
    parent = cat["techniques"].get(tech.get("parent") or "")
    out.update(technique=tid, name=tech["name"], tactic=parsed["tactic"], supported=tid == indicators.registry()["technique"],
               parent=f"{tech['parent']} {parent['name']}" if parent else None)
    if parsed["tactic"] not in tech["tactics"]:
        out.update(status="rejected", problems=[f"{tid} {tech['name']} is not listed under the tactic '{parsed['tactic']}' (it is under: {', '.join(tech['tactics'])})"])
        return out
    if not out["supported"]:
        out["status"] = "unsupported"
    return out


def analyse(question, model=llm.DEFAULT_MODEL, temperature=0.3):
    """Ask the model once and check the answer. Never raises; status 'error' means the catalog or the model was not reachable."""
    cat = catalog()
    res = {"status": "error", "technique": None, "name": None, "tactic": None, "parent": None, "clarify": None, "problems": [], "supported": False, "options": [], "source": "model", "reply": None,
           "seconds": None, "catalog_seconds": cat["seconds"], "catalog_size": len(cat["techniques"]), "prompt_version": PROMPT_VERSION, "model": model}
    if cat["error"]:
        res["problems"] = ["Ontop could not read the AML typology: " + cat["error"]]
        return res
    s, u = build(question, cat)
    try:
        reply, secs = llm.chat(s, u, model=model, temperature=temperature, num_ctx=8192)
    except llm.LLMError as e:
        res["problems"] = [f"The model could not be reached: {e}"]
        return res
    res.update(judge(parse(reply), cat), reply=reply, seconds=round(secs, 1))
    return res


def from_pick(tid, cat=None):
    """The investigator picked one of the offered techniques: no model call, the same result shape as analyse()."""
    cat = cat or catalog()
    res = {"status": "error", "technique": None, "name": None, "tactic": None, "parent": None, "clarify": None, "problems": [], "supported": False,
           "options": [], "source": "investigator", "reply": None, "seconds": 0.0, "catalog_seconds": cat["seconds"], "catalog_size": len(cat["techniques"]),
           "prompt_version": None, "model": None}
    if cat["error"]:
        res["problems"] = ["Ontop could not read the AML typology: " + cat["error"]]
        return res
    if tid not in cat["techniques"]:
        res.update(status="rejected", problems=[f"{tid} is not a technique of the AML typology"])
        return res
    o = option(tid, cat)
    res.update(status="ok" if o["supported"] else "unsupported", technique=tid, name=o["name"], tactic=o["tactic"], parent=o["parent"], supported=o["supported"])
    return res


def sentence(res):
    """One line for the chat log."""
    s = res["status"]
    if s == "error":
        return "Intent · could not be analysed: " + res["problems"][0]
    if s == "choose":
        return "Intent · the question fits more than one technique; the investigator is asked to choose: " + ", ".join(o["id"] for o in res["options"])
    if s == "clarify":
        return "Intent · the question is not clear enough to match a technique; the model asks the investigator"
    if s == "rejected":
        return "Intent · the model's answer was rejected: " + res["problems"][0]
    tail = "" if res["supported"] else "; this demo cannot check it"
    who = "the investigator chose " if res.get("source") == "investigator" else ""
    sub = f" - sub-technique of {res['parent']}" if res.get("parent") else ""
    return f"Intent · {who}{res['technique']} {res['name']} ({res['tactic']}{sub}){tail}"


def stop_text(res):
    """What the assistant tells the investigator when the intent step stops the chain (status other than 'ok')."""
    reg = indicators.registry()
    s = res["status"]
    if s == "clarify":
        return res["clarify"]
    if s == "choose":
        lines = [f"- **{o['id']} {o['name']}** ({o['tactic']}{', sub-technique of ' + o['parent'] if o['parent'] else ''})"
                 + (f": {o['text']}" if o["text"] else "") + (" *(this demo can check it)*" if o["supported"] else " *(this demo cannot check it)*") for o in res["options"]]
        return res["clarify"] + "\n\n" + "\n".join(lines)
    if s == "unsupported":
        return (f"This looks like {res['technique']} {res['name']} ({res['tactic']}{', sub-technique of ' + res['parent'] if res.get('parent') else ''}) in the AML typology. "
                f"This demo can only check {reg['technique']} {reg['name']}, so I cannot check it against the data.")
    if s == "rejected":
        return "The model's reading of the question was rejected because " + (res["problems"] or ["it did not match the AML typology"])[0] + ". Please rephrase."
    return (res["problems"] or ["The intent could not be analysed."])[0]


if __name__ == "__main__":
    r = analyse(" ".join(sys.argv[1:]) or "Money seems to go round in circles between a few accounts and ends up where it started.")
    print(json.dumps({k: v for k, v in r.items() if k != "reply"}, indent=2, ensure_ascii=False))
    print("reply:", r["reply"])
