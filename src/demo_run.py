"""One question through the whole chain, returning a trace the Streamlit page can show step by step.

steps(question, ...) is a generator: it fills the trace one stage at a time and yields (trace, event) after each stage, and also just before
each slow stage (the model writing, Ontop running), so a page can show the chain as it happens. event = {"msg", "obda", "sql", "role"}:
a sentence for the chat log and the view the page should bring forward. run(...) consumes it and returns the final trace.

run(question, mode, ...) -> trace dict:
  question, ids, mode ('model' = the LLM writes the SPARQL, 'gold' = the gold SPARQL stands in)
  plan: the queries the Alignment asks for (src/queryplan.py), one per entity: transaction (evidence for the indicators) and account (background)
  roles[key] = {label, serves, vars, required, sparql, guard (list), reply, llm_seconds, sql, ontop_seconds, rows (CSV dicts), error}
  (one model call writes all the queries: reply and llm_seconds are the same for each; t['llm_seconds'] is that call)
  answer (pipeline-style dict, or None), candidate_turtle, summary {text, source, problems, seconds}, status, status_text
A query that serves an indicator is required: if it is rejected or fails there is nothing to judge, so the run stops. The background query is
not: if it is rejected or fails, the rest is still answered and the page says that part is missing.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_ontology  # noqa: E402
import indicators  # noqa: E402
import intent  # noqa: E402
import llm  # noqa: E402
import loop_check  # noqa: E402
import pipeline  # noqa: E402
import pivot  # noqa: E402
import prompt  # noqa: E402
import queryplan  # noqa: E402
import queries  # noqa: E402
import sparql_guard  # noqa: E402
import summarize  # noqa: E402
import typology  # noqa: E402
import unified  # noqa: E402
from ontop_run import run_ontop  # noqa: E402

# the gold stand-in for the model: one gold query per plan key (legs_bank_sparql returns the transaction variables the plan asks for and more)
GOLD = {"transaction": queries.legs_bank_sparql, "account": queries.context_sparql}


def extract_ids(question):
    seen, out = set(), []
    for n in re.findall(r"(?<![\w.])\d{4,}(?!\w|\.\d)", question):
        if int(n) not in seen:
            seen.add(int(n))
            out.append(int(n))
    return out


def ev(msg, obda="Data ontology", sql="SPARQL", role="transaction", pause=False, stage=None):
    """An event for the page: what is happening (a sentence for the chat log), which view to bring forward, and which step of the flow
    diagram (src/flow_view.py) it belongs to: intent, ids, typology, sparql, guard, ontop, db, candidate, shacl, answer."""
    return {"msg": msg, "obda": obda, "sql": sql, "role": role, "pause": pause, "stage": stage}


def technique_for_report(t):
    """The technique the question was read as, for the report: {id, name, tactic, how}. how = 'model' | 'investigator' | 'assumed' (gold mode has no reading of the question)."""
    it = t.get("intent")
    if it and it.get("technique"):
        return {"id": it["technique"], "name": it["name"], "tactic": it.get("tactic"), "how": "investigator" if it.get("source") == "investigator" else "model"}
    reg = indicators.registry()
    return {"id": reg["technique"], "name": reg["name"], "tactic": reg["tactic"]["name"], "how": "assumed"}


def run_guards(t, ids, notes, technique=None):
    """The SPARQL checks for each query (fast, no model, no Ontop). Fills each role's 'guard' and notes the rejected ones.
    technique: given in 'intent' mode, where each query is an intent-level one (sparql_guard.check_intent)."""
    for role, r in t["roles"].items():
        if r["sparql"] and not r["guard"]:
            r["guard"] = (sparql_guard.check_intent(r["sparql"], role, technique, ids) if technique
                          else sparql_guard.check(r["sparql"], r["vars"], ids))
        if r["guard"]:
            notes.append(f"{role} query rejected ({r['guard'][0][0]})")


def steps(question, mode="model", model=llm.DEFAULT_MODEL, temperature=0.3, summary="model", pick=None, enforce=True):
    t = {"question": question, "ids": extract_ids(question), "mode": mode, "roles": {}, "answer": None, "typology": None, "intent": None, "choices": [], "candidate_turtle": None,
         "summary": None, "status": "ok", "status_text": "", "model": model if mode in ("model", "intent") else None,
         "prompt_version": prompt.PROMPT_VERSION_INTENT if mode == "intent" else prompt.PROMPT_VERSION_PLAN, "plan": None, "llm_seconds": None, "summary_prompt_version": summarize.PROMPT_VERSION}
    ids = t["ids"]
    uses_model = mode in ("model", "intent")        # 'model': the model writes the queries of the plan; 'intent': it writes only intent-level ones; 'gold': no model
    # 0. Intent: which AML technique does the question describe? The model picks from the typology's list (read through Ontop) and code
    # checks the pick. In gold mode there is no model, so T0039 is assumed (that is what the gold queries are for).
    if uses_model:
        if pick:        # the investigator chose one of the techniques offered for this question: no model call
            t["intent"] = intent.from_pick(pick)
        else:
            yield t, ev(f"Intent · {model} is matching the question to a technique of the AML typology...", obda="AML typology", stage="intent")
            t["intent"] = intent.analyse(question, model=model, temperature=temperature)
        it = t["intent"]
        yield t, ev(intent.sentence(it), obda="AML typology", pause=True, stage="intent")
        if it["status"] != "ok":
            t["status"] = {"clarify": "clarify", "choose": "choose", "unsupported": "unsupported", "rejected": "intent_rejected", "error": "intent_error"}[it["status"]]
            t["status_text"] = intent.stop_text(it)
            t["choices"] = it.get("options", [])
            return
    if not ids:
        t["status"], t["status_text"] = "no_ids", "No transaction id found in the question. Include the ids, for example: ... ids 2131053, 2204314, 2282865."
        if t.get("intent"):
            t["status_text"] = f"This looks like {t['intent']['technique']} {t['intent']['name']}. To check it I need the transaction ids you suspect, for example: ... ids 2131053, 2204314, 2282865."
        yield t, ev("No transaction id found in the question.", stage="ids")
        return
    yield t, ev(f"Found {len(ids)} transaction ids: {ids}", pause=True, stage="ids")
    notes = []
    # The AML typology through Ontop (AMLO + AMLTRIX). Cached after the first question. It does not change the answer below, which
    # indicators.py still decides; it shows where the indicators and what they need come from, and is checked against the code.
    yield t, ev("AML typology · Ontop is reading AMLO + AMLTRIX...", obda="AML typology", stage="typology")
    t["typology"] = typology.read()
    yield t, ev(typology.sentence(t["typology"]), obda="AML typology", pause=True, stage="typology")
    if t["typology"]["error"] or not t["typology"]["check"]["ok"]:
        notes.append("the AML typology read through Ontop did not agree with the registry; see the AML typology view")
    technique = (t.get("intent") or {}).get("technique") or indicators.registry()["technique"]
    if mode == "intent":
        # the two intent-level queries: what to fetch is not planned here, the Alignment decides it inside Ontop (src/unified.py)
        specs = [{"key": "evidence", "label": f"Evidence · the indicators of {technique}", "serves": [i["id"] for i in indicators.registry()["indicators"]],
                  "vars": sparql_guard.INTENT_VARS["evidence"], "required": True},
                 {"key": "background", "label": "Background · accounts", "serves": ["background"], "vars": sparql_guard.INTENT_VARS["background"], "required": False}]
    else:
        specs = queryplan.plan()
    t["plan"] = specs
    for sp in specs:
        t["roles"][sp["key"]] = {"label": sp["label"], "serves": sp["serves"], "vars": sp["vars"], "required": sp["required"],
                                 "sparql": None, "guard": [], "reply": None, "llm_seconds": None, "sql": None, "ontop_seconds": None,
                                 "rows": None, "error": None}
    main = specs[0]["key"]
    # 1. the SPARQL for every query the plan asks for: in model mode the model is called once and answers with all of them
    if mode == "intent":
        yield t, ev(f"SPARQL · {model} is writing the intent-level queries (technique + ids only)...", stage="sparql")
        s_, u_ = prompt.build_intent(question, technique)
        try:
            reply, secs = llm.chat(s_, u_, model=model, temperature=temperature)
        except llm.LLMError as e:
            t["status"], t["status_text"] = "model_error", f"The model could not be reached: {e}"
            yield t, ev(t["status_text"], stage="sparql")
            return
        t["llm_seconds"] = round(secs, 1)
        found = prompt.extract_intent(reply)
        for role, r in t["roles"].items():
            r["reply"], r["llm_seconds"], r["sparql"] = reply, secs, found.get(role)
            if r["sparql"] is None:
                r["guard"] = [("no_sparql", f"the reply had no '{role}' query (expected a JSON object with the keys {', '.join(t['roles'])})")]
        run_guards(t, ids, notes, technique=technique)
        yield t, ev(f"SPARQL · the {len(specs)} intent-level queries written in {secs:.0f} s (the Alignment decides what to fetch)", pause=True, stage="sparql")
    elif mode == "gold":
        for sp in specs:
            t["roles"][sp["key"]]["sparql"] = GOLD[sp["key"]](ids)
        run_guards(t, ids, notes)
        yield t, ev(f"SPARQL · gold SPARQL for the {len(specs)} queries (no model)", pause=True, stage="sparql")
    else:
        yield t, ev(f"SPARQL · {model} is writing the {len(specs)} queries in one call...", stage="sparql")
        s_, u_ = prompt.build_plan(question, specs)
        try:
            reply, secs = llm.chat(s_, u_, model=model, temperature=temperature)
        except llm.LLMError as e:
            t["status"], t["status_text"] = "model_error", f"The model could not be reached: {e}"
            yield t, ev(t["status_text"], stage="sparql")
            return
        t["llm_seconds"] = round(secs, 1)
        found = prompt.extract_plan(reply, specs)
        for role, r in t["roles"].items():
            r["reply"], r["llm_seconds"], r["sparql"] = reply, secs, found.get(role)
            if r["sparql"] is None:
                r["guard"] = [("no_sparql", f"the reply had no '{role}' query (expected a JSON object with the keys {', '.join(t['roles'])})")]
        run_guards(t, ids, notes)       # before the event, so a rejected query is never shown as used
        yield t, ev(f"SPARQL · the {len(specs)} queries written in {secs:.0f} s, one call (ontology terms only)", pause=True, stage="sparql")
    # 2. what the checks said, for each of the three (run_guards above)
    bad = [role for role, r in t["roles"].items() if r["guard"]]
    first = bad[0] if bad else main
    if bad:
        yield t, ev("Query checks · " + "; ".join(f"{t['roles'][k]['label']} rejected: {t['roles'][k]['guard'][0][1][:110]}" for k in bad),
                    sql="Checks", role=first, pause=True, stage="guard")
    else:
        yield t, ev(f"Query checks passed for the {len(specs)} queries", sql="Checks", role=first, pause=True, stage="guard")
    must = [k for k in bad if t["roles"][k]["required"]]
    if must:
        t["status"], t["status_text"] = "rejected_by_guard", f"The query for {t['roles'][must[0]]['label']} was rejected before it reached the database: " + t["roles"][must[0]]["guard"][0][1]
        return
    # 3. Ontop writes the SQL for each query that passed, and runs it
    for role in t["roles"]:
        r = t["roles"][role]
        what = r["label"]
        if r["guard"]:
            continue
        yield t, ev(f"{what} · Ontop is writing the SQL and running it...", obda="R2RML", sql="SQL from Ontop", role=role, stage="ontop")
        if mode == "intent":      # one virtual graph over the typology and the data: Ontop joins the Alignment's needs with the data
            rows, sql, secs, err = unified.run(r["sparql"])
            if not err:
                r["long_rows"], r["used_terms"] = rows, pivot.terms_in(rows)
                rows = pivot.evidence(rows) if role == "evidence" else pivot.background(rows)
        else:
            rows, sql, secs, err = run_ontop(r["sparql"], normalize=False, ontology=data_ontology.merged_path())
        r["sql"], r["ontop_seconds"], r["rows"], r["error"] = sql, round(secs, 1), rows, err
        if err:
            yield t, ev(f"{what} · Ontop could not run the query: {err[:160]}", obda="R2RML", sql="SQL from Ontop", role=role, pause=True, stage="ontop")
            if r["required"]:
                t["status"], t["status_text"] = "ontop_error", "Ontop could not run the query: " + err[:300]
                return
            notes.append(f"{role} query failed in Ontop")
            continue
        got = (f"{len(r['long_rows'])} rows, one for each indicator, transfer and term, pivoted to {len(rows)} (the Alignment decided what to fetch)"
               if mode == "intent" else f"{len(rows)} rows (rewritten by the ontology and the mapping)")
        yield t, ev(f"{what} · Ontop returned {got}; SQL written by Ontop, not the model", obda="R2RML", sql="Rows", role=role, pause=True, stage="db")
    try:
        legs = pipeline.parse_legs(t["roles"][main]["rows"])
    except (pipeline.MissingColumns, ValueError, KeyError) as e:
        t["status"], t["status_text"] = "rejected_later", f"The rows returned for the transactions are not usable: {e}"
        yield t, ev(t["status_text"], sql="Rows", stage="candidate")
        return
    context = []
    ctx = t["roles"].get("account") or t["roles"].get("background")
    if ctx and ctx["rows"] is not None:
        try:
            context = pipeline.parse_context(ctx["rows"])
        except (pipeline.MissingColumns, ValueError, KeyError) as e:
            notes.append(f"the account-background query returned unusable rows ({str(e)[:80]}); background not shown")
    yield t, ev("Code built the candidate loop: sorted by time, origin = first payer", obda="SHACL check", sql="Rows", role=main, stage="candidate")
    rep = indicators.report(legs)
    t["answer"] = {"asked": ids, "missing_ids": sorted(set(ids) - {x["tx_id"] for x in legs}), "legs": legs, "order": rep["order"],
                   "indicators": rep["indicators"], "context": context, "question": question, "technique": technique_for_report(t)}
    g, _ = loop_check.assemble(legs)
    g.bind("ex", "https://example.org/rules#")
    t["candidate_turtle"] = g.serialize(format="turtle")
    e1 = next(e for e in rep["indicators"] if e["id"] == "IND02191")
    verdict = ("the structure matches the description" if e1["state"] == "held"
               else "the structure does not match (" + ", ".join(e1["failed"]) + ")")
    yield t, ev(f"SHACL · IND02191: {verdict}",
                obda="SHACL check", sql="Rows", role=main, pause=True, stage="shacl")
    names = {i["id"]: i["text"] for i in indicators.registry()["indicators"]}
    if summary == "model" and uses_model:
        yield t, ev(f"{model} is writing the summary" + ("; code will check it..." if enforce else " (the rules are not enforced)..."), obda="SHACL check", sql="Rows", stage="answer")
        text, src, problems, secs = summarize.llm_summary(t["answer"], names, model=model, temperature=temperature, enforce=enforce)
    else:
        text, src, problems, secs = summarize.template(t["answer"], names), "template", [], 0.0
    t["summary"] = {"text": text, "source": src, "problems": problems, "seconds": round(secs, 1), "enforced": enforce}
    t["status_text"] = "; ".join(notes)
    yield t, ev("Summary ready" + (" (the model's was rejected by the checks; fixed template used)" if problems and src == "template" else ""), obda="SHACL check", sql="Rows", stage="answer")


def run(question, mode="model", model=llm.DEFAULT_MODEL, temperature=0.3, summary="model", pick=None, enforce=True):
    """The whole chain without a page: returns the final trace."""
    t = None
    for t, _event in steps(question, mode, model, temperature, summary, pick, enforce):
        pass
    return t
