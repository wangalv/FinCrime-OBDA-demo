"""AML OBDA Demo: a local page that shows one question going through the chain.

Run from the repo root:   .venv/bin/streamlit run app/streamlit_app.py
Left: the investigator's chat. Right: what happened behind it: OBDA (ontology, R2RML mapping, SHACL check), then the SPARQL, SQL and rows,
then the summary. It needs Ontop (tools/) and the database; the model path also needs Ollama with qwen3.5:9b.
"""
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from rdflib import RDF, RDFS, Graph, Namespace
from rdflib.namespace import OWL

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import baseline  # noqa: E402
import data_ontology  # noqa: E402
import demo_run  # noqa: E402
import flow_view  # noqa: E402
import graph_view  # noqa: E402
import indicators  # noqa: E402
import llm  # noqa: E402
import paths  # noqa: E402
import typology  # noqa: E402

RR = Namespace("http://www.w3.org/ns/r2rml#")
FCD = "https://example.org/fincrime-data#"
TABLE_NOTE = {"tx": "tx_features", "kyc": "kyc_profiles"}
STATE_ICON = {"held": "✅ structure matches", "not_held": "❌ does not match", "cannot_check": "➖ cannot check",
              "facts_only": "ℹ️ facts only"}
LEGEND = {"text": "close to the typology text", "read": "our reading", "added": "added by decision", "structure": "needed to build the candidate",
          "data": "data availability"}

