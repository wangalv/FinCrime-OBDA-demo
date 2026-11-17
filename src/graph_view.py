"""A graph of the AML typology (T0039) and what of it a run touches: nodes light up as the chain goes on.

Columns, left to right:
  tactic -> technique -> indicators (-> SHACL rules) -> data terms (data ontology) -> database columns (through the R2RML mapping)
Everything is derived, not drawn by hand: indicators and what they need from validation/indicator_registry.json (src/indicators.py),
the terms from ontology/alignment/source_vocabulary.ttl, the term -> column links from mappings/transaction/tx_features.r2rml.ttl and customer.r2rml.ttl, the tactic / technique names
from what Ontop read (src/typology.py).

lit(trace) says which node or edge is in which state at this point of the chain; render(...) draws the SVG for it.
States (a node or edge has at most one; later stages overwrite earlier ones):
  read     read by Ontop from AMLTRIX (tactic, technique, indicators)
  present  a data term an indicator needs, and the data ontology has it
  missing  a data term an indicator needs, and the data ontology does not have it
  used     used by a query that passed the checks (term), or that Ontop ran (column)
  held / not_held / facts_only / cannot_check   the answer for an indicator (decided by indicators.py, not by Ontop)
  shacl    the SHACL rules that checked the candidate loop
The "needs" links are our draft reading (AMLTRIX does not say which data an indicator needs).
"""
import html
import re
import sys
from pathlib import Path

from rdflib import RDF, Graph, Namespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_ontology  # noqa: E402
import indicators  # noqa: E402
import paths  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RR = Namespace("http://www.w3.org/ns/r2rml#")
FCD = "https://example.org/fincrime-data#"
TABLE = {"tx": "tx_features", "kyc": "kyc_profiles"}
SHACL_INDICATORS = ("IND02191", "IND02195")
VERDICT_TEXT = {"held": "structure matches", "not_held": "does not match", "facts_only": "facts only", "cannot_check": "cannot check",
                "read": "read from AMLTRIX", "used": "used in this run", "shacl": "SHACL rules"}
W, H = 1000, 480
Y0, Y1 = 38, 470


def term_columns():
    """Term -> list of 'table.column' it is read from: the R2RML mapping for a data term, and through the bridge for an AML term."""
    g = Graph()
    for m in paths.DATA_MAPPINGS:
        g.parse(m)
    out = {}

    def add(term, table, text):
        for col in re.findall(r"\{(\w+)\}", text) or [text]:
            lab = f"{table}.{col}"
            if lab not in out.setdefault(term, []):
                out[term].append(lab)

    for tm in g.subjects(RDF.type, RR.TriplesMap):
        table = TABLE.get(str(g.value(g.value(tm, RR.logicalTable), RR.tableName)), "?")
        sm = g.value(tm, RR.subjectMap)
        cls = g.value(sm, RR["class"])
        if cls is not None:
            add("fcd:" + str(cls)[len(FCD):], table, str(g.value(sm, RR.template)))
        for pom in g.objects(tm, RR.predicateObjectMap):
            om = g.value(pom, RR.objectMap)
            col, tp = g.value(om, RR.column), g.value(om, RR.template)
            add("fcd:" + str(g.value(pom, RR.predicate))[len(FCD):], table, str(col) if col is not None else str(tp))
    for data, ups in data_ontology.bridges().items():          # an AML term is read from the columns of the data terms under it
        for up in ups:
            for lab in out.get(data, []):
                if lab not in out.setdefault(up, []):
                    out[up].append(lab)
    return out


_static = {}


