"""The comparison for the "Without OBDA" switch: Qwen gets the transaction table rows and decides for itself.

No ontology, no mapping, no typology text, no SHACL. The rows of the flagged transactions are read with a plain SELECT by id (code, not
the model; no Ontop), shown to the model as a CSV, and the model is asked the investigator's own question. What it says is shown next to
the OBDA answer. One run, one answer: this is an illustration of the difference, not a measurement.

Columns left out of what the model sees (they would hand it the answer or are bookkeeping of the dataset, not facts about the payment):
label (the laundering flag), graph_roundtrip (a precomputed loop flag), split, is_tail_period.

run(question, ids, model, temperature) -> dict:
  ids, found_ids, missing_ids, columns, rows (list of dicts), prompt_version, reply, answer ('yes' | 'no' | 'cannot tell' | None),
  parts ({understood, data_used, found, checked, cannot_say}), explanation (the parts as markdown), seconds, error
"""
import csv
import io
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT.parent / "AML Triage Demo" / "data" / "features.duckdb"
DB_PYTHON = ROOT.parent / "AML Triage Demo" / ".venv" / "bin" / "python"      # the DuckDB that can read this file (see CLAUDE.md)
HIDDEN = ("label", "graph_roundtrip", "split", "is_tail_period")
PROMPT_VERSION = "b2-without-obda-report-2026-11-13"
SECTIONS = [("understood", "How I read the question"), ("data_used", "What information I used"), ("found", "What the records show"),
            ("checked", "What I checked, and the result"), ("cannot_say", "What these records cannot tell")]       # the same five parts as src/summarize.py

# runs inside the AML Triage venv; read-only; the ids come in as JSON on stdin
_FETCH = """
import json, sys, duckdb
req = json.load(sys.stdin)
con = duckdb.connect(req["db"], read_only=True)
marks = ",".join("?" for _ in req["ids"])
cur = con.execute("SELECT * FROM tx_features WHERE tx_id IN (" + marks + ") ORDER BY tx_id", [int(i) for i in req["ids"]])
cols = [d[0] for d in cur.description]
print(json.dumps({"columns": cols, "rows": [[str(v) if hasattr(v, "isoformat") else v for v in r] for r in cur.fetchall()]}))
"""

SYSTEM = ("You are an assistant for an anti-money-laundering investigator. You are given some rows of a transaction table and the "
          "investigator's question. Answer from the rows only, in plain business language: say paying account, receiving account, time, amount, "
          "and do not use table or column names. Reply with one JSON object with the keys "
          '"answer" (one of "yes", "no", "cannot tell": does what the investigator describes fit the rows) and, each a string of one to three sentences, '
          '"understood" (how you read the question), "data_used" (which information in the rows you relied on), "found" (what the rows show), '
          '"checked" (what you checked and the result) and "cannot_say" (what these rows cannot tell).')


def fetch(ids, db=DB, python=DB_PYTHON, timeout=120):
    """The rows of tx_features for these ids, minus the hidden columns: (columns, rows as dicts). Raises RuntimeError if the database
    cannot be read."""
    if not Path(db).exists() or not Path(python).exists():
        raise RuntimeError("the transaction database or the Python that can read it was not found")
    p = subprocess.run([str(python), "-I", "-c", _FETCH], input=json.dumps({"db": str(db), "ids": list(ids)}), capture_output=True, text=True,
                       timeout=timeout)
    try:
        out = json.loads(p.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"the database call failed: {(p.stderr or p.stdout)[:200]}") from e
    keep = [i for i, c in enumerate(out["columns"]) if c not in HIDDEN]
    cols = [out["columns"][i] for i in keep]
    return cols, [{out["columns"][i]: r[i] for i in keep} for r in out["rows"]]


def as_csv(cols, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        w.writerow([r[c] for c in cols])
    return buf.getvalue()


def build(question, cols, rows):
    """(system, user) for the model. The question is the investigator's own words, unchanged."""
    return SYSTEM, f"Question:\n{question}\n\nTable tx_features, {len(rows)} rows (CSV):\n{as_csv(cols, rows)}"


def parse(reply):
    """(answer, parts) from the model's reply: answer is None when it is not one of the three allowed words; parts = {key: text} for the five parts present."""
    try:
        d = json.loads(reply)
    except json.JSONDecodeError:
        return None, {}
    if not isinstance(d, dict):
        return None, {}
    a = str(d.get("answer", "")).strip().lower()
    parts = {k: str(d[k]).strip() for k, _ in SECTIONS if isinstance(d.get(k), str) and d[k].strip()}
    return (a if a in ("yes", "no", "cannot tell") else None), parts


def as_markdown(parts):
    return "\n\n".join(f"**{title}**  \n{parts[key]}" for key, title in SECTIONS if parts.get(key))


def run(question, ids, model=llm.DEFAULT_MODEL, temperature=0.3, rows_fn=fetch, chat_fn=llm.chat):
    r = {"ids": list(ids), "found_ids": [], "missing_ids": [], "columns": [], "rows": [], "prompt_version": PROMPT_VERSION, "model": model,
         "reply": None, "answer": None, "parts": {}, "explanation": "", "seconds": None, "error": None}
    try:
        cols, rows = rows_fn(ids)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        r["error"] = f"Could not read the table: {e}"
        return r
    r["columns"], r["rows"] = cols, rows
    r["found_ids"] = [x["tx_id"] for x in rows]
    r["missing_ids"] = sorted(set(int(i) for i in ids) - set(r["found_ids"]))
    if not rows:
        r["error"] = "None of these transaction ids is in the table."
        return r
    s, u = build(question, cols, rows)
    try:
        reply, secs = chat_fn(s, u, model=model, temperature=temperature)
    except llm.LLMError as e:
        r["error"] = f"The model could not be reached: {e}"
        return r
    r["reply"], r["seconds"] = reply, round(secs, 1)
    r["answer"], r["parts"] = parse(reply)
    r["explanation"] = as_markdown(r["parts"]) or reply.strip()          # the five parts as markdown (the raw reply if the model did not follow the format)
    return r