st.set_page_config(page_title="AML OBDA Demo", page_icon="🔎", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
.block-container h5 {white-space: nowrap; font-size: 1rem; margin: 0; padding-bottom: 0.3rem;}
.block-container {padding-top: 4.2rem; padding-bottom: 0.5rem; padding-left: 1.5rem; padding-right: 1.5rem; max-width: 1900px;}
h1, h2, h3 {margin-bottom: 0.3rem;} h4 {margin: 0 0 0.3rem 0;}
/* the sidebar's own header (it holds the collapse button) is 60px high and the title has 20px of padding on top: tighten both so the title sits higher */
[data-testid="stSidebarHeader"] {height: 40px !important; min-height: 40px !important;}
[data-testid="stSidebar"] h1 {padding-top: 0 !important;}
.arrow {text-align:center; font-size: 26px; line-height: 1; margin: -4px 0 4px 0; opacity: .6;}
.small {font-size: 0.85rem; opacity: .75;}
/* the chat area (the first of the two top-level columns; it holds the two chat panels side by side) is at most 800px wide, so on a wide window the extra width
   goes to the diagrams on the right. The selector does not match the two panels inside it (they are in a horizontal block that is itself inside a column). */
[data-testid="stColumn"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child {max-width: none;}
.block-container > div > div > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child {max-width: 800px;}
/* the chat input is one line high by default: make the box taller (Streamlit fixes the height of the rounded box, so it is overridden too) */
[data-testid="stChatInput"] {height: auto !important; min-height: 130px !important;}
[data-testid="stChatInput"] > div {height: auto !important; min-height: 130px !important; border-radius: 14px !important; align-items: flex-end !important;}
[data-testid="stChatInput"] textarea {min-height: 110px !important;}
</style>""", unsafe_allow_html=True)


# what each gold case is, in a few words (the dropdown is narrow and the case ids mean nothing to the person using it); the first prefix that matches wins
CASE_LABEL = [("F1-loop3-unlabelled", "Unlabelled loop"), ("F1-loop3", "Three-leg loop"), ("F1-loop4", "Four-leg loop"), ("F1-chain", "Chain, no return"),
              ("F1-open-from-loop3", "Open loop, 2 of 3 legs"), ("F1-open-from-loop4", "Open loop, 3 of 4 legs"), ("F1-out-of-order", "Wrong time order"),
              ("F1-roundtrip", "Two-leg round trip"), ("F1-unrelated", "Unrelated transactions"), ("F1-missing-id", "Loop plus a missing id")]
WORDING = (0,)                                      # the wording offered: 0 is the English one (the Chinese wording, 6, is not offered)


def examples():
    """{label: question} for the dropdown: one example for each kind of case (the first case of that kind), named by what it is, not by its id."""
    cases = json.loads((ROOT / "gold" / "cases.json").read_text())["cases"]
    out = {}
    for c in cases:
        t = next((t for pre, t in CASE_LABEL if c["id"].startswith(pre)), c["what"][:30])
        if t not in out:
            out[t] = c["questions"][WORDING[0]]
    return out


@st.cache_data
def ontology_rows():
    """The data terms (fcd:) and the AML terms (amd:) Ontop is given, with the bridge between them: 'bridge' says what a term sits under, or is answered by."""
    g = data_ontology.graph()
    br = data_ontology.bridges()
    rows = []
    for ns, tag in (("amd", "AML term"), ("fcd", "data term")):
        for kind, label in ((OWL.Class, "class"), (OWL.ObjectProperty, "link"), (OWL.DatatypeProperty, "value")):
            for s in sorted(g.subjects(RDF.type, kind)):
                if not str(s).startswith(data_ontology.PREFIXES[ns]):
                    continue
                t = data_ontology.short(s)
                bridge = ("under " + ", ".join(br[t])) if t in br else ("answered by " + ", ".join(data_ontology.below(t)) if data_ontology.below(t)
                                                                      else ("no data term under it: the data cannot answer it" if ns == "amd" else ""))
                rows.append({"term": t, "kind": f"{tag}, {label}", "of": (data_ontology.short(g.value(s, RDFS.domain)) if g.value(s, RDFS.domain) else ""),
                             "bridge": bridge, "meaning": str(g.value(s, RDFS.comment) or "")})
    return rows


@st.cache_data
def mapping_rows():
    g = Graph()
    for m in paths.DATA_MAPPINGS:
        g.parse(m)
    rows = []
    for tm in g.subjects(RDF.type, RR.TriplesMap):
        table = str(g.value(g.value(tm, RR.logicalTable), RR.tableName))
        sm = g.value(tm, RR.subjectMap)
        tmpl = str(g.value(sm, RR.template))
        cls = g.value(sm, RR["class"])
        if cls is not None:
            rows.append({"term": "fcd:" + str(cls)[len(FCD):], "from table": TABLE_NOTE.get(table, table), "column / template": tmpl})
        for pom in g.objects(tm, RR.predicateObjectMap):
            om = g.value(pom, RR.objectMap)
            col, tp = g.value(om, RR.column), g.value(om, RR.template)
            rows.append({"term": "fcd:" + str(g.value(pom, RR.predicate))[len(FCD):], "from table": TABLE_NOTE.get(table, table),
                         "column / template": str(col) if col is not None else str(tp)})
    return rows


COLS = {"kind": st.column_config.TextColumn(width="small"), "bridge": st.column_config.TextColumn(width="medium"),
        "of": st.column_config.TextColumn(width="small"), "meaning": st.column_config.TextColumn(width="large"),
        "term": st.column_config.TextColumn(width="medium"), "column / template": st.column_config.TextColumn(width="large"),
        "what it checks": st.column_config.TextColumn(width="large")}


def used_terms(trace):
    """Terms the queries of this run use, and what they stand for: an AML term marks the data terms under it, and the other way round."""
    text = " ".join((r["sparql"] or "") for r in (trace or {}).get("roles", {}).values())
    used = graph_view.terms_in(text) | {x for r in (trace or {}).get("roles", {}).values() for x in r.get("used_terms", [])}      # intent mode: the terms the rows came back for
    used |= {up for t in used for up in data_ontology.bridges().get(t, [])}
    return used | data_ontology.expand(used)


GREEN = "background-color: rgba(46, 160, 67, 0.28)"


def mark(rows, used):
    """Table with the rows whose term the queries of this run use shaded green."""
    df = pd.DataFrame(rows)
    return df.style.apply(lambda r: [GREEN if r["term"] in used else ""] * len(r), axis=1)


AMBER = "background-color: rgba(210, 153, 34, 0.30)"


def render_typology(ty):
    """What Ontop read from AMLO + AMLTRIX about T0039, and which indicators this data can answer."""
    if ty is None:
        with st.spinner("Ontop is reading the AML typology..."):
            ty = typology.read()
    if ty["error"]:
        st.warning("Ontop could not read the typology: " + ty["error"][:200])
        return
    st.caption(f"{ty['technique_id']} {ty['technique']} · tactic: {ty['tactic']} · read by Ontop from AMLTRIX. "
               "Green = the data has every term the indicator needs; amber = some of them.")
    df = pd.DataFrame([{"indicator": e["id"], "what it says": e["text"], "needs (our draft reading)": ", ".join(e["needs"]),
                        "missing in the data": ", ".join(e["missing"]), "_a": e["answerability"]} for e in ty["indicators"]])
    colour = {"answerable": GREEN, "partial": AMBER}
    styled = df.style.apply(lambda r: [colour.get(r["_a"], "")] * len(r), axis=1)
    st.dataframe(styled, hide_index=True, use_container_width=True, height=190,
                 column_config={"_a": None, "indicator": st.column_config.TextColumn(width="small"),
                                "what it says": st.column_config.TextColumn(width="medium"),
                                "needs (our draft reading)": st.column_config.TextColumn(width="medium"),
                                "missing in the data": st.column_config.TextColumn(width="medium")})
    if ty.get("sources"):
        st.caption("Data sources the typology lists for this technique (relationship `isIdentifiedIn`). Which AML terms each source holds, and which table "
                   "provides it, are our draft reading. Green = this database answers all its terms; amber = some; blue = background only.")
        scol = {"available": GREEN, "partial": AMBER, "background_only": "background-color: rgba(56, 139, 253, 0.25)"}
        sdf = pd.DataFrame([{"source": f"{x['id']} {x['name']}", "state": x["state"].replace("_", " "),
                             "terms recorded in it": ", ".join(t.split(":")[1] for t in x["terms"]),
                             "not answered": ", ".join(t.split(":")[1] for t in x["missing"]),
                             "provided by table": ", ".join(m["table"] or m["map"] for m in x["realised_by"]), "_s": x["state"]} for x in ty["sources"]])
        st.dataframe(sdf.style.apply(lambda r: [scol.get(r["_s"], "")] * len(r), axis=1), hide_index=True, use_container_width=True, height=250,
                     column_config={"_s": None})
    st.caption(("Check against the code (indicators.py, sources.py): same indicators, text, needs, missing terms and data sources." if ty["check"]["ok"]
                else "Check against the code FAILED: " + "; ".join(ty["check"]["problems"])) + f"  ·  {ty['seconds']} s")
    with st.expander("How Ontop answered"):
        st.caption("Indicators and their text come from the AMLTRIX CSVs through the R2RML mapping. The tactic is asked as `achievesTactic` but the data "
                   "only holds `isAchievedBy`: AMLO's `inverseOf` bridges them. What an indicator needs and which data terms exist are our "
                   "alignment facts (a draft reading, not part of AMLTRIX); 'missing' is a SPARQL `FILTER NOT EXISTS` over them.")
        st.code(ty["sparql"]["overview"], language="sparql")
        st.code(ty["sparql"]["missing"], language="sparql")
        if ty["sparql"].get("sources"):
            st.code(ty["sparql"]["sources"], language="sparql")


def render_graph(trace):
    """The T0039 typology as a graph: what this run touches is lit; what is new at this step flashes once."""
    cur = graph_view.lit(trace)
    new = graph_view.changed(cur, st.session_state.get("lit_shown"))
    st.session_state.lit_shown = cur
    ty = (trace or {}).get("typology") or {}
    components.html(graph_view.iframe_page(cur, new, tactic=ty.get("tactic"), technique=ty.get("technique")), height=380)
    st.caption(graph_view.LEGEND_LINE + "  ·  verdict colours come from indicators.py, dashed lines are our draft reading of what an indicator needs")


def render_flow(trace, stage):
    """The chain as a flow diagram under the graph. Drawn from the same trace and event as the graph, so the two light up together."""
    cur = flow_view.states(trace, stage)
    new = flow_view.changed(cur, st.session_state.get("flow_shown"))
    st.session_state.flow_shown = cur
    mode = (trace or {}).get("mode")
    lane = st.session_state.get("baseline_state") or "waiting"      # the Without OBDA lane under the chain (every question runs both)
    components.html(flow_view.iframe_page(trace, stage, new, mode=mode, lane=lane), height=flow_view.height(mode, lane))
    st.caption(flow_view.LEGEND_INTENT if mode == "intent" else flow_view.LEGEND_LINE)


def save_failed_run(trace, question, mode, model, temperature):
    """A run that stopped is saved whole (question, settings, trace) under generated/failed_runs/, so it can be looked at later. Returns the path or None."""
    try:
        d = ROOT / "generated" / "failed_runs"
        d.mkdir(parents=True, exist_ok=True)
        f = d / (time.strftime("%Y%m%d-%H%M%S") + f"-{trace['status']}.json")
        f.write_text(json.dumps({"question": question, "mode": mode, "model": model, "temperature": temperature, "trace": trace}, indent=1,
                                ensure_ascii=False, default=str), encoding="utf-8")
        return str(f.relative_to(ROOT))
    except OSError:
        return None


def render_baseline(b):
    """What Qwen said when it was given only the table rows (the 'Without ontology' panel): a yes / no and the same five parts as the other side."""
    if b["error"]:
        st.warning(b["error"])
        return
    if b.get("total_seconds") is not None:
        st.caption(f"⏱ {b['total_seconds']} s")           # reading the rows plus the model call, first line of the reply
    mark_ = {"yes": "✅ yes", "no": "❌ no", "cannot tell": "➖ cannot tell"}.get(b["answer"], "⚠️ no clear yes/no")
    st.markdown(f"**Does it fit? {mark_}**")
    st.markdown(b["explanation"] or b["reply"] or "")
    miss = f" Ids not in the table: {b['missing_ids']}." if b["missing_ids"] else ""
    st.caption(f"Qwen saw only {len(b['rows'])} rows of the transaction table ({len(b['columns'])} fields), no typology, rules or customer profiles.{miss} "
               f"{b['model']}, {b['seconds']} s, prompt {b['prompt_version']}. One run, not a measurement.")


def business_note(notes):
    """The run's technical notes (e.g. 'account query rejected (syntax)') as one sentence for the investigator; the exact notes stay in the process log."""
    if not notes:
        return ""
    if "account" in notes or "background" in notes:
        return "The customer profiles of the accounts could not be retrieved this time, so no account background is shown."
    return "Part of the checking could not be completed this time; the details are under 'How this answer came about'."


def chips(ans):
    return "  \n".join(f"`{e['id']}` {STATE_ICON[e['state']]}" for e in ans["indicators"][:2])


# ------------------------------------------------------------------ the right-hand side, drawn from a trace (and redrawn at every step)
H_OBDA, H_SQL, H_SUM, H_CHAT = 330, 300, 190, 650


def short_iri(v):
    """A cell for display: a full IRI becomes its prefix and last part (fcd:fromAccount, amd:originator) or just its last part (an account id)."""
    if not isinstance(v, str) or not v.startswith("http"):
        return v
    for pre, ns in data_ontology.PREFIXES.items():
        if v.startswith(ns):
            return f"{pre}:{v[len(ns):]}"
    return re.split(r"[/#]", v.rstrip("/"))[-1]


def short_rows(rows):
    """The rows of a result table with every IRI shortened (the data itself is unchanged; this is only for the page)."""
    return [{k: short_iri(v) for k, v in r.items()} for r in rows]


def pick(label, options, default, key):
    return st.segmented_control(label, options, default=default if default in options else options[0], key=key, label_visibility="collapsed") or options[0]


def render_right(trace, focus, key):
    ans = trace["answer"] if trace else None
    used = used_terms(trace)
    reg = indicators.registry()
    with st.container(height="content", border=True):
        st.markdown("#### OBDA · Ontology-Based Data Access")
        # The row of tabs (Graph, Data ontology, R2RML, AML typology, SHACL check) was taken out at the user's request: only the Graph is shown. The
        # other views below are kept but cannot be reached; to bring them back, make `view` a pick(...) over those names again.
        view = "Graph"
        if view != "Graph":
            st.session_state.lit_shown = graph_view.lit(trace)   # keep "what is new" in step with the chain even when the graph is not shown
        if view == "Graph":
            render_graph(trace)
        elif view == "Data ontology":
            st.caption("What Ontop is given for the data: our data terms (fcd:), the AML terms indicators talk about (amd:), and the bridge between them. The model writes in these terms (not the AML typology). Green rows = used by the queries in this run.")
            st.dataframe(mark(ontology_rows(), used), hide_index=True, use_container_width=True, height=190, column_config=COLS)
        elif view == "R2RML":
            st.caption("How each term is read from the database. The model never sees table or column names. Green rows = used in this run.")
            st.dataframe(mark(mapping_rows(), used), hide_index=True, use_container_width=True, height=190, column_config=COLS)
            st.caption("`tx` and `kyc` are lenses over `tx_features` and `kyc_profiles` (they declare the key, so Ontop does not self-join).")
        elif view == "AML typology":
            render_typology((trace or {}).get("typology"))
        elif ans is None:
            st.caption("Runs on the candidate loop built from the transactions that come back. It appears when the rows are in.")
        else:
            st.caption("Rules applied to the candidate loop. SHACL checks the structure of what was retrieved; it does not search for loops.")
            st.dataframe([{"indicator": e["id"], "result": STATE_ICON[e["state"]],
                           "detail": (", ".join(e["failed"]) if e["failed"] else "") or ("missing: " + ", ".join(e["missing_terms"])
                                                                           + (" (would be in: " + "; ".join(x["name"] for x in e["missing_sources"]) + ")"
                                                                              if e.get("missing_sources") else "") if e["missing_terms"] else "")}
                          for e in ans["indicators"]], hide_index=True, use_container_width=True)
            rules = []
            for ind in reg["indicators"]:
                e = next(x for x in ans["indicators"] if x["id"] == ind["id"])
                for r in ind["rules"]:
                    info = reg["rule_info"][r]
                    rules.append({"indicator": ind["id"], "rule": r, "result": "warning" if r in e["warnings"] else ("violated" if r in e["failed"] else "passed"),
                                  "source": LEGEND[info["source"]], "what it checks": info["text"]})
            st.markdown("**Rules (IND02191, IND02195)**")
            st.dataframe(rules, hide_index=True, use_container_width=True, column_config=COLS)
            with st.expander("Candidate loop (RDF) that SHACL validated"):
                st.code(trace["candidate_turtle"], language="turtle")
            with st.expander("Not checked, by indicator"):
                for e in ans["indicators"]:
                    if e["not_checked"]:
                        st.markdown(f"**{e['id']}**: " + "; ".join(e["not_checked"]))

    with st.container(border=True):
        render_flow(trace, focus.get("stage"))

    st.markdown('<div class="arrow">⬇</div>', unsafe_allow_html=True)

    with st.container(height=H_SQL, border=True):
        st.markdown("#### SQL & Result")
        if trace is None or not trace["roles"]:
            st.caption("The SPARQL, the SQL that Ontop wrote from it, and the rows it returned appear here as they are produced.")
        else:
            roles = list(trace["roles"])
            role = pick("Query", roles, focus.get("role"), f"role_{key}")
            st.caption("Query: " + trace["roles"][role]["label"])
            r = trace["roles"][role]
            sview = pick("Detail", ["SPARQL", "SQL from Ontop", "Rows", "Checks"], focus.get("sql"), f"sql_{key}")
            if sview == "SPARQL":
                if trace["mode"] in ("model", "intent"):
                    secs = f" in {r['llm_seconds']:.0f} s" if r["llm_seconds"] is not None else ""
                    what = "intent-level queries (technique + ids only)" if trace["mode"] == "intent" else "queries"
                    st.caption(f"Written by {trace['model']}{secs}, one call for the {len(trace['roles'])} {what}  ·  prompt {trace['prompt_version']}" if (r["sparql"] or r["reply"]) else f"{trace['model']} is writing...")
                else:
                    st.caption("Gold SPARQL (no model)")
                st.code(r["sparql"] or r["reply"] or "(waiting)", language="sparql")
            elif sview == "SQL from Ontop":
                if r["sql"]:
                    st.caption(f"Ontop, {r['ontop_seconds']} s. Written by the rewriter from the mapping, not by the model.")
                    st.code(r["sql"], language="sql")
                else:
                    st.caption("Not yet, or the query did not reach the database.")
            elif sview == "Rows":
                if r["rows"] is not None:
                    if r.get("long_rows") is not None:
                        st.caption("What Ontop returned: one row for each indicator, transfer, term and value. The term is bound by the Alignment, not named in the query.")
                        st.dataframe(short_rows(r["long_rows"]), hide_index=True, use_container_width=True, height=150)
                        st.caption("After pivoting (code): one row for each transfer or account, the rows the next steps read.")
                    st.dataframe(short_rows(r["rows"]), hide_index=True, use_container_width=True)
                    st.caption("Web addresses (IRIs) are shortened for display: an account id is its last part, ontology terms keep their prefix.")
                elif r["error"]:
                    st.error(r["error"][:400])
                else:
                    st.caption("No rows yet.")
            else:
                if r["guard"]:
                    for name, msg in r["guard"]:
                        st.error(f"**{name}**: {msg}")
                elif r["sparql"]:
                    st.success("Passed the query checks: parses, SELECT only, only terms of the ontology, the required variables, the ids match the question.")
                else:
                    st.caption("Waiting for the query.")
                st.caption("Not checked: whether the query means what the investigator asked. That is measured against the gold, not here.")

    with st.container(height=H_SUM, border=True):
        st.markdown("#### LLM summarized response")
        if trace is None or trace["summary"] is None:
            st.caption("The summary of the per-indicator results appears here.")
        else:
            sm = trace["summary"]
            st.markdown(sm["text"])
            by = 'the model, ' + str(sm['seconds']) + ' s' if sm['source'] == 'model' else 'a fixed template'
            if sm.get("enforced", True):
                st.caption(f"Written by {by}  ·  checked for verdict words, claims about places, stray numbers and business-rationale claims"
                           "  ·  not checked: whether every sentence is faithful.")
            else:
                st.caption(f"Written by {by}  ·  the rules were not applied (Checked by code is off).")
            for p_ in sm["problems"]:
                st.warning(("Not enforced; the rules would have flagged: " + p_) if sm["source"] == "model" else p_)


# ------------------------------------------------------------------ state
st.session_state.setdefault("history", [])
st.session_state.setdefault("trace", None)
st.session_state.setdefault("focus", {})
st.session_state.setdefault("tid", 0)

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("AML OBDA Demo")
    st.caption("T0039 Circular Transactions. A small local model writes SPARQL over ontology terms; Ontop turns it into SQL; "
               "SHACL checks the structure of what comes back. Every question also goes to Qwen on its own, given only the table rows (no OBDA), for comparison.")
    mode = "model"          # Qwen writes the SPARQL (the intent-only and gold modes are still in demo_run, but the page no longer offers them)
    model = st.text_input("Model (Ollama)", llm.DEFAULT_MODEL, disabled=(mode == "gold"))
    temperature = st.slider("Temperature", 0.0, 1.0, 0.3, 0.1, disabled=(mode == "gold"))
    enforce = st.checkbox("Checked by code", value=False, disabled=(mode == "gold"),
                          help="On: Qwen writes the summary and code checks it against the rules (verdict words, technical words, places, stray numbers, "
                               "business-rationale claims); a summary that breaks a rule is replaced by a fixed template. "
                               "Off: Qwen's summary is shown as it is.")
    summary = "model" if mode != "gold" else "template"
    pause = st.slider("Pause between steps (s)", 0.0, 2.0, 0.5, 0.1, help="Slows the quick steps down so each one can be seen.")
    st.divider()
    ex = examples()
    pick_ex = st.selectbox("Example questions", list(ex))
    ask_example = st.button("Ask this example", use_container_width=True)
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.history, st.session_state.trace, st.session_state.focus = [], None, {}
        st.rerun()
    st.divider()
    st.caption("Account background comes from a synthetic KYC table (not IBM data). Typology text: AMLTRIX 1.0-beta.4 by UAB Amlyze, "
               "used under the AMLTRIX License Terms; not endorsed by AMLTRIX.")

EXAMPLE = ("For example: *The alert flagged these transfers. The money seems to go round in a circle and come back to where it started. "
           "The ids are 2131053, 2204314, 2282865.*")                      # shown in both chat panels before the first question
left, right = st.columns([4, 5], gap="medium")
with left:
    pw, po = st.columns(2, gap="small")
    pw.markdown("##### Without ontology")                     # the headings sit above the boxes; the right column gets an invisible one so the tops stay level
    po.markdown("##### With ontology")
    chat_w = pw.container(height=H_CHAT, border=True)         # Qwen alone, given only the table rows
    chat_o = po.container(height=H_CHAT, border=True)         # the whole chain: typology, ontology, mapping, rules
    typed = st.chat_input("Describe the suspicious pattern and give the flagged transaction ids")
right.markdown("##### &nbsp;")
holder = right.empty()

def choose_cb(q, tid, label):
    """The investigator clicked one of the techniques offered for their question: ask the same question again with that choice."""
    st.session_state.pick = {"question": q, "technique": tid, "label": label}


chosen = st.session_state.pop("pick", None)       # (not named `pick`: that is the selector helper above)
question = typed or (ex[pick_ex] if ask_example else None)
if question:
    chosen = None                                # a new question wins over a click that has not been answered yet
elif chosen:
    question = chosen["question"]
shown = f"I choose {chosen['label']}." if chosen else question

with chat_w:
    if not st.session_state.history and not question:
        st.info(EXAMPLE)
    for m in st.session_state.history:
        if m["role"] == "user":
            with st.chat_message("user"):
                st.markdown(m["text"])
        else:
            with st.chat_message("assistant"):
                if m.get("baseline"):
                    render_baseline(m["baseline"])
                else:
                    st.caption("Not run for this question (no transaction ids to read, or the question was not understood).")
    if question:
        with st.chat_message("user"):
            st.markdown(shown)
        with st.chat_message("assistant"):
            status_w = st.status("Waiting for the other side to finish...", expanded=False)

with chat_o:
    if not st.session_state.history and not question:
        st.info(EXAMPLE)
    for i, m in enumerate(st.session_state.history):
        with st.chat_message(m["role"]):
            if m.get("secs") is not None:
                st.caption(f"⏱ {m['secs']} s")            # processing time of the whole chain, first line of the reply
            st.markdown(m["text"])
            if m.get("choices") and i == len(st.session_state.history) - 1 and not question:      # only the latest offer can be answered
                for o in m["choices"]:
                    st.button(f"{o['id']} {o['name']}" + (" (can check)" if o["supported"] else " (cannot check here)"), key=f"pick_{i}_{o['id']}",
                              on_click=choose_cb, args=(m["question"], o["id"], f"{o['id']} {o['name']}"))
            if m.get("chips"):
                st.markdown(m["chips"])
            if m.get("log"):
                with st.expander("How this answer came about"):
                    for line in m["log"]:
                        st.markdown("- " + line)
    if question:
        with st.chat_message("user"):
            st.markdown(shown)
        with st.chat_message("assistant"):
            status = st.status("Working on it...", expanded=True)

if question:
    st.session_state.history.append({"role": "user", "text": shown})
    st.session_state.baseline_state = None
    st.session_state.tid += 1
    tid, n, log, trace = st.session_state.tid, 0, [], None
    t_chain, paused = time.perf_counter(), 0.0           # processing time of the whole chain, without the pauses the sidebar adds between steps
    for trace, event in demo_run.steps(question, mode=mode, model=model, temperature=temperature, summary=summary,
                                          pick=chosen["technique"] if chosen else None, enforce=enforce):
        n += 1
        log.append(event["msg"])
        status.write("• " + event["msg"])
        st.session_state.focus = {"obda": "Graph", "sql": event["sql"], "role": event["role"], "stage": event["stage"]}
        with holder.container():
            render_right(trace, st.session_state.focus, f"{tid}_{n}")
        if event["pause"] and pause:
            time.sleep(pause)
            paused += pause
    chain_secs = round(time.perf_counter() - t_chain - paused, 1)
    st.session_state.trace = trace
    base = None             # "Without ontology": after the chain, Qwen on its own reads the table rows (its lane in the flow diagram lights for this call)
    if trace["ids"] and trace["status"] not in ("clarify", "choose", "unsupported", "intent_rejected", "intent_error", "no_ids"):
        status_w.update(label=f"{model} is reading the table rows on its own...", state="running", expanded=True)
        st.session_state.baseline_state = "active"
        with holder.container():
            render_right(trace, {**st.session_state.focus, "stage": None}, f"{tid}_base")
        t_base = time.perf_counter()
        base = baseline.run(question, trace["ids"], model=model, temperature=temperature)
        base["total_seconds"] = round(time.perf_counter() - t_base, 1)         # reading the rows plus the model call
        st.session_state.baseline_state = "fail" if base["error"] else "done"
        status_w.update(label="Done" if not base["error"] else "Stopped", state="complete" if not base["error"] else "error", expanded=False)
    else:
        status_w.update(label="Not run", state="complete", expanded=False)
    if trace["status"] == "ok":
        text = trace["summary"]["text"]
        if trace["summary"]["source"] == "model" and trace["summary"]["problems"]:         # checking is off and the rules would have rejected this report
            text += "\n\n*Checking is off. The rules would have flagged: " + "; ".join(trace["summary"]["problems"]) + ".*"
        if trace["status_text"]:
            text += f"\n\n*Note: {business_note(trace['status_text'])}*"
            log.append("Note: " + trace["status_text"])
        status.update(label="Done", state="complete", expanded=False)
        st.session_state.history.append({"role": "assistant", "text": text, "chips": chips(trace["answer"]), "log": log, "baseline": base, "secs": chain_secs})
    elif trace["status"] == "choose":                                   # the assistant offers a few techniques; the buttons are drawn under this message
        status.update(label="Choose one", state="complete", expanded=False)
        st.session_state.history.append({"role": "assistant", "text": trace["status_text"], "log": log, "choices": trace["choices"], "question": question, "secs": chain_secs})
    elif trace["status"] in ("clarify", "no_ids", "unsupported"):      # not a failure: the assistant asks, or says what it cannot check
        status.update(label="Needs more detail" if trace["status"] != "unsupported" else "Cannot check", state="complete", expanded=False)
        st.session_state.history.append({"role": "assistant", "text": trace["status_text"], "log": log, "secs": chain_secs})
    else:
        status.update(label="Stopped", state="error", expanded=False)
        saved = save_failed_run(trace, question, mode, model, temperature)
        why = trace["status_text"] or f"The run stopped (status '{trace['status']}') without saying why."
        st.session_state.history.append({"role": "assistant", "text": "⚠️ " + why + (f"\n\n*Saved to `{saved}` for inspection.*" if saved else ""),
                                         "log": log, "baseline": base, "secs": chain_secs})
    st.session_state.final_key = f"{tid}_final"
    st.rerun()

with holder.container():
    render_right(st.session_state.trace, st.session_state.focus, st.session_state.get("final_key", "0"))