def build():
    """The fixed graph: {'nodes': {id: {...}}, 'edges': [(a, b, kind)]}. Cached."""
    if _static:
        return _static["g"]
    reg, in_data, cols = indicators.registry(), indicators.available_terms(), term_columns()
    inds = reg["indicators"]
    nodes, edges = {}, []

    def node(i, kind, label, x, y, w, h=24, title=""):
        nodes[i] = {"kind": kind, "label": label, "x": x, "y": y, "w": w, "h": h, "title": title}

    n_rows = len(inds) + 1                          # the indicators and the "other terms" node
    pitch = (Y1 - Y0) / n_rows
    ind_y = {}
    for k, ind in enumerate(inds):
        ind_y[ind["id"]] = Y0 + pitch * (k + 0.5)
        node(ind["id"], "indicator", ind["id"], 330, ind_y[ind["id"]] - 15, 140, 30, ind["text"])
    ind_y["other"] = Y0 + pitch * (len(inds) + 0.5)
    node("other", "indicator", "Other terms", 330, ind_y["other"] - 15, 140, 30,
         "Not an indicator: the account background and ids the queries also use")
    mid = (ind_y[inds[0]["id"]] + ind_y[inds[-1]["id"]]) / 2
    node("tactic", "typology", "Tactic", 6, mid - 15, 90, 30)
    node("technique", "typology", reg["technique"], 150, mid - 15, 120, 30)
    node("shacl", "shacl", "SHACL rules", 150, ind_y["IND02191"] - 15, 120, 30, "validation/shapes/t0039.shapes.ttl: checks the candidate loop built from the rows")
    edges.append(("technique", "tactic", "tactic"))

    needed = []                                     # data terms in the order the indicators first ask for them
    for ind in inds:
        for t in ind["needs"]:
            if t not in needed:
                needed.append(t)
    hidden = {d for t in needed for d in data_ontology.below(t)}      # a data term that stands behind a needed AML term is drawn as that AML term
    others = sorted(t for t in in_data if t.startswith("fcd:") and t not in needed and t not in hidden)
    term_order = needed + others
    t_pitch = (Y1 - Y0) / len(term_order)
    t_y = {}
    for k, t in enumerate(term_order):
        t_y[t] = Y0 + t_pitch * (k + 0.5)
        have = t in in_data
        node(t, "term", t, 520, t_y[t] - 8.5, 200, 17, "the data can speak about this" if have else "no data term under it: the data cannot speak about this")
    for ind in inds:
        edges.append(("technique", ind["id"], "indicates"))
        for t in ind["needs"]:
            edges.append((ind["id"], t, "needs"))
    for t in others:
        edges.append(("other", t, "needs"))
    for ind_id in SHACL_INDICATORS:
        edges.append((ind_id, "shacl", "shacl"))

    col_terms = {}
    for t in term_order:
        for c in cols.get(t, []):
            col_terms.setdefault(c, []).append(t)
    order = sorted(col_terms, key=lambda c: sum(t_y[t] for t in col_terms[c]) / len(col_terms[c]))
    c_pitch = (Y1 - Y0) / len(order)
    for k, c in enumerate(order):
        node("col:" + c, "column", c, 764, Y0 + c_pitch * (k + 0.5) - 8.5, 232, 17, "read through the R2RML mapping")
        for t in col_terms[c]:
            edges.append((t, "col:" + c, "maps"))
    _static["g"] = {"nodes": nodes, "edges": edges, "needs": {i["id"]: i["needs"] for i in inds}, "cols": cols, "in_data": set(in_data)}
    return _static["g"]


def terms_in(sparql):
    """The terms a SPARQL query uses, as 'fcd:x' / 'amd:y', plus the AML terms above the data terms it uses (a query in data terms answers them too)."""
    used = {f"{p}:{t}" for p, t in re.findall(r"\b(fcd|amd):(\w+)", sparql or "")}
    br = data_ontology.bridges()
    return used | {up for t in used for up in br.get(t, [])}


def lit(trace):
    """{'nodes': {id: state}, 'edges': {(a, b): state}} for this point of the chain (trace may be None or partial)."""
    g = build()
    nodes, edges = {}, {}
    trace = trace or {}
    ty = trace.get("typology")
    if ty and not ty.get("error"):
        nodes["tactic"] = nodes["technique"] = "read"
        edges[("technique", "tactic")] = "read"
        for ind, needs in g["needs"].items():
            nodes[ind] = "read"
            edges[("technique", ind)] = "read"
            for t in needs:
                nodes[t] = "present" if t in g["in_data"] else "missing"
                edges[(ind, t)] = "read"
    edge_set = {(a, b) for a, b, _ in g["edges"]}
    for role, r in (trace.get("roles") or {}).items():
        if not r.get("sparql") or r.get("guard"):
            continue
        serves = ["other" if x == "background" else x for x in r.get("serves", [])]    # the indicators (or the background) this query serves
        # the terms the query names, and (intent mode) the terms the Alignment made Ontop fetch, which the rows came back for
        fetched = set(r.get("used_terms", [])) | {up for t in r.get("used_terms", []) for up in data_ontology.bridges().get(t, [])}
        used = [t for t in sorted(terms_in(r["sparql"]) | fetched) if t in g["nodes"]]
        if "other" in serves:
            nodes["other"] = "used"
        for t in used:
            nodes[t] = "used"
            for who in serves:
                if (who, t) in edge_set:
                    edges[(who, t)] = "used"
        if r.get("rows") is not None and not r.get("error"):
            for t in used:
                for c in g["cols"].get(t, []):
                    nodes["col:" + c] = "used"
                    edges[(t, "col:" + c)] = "used"
    ans = trace.get("answer")
    if ans:
        for e in ans["indicators"]:
            nodes[e["id"]] = e["state"]
        nodes["shacl"] = "shacl"
        for ind in SHACL_INDICATORS:
            edges[(ind, "shacl")] = "shacl"
    return {"nodes": nodes, "edges": edges}


def changed(cur, prev):
    """What is new in cur compared with prev: {'nodes': set, 'edges': set}."""
    prev = prev or {"nodes": {}, "edges": {}}
    return {"nodes": {k for k, v in cur["nodes"].items() if prev["nodes"].get(k) != v},
            "edges": {k for k, v in cur["edges"].items() if prev["edges"].get(k) != v}}


CSS = """
:root{--fg:#1f2937;--off-f:#f3f4f6;--off-s:#d1d5db;--off-t:#9ca3af;--edge:#d1d5db;
 --read-f:#dbeafe;--read-s:#3b82f6;--present-f:#dcfce7;--present-s:#22c55e;--missing-f:#fee2e2;--missing-s:#ef4444;
 --used-f:#fef3c7;--used-s:#f59e0b;--held-f:#bbf7d0;--held-s:#16a34a;--not_held-f:#fecaca;--not_held-s:#dc2626;
 --facts_only-f:#e0e7ff;--facts_only-s:#6366f1;--cannot_check-f:#e5e7eb;--cannot_check-s:#6b7280;--shacl-f:#ede9fe;--shacl-s:#8b5cf6}
@media (prefers-color-scheme: dark){:root{--fg:#e5e7eb;--off-f:#262730;--off-s:#3d3f4a;--off-t:#6b7280;--edge:#3d3f4a;
 --read-f:#1e3a5f;--present-f:#14532d;--missing-f:#5b1d1d;--used-f:#5a4310;--held-f:#14532d;--not_held-f:#5b1d1d;
 --facts_only-f:#2e3070;--cannot_check-f:#3a3d46;--shacl-f:#3b2a6b}}
html,body{margin:0;height:100%;background:transparent;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
svg{width:100%;height:100%}
.hd{font-size:12px;fill:var(--off-t);text-transform:uppercase;letter-spacing:.04em}
.node rect{fill:var(--off-f);stroke:var(--off-s);stroke-width:1}
.node text{fill:var(--off-t);font-size:11.5px}.node .t1{font-weight:600;font-size:12.5px}.node .t2{font-size:10.5px}
.edge{fill:none;stroke:var(--edge);stroke-width:1}.edge.dash{stroke-dasharray:4 3}
.edge.on{stroke-width:1.8}
.arrow{fill:var(--edge)}
.lbl{font-size:10px;fill:var(--off-t)}
__STATES__
@keyframes pop{0%{filter:drop-shadow(0 0 0 transparent)}30%{filter:drop-shadow(0 0 12px var(--g))}100%{filter:drop-shadow(0 0 3px var(--g))}}
.node.on rect{filter:drop-shadow(0 0 3px var(--g))}
.node.new rect{animation:pop 1.5s ease-out}
.edge.new{animation:blink 1.5s ease-out}
@keyframes blink{0%{stroke-width:4}100%{stroke-width:1.8}}
"""


def _state_css():
    out = []
    for s in ("read", "present", "missing", "used", "held", "not_held", "facts_only", "cannot_check", "shacl"):
        dash = "stroke-dasharray:4 2;" if s == "missing" else ""
        out.append(f".node.s-{s}{{--g:var(--{s}-s)}}.node.s-{s} rect{{fill:var(--{s}-f);stroke:var(--{s}-s);stroke-width:{2 if s in ('used', 'held', 'not_held') else 1.4};{dash}}}"
                   f".node.s-{s} text{{fill:var(--fg)}}.edge.s-{s}{{stroke:var(--{s}-s)}}")
    return "\n".join(out)


def _path(a, b):
    x1, y1 = a["x"] + a["w"], a["y"] + a["h"] / 2
    x2, y2 = b["x"], b["y"] + b["h"] / 2
    dx = max(18, (x2 - x1) / 2)
    return f"M{x1:.0f},{y1:.0f} C{x1 + dx:.0f},{y1:.0f} {x2 - dx:.0f},{y2:.0f} {x2:.0f},{y2:.0f}"


def page_css():
    """The CSS scoped under .gv, so it can sit inside a Streamlit page without touching it."""
    css = CSS.replace("__STATES__", _state_css())
    for sel in (".node", ".edge", ".hd", ".lbl"):
        css = css.replace(sel, ".gv " + sel)
    css = css.replace(":root{", ".gv{").replace("html,body{", ".gv{").replace("svg{width:100%;height:100%}", ".gv svg{width:100%;height:auto;display:block}")
    return css


def render(cur, new=None, tactic=None, technique=None):
    """SVG page (HTML) for the lit state cur (from lit()); new = changed(cur, previous) makes the newly lit parts flash once."""
    g = build()
    nodes, new = g["nodes"], new or {"nodes": set(), "edges": set()}
    parts = [f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMinYMid meet" xmlns="http://www.w3.org/2000/svg">']
    for x, label in ((6, "Tactic"), (150, "Technique"), (330, "Indicators"), (520, "Data terms"), (764, "Database columns")):
        parts.append(f'<text class="hd" x="{x}" y="16">{label}</text>')
    parts.append('<text class="hd" x="520" y="29" style="font-size:9px;text-transform:none">dashed: indicator needs it (our draft reading)</text>')
    for a, b, kind in g["edges"]:
        st = cur["edges"].get((a, b))
        # an edge to a SHACL node leaves the indicator on its left side, the others leave on the right
        pa, pb = nodes[a], nodes[b]
        if kind == "shacl":
            p = f"M{pb['x'] + pb['w']:.0f},{pb['y'] + pb['h'] / 2:.0f} L{pa['x']:.0f},{pa['y'] + pa['h'] / 2:.0f}"
        else:
            p = _path(pa, pb)
        cls = ["edge"] + (["dash"] if kind in ("needs", "tactic") else []) + ([f"on s-{st}"] if st else []) + (["new"] if (a, b) in new["edges"] else [])
        parts.append(f'<path class="{" ".join(cls)}" d="{p}"/>')
    parts.append(f'<text class="lbl" x="98" y="{nodes["tactic"]["y"] + 9:.0f}">inferred</text>')
    for i, n in nodes.items():
        st = cur["nodes"].get(i)
        label, sub = n["label"], ""
        if i == "tactic":
            sub = tactic or ""
        elif i == "technique":
            sub = technique or ""
        elif n["kind"] == "indicator":
            sub = VERDICT_TEXT.get(st, "") if st in VERDICT_TEXT else ""
        if len(sub) > 24:
            sub = sub[:23] + "…"
        cls = ["node"] + ([f"on s-{st}"] if st else []) + (["new"] if i in new["nodes"] else [])
        parts.append(f'<g class="{" ".join(cls)}"><title>{html.escape(n["title"] or (label + " " + sub).strip())}</title>'
                     f'<rect x="{n["x"]}" y="{n["y"]:.1f}" width="{n["w"]}" height="{n["h"]}" rx="5"/>')
        cx, cy = n["x"] + 7, n["y"] + n["h"] / 2
        if n["kind"] in ("indicator", "typology", "shacl"):
            if sub:
                parts.append(f'<text class="t1" x="{cx}" y="{cy - 2:.1f}">{html.escape(label)}</text>'
                             f'<text class="t2" x="{cx}" y="{cy + 9:.1f}">{html.escape(sub)}</text>')
            else:
                parts.append(f'<text class="t1" x="{cx}" y="{cy + 4:.1f}">{html.escape(label)}</text>')
        else:
            parts.append(f'<text x="{cx}" y="{cy + 3.5:.1f}">{html.escape(label)}</text>')
        parts.append("</g>")
    parts.append("</svg>")
    return f'<style>{page_css()}</style><div class="gv">' + "".join(parts) + "</div>"


LEGEND = ("Grey = not involved in this run.  Blue = read by Ontop from AMLTRIX.  Gold = used by a query in this run (term) or read through "
          "the mapping (column).  Green / red dashed = a term an indicator needs that the data has / lacks.  Purple = SHACL rules.  "
          "Indicator colours at the end (green matches, red does not, indigo facts only, grey cannot check) come from the code in "
          "`indicators.py` running the SHACL result, not from Ontop.")



# An iframe made by components.html has a fixed height, and the drawing (an SVG that keeps its proportions) is only as tall as its width allows, so the
# difference showed as empty bands above and below it. This script, run inside the iframe, sets the iframe's own height, and that of the Streamlit box around it (which has the height the page gave it), to the drawing's height (and
# again when the width changes: on the resize event, a ResizeObserver, and a slow timer, because a browser may deliver none of the first two to an iframe). If the browser does not allow it, the iframe keeps the height the page gave it and the page still works.
AUTOFIT = ("<script>(function(){function fit(){try{var s=document.querySelector('svg');if(!s)return;var h=Math.ceil(s.getBoundingClientRect().height)+2;"
           "if(window.frameElement&&h>20){var f=window.frameElement;f.style.height=h+'px';if(f.parentElement){f.parentElement.style.setProperty('height',h+'px','important');f.parentElement.style.setProperty('min-height',h+'px','important');f.parentElement.style.setProperty('flex-basis',h+'px','important')}}}catch(e){}}fit();window.addEventListener('resize',fit);setTimeout(fit,60);if(window.ResizeObserver){new ResizeObserver(fit).observe(document.documentElement)}setInterval(fit,600);})();</script>")


def iframe_page(cur, new=None, tactic=None, technique=None):
    """render() as a standalone page for an iframe (st.html strips SVG). The drawing is as wide as the iframe and as tall as that makes it;
    AUTOFIT sets the iframe's height to match, so there is no empty band above or below it.
    The drawing is never larger than 1 unit = 1 pixel (max-height = the viewBox height): on a very wide window it stays that size and is centred."""
    return render(cur, new, tactic, technique) + f"<style>html,body{{margin:0}}.gv svg{{height:auto;max-height:{H}px;display:block}}</style>" + AUTOFIT   # never drawn bigger than its own units (a wide window must not blow it up)


LEGEND_LINE = ("⬜ not involved · 🟦 read by Ontop · 🟨 used in this run · 🟩 data has it / structure matches · "
               "🟥 data lacks it / does not match · 🟪 SHACL · 🔷 facts only · ⬛ cannot check")
