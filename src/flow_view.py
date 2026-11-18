"""The chain from the investigator's question to the answer, as a short flow diagram whose boxes light up while a question runs.

Boxes, left to right:   Question -> SPARQL -> Ontop -> SQL -> SHACL -> Result
(The intent analysis, where the model matches the question to a technique of the AML typology, is part of the SPARQL box: same model, same step.)
Under them a row of the six layers of the semantic architecture (L1 external knowledge ... L6 validation), all in grey (a colour of their own would be mistaken for the status colours of the steps), joined to the
step that reads it. A layer is outlined and filled darker in the run that reads it. Layers 2 to 5 are the semantic and data-access foundation.
The demo's finer steps (ids, the SPARQL checks, the rows, the candidate loop) are folded into the six boxes.

What the diagram says, and does not say:
  - Ontop runs twice in a question: once early, to read the AML typology (AMLO + AMLTRIX, see typology.py), and once to turn the model's
    SPARQL into SQL. The SQL run reads the R2RML mapping, the lens and the data ontology with the AML terms and the bridge (src/ontop_run.py
    is given the merged data ontology as -t, so a query in AML terms is rewritten to the data terms), but not AMLO: the AML framework ontology
    does not shape the SQL. The Ontop box therefore lights twice, and each layer lights only in the run that reads it.
  - The AML terms (L2) are also what the model writes against (prompt vocabulary) and what the SPARQL checks use; the requirements (L3) decide what the plan asks for.
Below them, when the "Without OBDA" switch is on, a second lane: Question -> LLM -> Answer, the comparison where the model is given only the table
rows (src/baseline.py). It is separate from the chain above: it lights only while that one call runs. lane = None (no lane), 'waiting', 'active',
'done' or 'fail'.
States of a box: idle (grey), active (the step the chain is at; gold, pulses), done (green), fail (red). A layer box stays grey; when read it is outlined in the text colour and filled darker.
It is derived from the trace (what exists so far) and the stage of the current event (demo_run.ev(stage=...)), so it moves with the graph
in graph_view.py, which is drawn from the same trace at the same step.
"""
import html

W, H = 1000, 172
LANE_H = 84                                          # extra height of the "Without OBDA" lane
LANE_NODES = [("lq", "Question", "same question"), ("lm", "LLM", "reads the table rows"), ("la", "Answer", "yes / no, no checks")]
BOX_W, BOX_H, GAP, Y = 140, 44, 24, 12

# id, label, sub label
NODES = [
    ("question", "Question", "natural language"),
    ("sparql", "SPARQL", "model"),
    ("ontop", "Ontop", "reads ontology + mapping"),
    ("sql", "SQL", "run on DuckDB"),
    ("shacl", "SHACL", "checks the candidate loop"),
    ("result", "Result", "verdicts + summary"),
]
ORDER = [n[0] for n in NODES]
TAIL = ("shacl", "result")                          # strictly one after the other; the earlier steps repeat for each of the three queries
# which box of the diagram each stage of demo_run belongs to
STAGE_NODE = {"intent": "sparql", "ids": "question", "typology": "ontop", "sparql": "sparql", "guard": "sparql", "ontop": "ontop", "db": "sql",
              "candidate": "shacl", "shacl": "shacl", "answer": "result"}
FAIL_AT = {"no_ids": "question", "clarify": "sparql", "choose": "sparql", "unsupported": "sparql", "intent_rejected": "sparql", "intent_error": "sparql", "model_error": "sparql", "rejected_by_guard": "sparql", "ontop_error": "ontop", "rejected_later": "shacl"}
SUB = {"sparql": {"model": "LLM", "intent": "LLM, intent only", "gold": "gold, no model"}}
# The six layers (see the architecture figure): id, tag, title, what it holds here, colour, the boxes that read it. A layer is read by a box in the
# run that needs it: L1 and L3 when Ontop reads the AML typology and the requirements (in the intent mode also in the SQL run: one graph), L2
# by the model's vocabulary and by the SQL run, L4 and L5 by the SQL run, L6 by SHACL.
GREY = "#8b919c"        # every layer is grey: the status colours (gold active, green done, red failed) belong to the steps only
LAYERS = [
    ("l1", "L1", "External knowledge", "AMLO + AMLTRIX", GREY, ("ontop",)),
    ("l2", "L2", "AML core ontology", "AML terms (amd:)", GREY, ("sparql", "ontop")),
    ("l3", "L3", "Requirements", "needsTerm (Alignment)", GREY, ("sparql", "ontop")),
    ("l4", "L4", "Data semantics", "bridge + source terms", GREY, ("ontop",)),
    ("l5", "L5", "OBDA mapping", "R2RML + lens", GREY, ("ontop",)),
    ("l6", "L6", "Validation", "SHACL + indicator registry", GREY, ("shacl",)),
]
LAYER_W, LAYER_H, LAYER_Y = 150, 38, 106


def layer_x(i):
    return 8 + i * (W - 16 - LAYER_W) / (len(LAYERS) - 1)


def pos(i):
    return 8 + i * (BOX_W + GAP)


def main_query(trace):
    """The query that serves an indicator (the one the chain cannot go on without), or {} before the plan exists."""
    return next((r for r in ((trace or {}).get("roles") or {}).values() if r.get("required")), {})


def done_steps(trace):
    """Boxes the chain has completed so far, from what the trace holds."""
    t = trace or {}
    legs = main_query(t)
    d = set()
    if trace is not None:
        d.add("question")
    if legs.get("sparql") and not legs.get("guard"):
        d.add("sparql")
    if t.get("typology") is not None or (legs.get("sql") is not None and not legs.get("error")):
        d.add("ontop")
    if legs.get("sql") is not None and not legs.get("error"):
        d.add("sql")
    if t.get("answer"):
        d.add("shacl")
    if t.get("summary"):
        d.add("result")
    return d


def states(trace, stage):
    """{box id: 'done' | 'active' | 'fail'} for this point of the chain. stage = the step of demo_run the current event belongs to."""
    d = done_steps(trace)
    node = STAGE_NODE.get(stage)
    if node in TAIL:                                    # the tail boxes after the current one have not happened yet at this event
        d -= {s for s in TAIL if ORDER.index(s) > ORDER.index(node)}
    out = {s: "done" for s in d}
    failed = FAIL_AT.get((trace or {}).get("status"))
    if failed:
        out[failed] = "fail"
    elif node and not (node == "result" and "result" in d):
        out[node] = "active"
    return out


def height(mode=None, lane=None):
    """The height of the diagram (the same for every mode: the six layers are always drawn; the Without OBDA lane adds to it)."""
    return round(130 * (H + (LANE_H if lane else 0)) / H)         # the height before the page knows the width (AUTOFIT then sets the real one)


def lane_states(lane):
    """{lane box id: state} for the Without OBDA lane."""
    return {"waiting": {}, "active": {"lq": "done", "lm": "active"}, "done": {"lq": "done", "lm": "done", "la": "done"},
            "fail": {"lq": "done", "lm": "fail"}}.get(lane, {})


def input_states(trace, stage, st, mode=None):
    """Which layers are lit: {'l1': 'on' | '', ...}. Each lights in the run that reads it (see LAYERS)."""
    t = trace or {}
    legs = main_query(t)
    sql_run = stage == "ontop" or legs.get("sql") is not None
    typology = t.get("typology") is not None or stage == "typology"
    uses_model = mode in ("model", "intent")
    on = {"l1": typology or (mode == "intent" and sql_run),
          "l2": sql_run or (uses_model and st.get("sparql") in ("done", "active")),
          "l3": typology or (mode == "intent" and sql_run) or st.get("sparql") in ("done", "active"),
          "l4": sql_run,
          "l5": sql_run,
          "l6": st.get("shacl") in ("done", "active")}
    return {k: ("on" if v else "") for k, v in on.items()}


def changed(cur, prev):
    prev = prev or {}
    return {k for k, v in cur.items() if prev.get(k) != v}


CSS = """
.fl{--fg:#1f2937;--off-f:#f3f4f6;--off-s:#d1d5db;--off-t:#9ca3af;--done-f:#dcfce7;--done-s:#16a34a;--active-f:#fef3c7;--active-s:#f59e0b;
 --fail-f:#fee2e2;--fail-s:#dc2626;--on-f:#dbeafe;--on-s:#3b82f6;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
@media (prefers-color-scheme: dark){.fl{--fg:#e5e7eb;--off-f:#262730;--off-s:#3d3f4a;--off-t:#6b7280;--done-f:#14532d;--active-f:#5a4310;--fail-f:#5b1d1d;--on-f:#1e3a5f}}
.fl svg{width:100%;height:100%}
.fl .b rect{fill:var(--off-f);stroke:var(--off-s);stroke-width:1}
.fl .b text{fill:var(--off-t);font-size:12px}.fl .b .t1{font-weight:600;font-size:14px}.fl .b .t2{font-size:10.5px}
.fl .a{fill:none;stroke:var(--off-s);stroke-width:1.3}.fl .ah{fill:var(--off-s)}
.fl .c{fill:none;stroke:var(--off-s);stroke-width:1;stroke-dasharray:3 2}
.fl .b.done rect{fill:var(--done-f);stroke:var(--done-s);stroke-width:1.6}.fl .b.done text{fill:var(--fg)}
.fl .b.active rect{fill:var(--active-f);stroke:var(--active-s);stroke-width:2.2}.fl .b.active text{fill:var(--fg)}
.fl .b.fail rect{fill:var(--fail-f);stroke:var(--fail-s);stroke-width:2}.fl .b.fail text{fill:var(--fg)}
.fl .a.done{stroke:var(--done-s);stroke-width:1.9}.fl .ah.done{fill:var(--done-s)}
.fl .c.on{stroke-width:1.5;stroke-dasharray:none}
.fl .ly rect{fill:var(--off-f);stroke:var(--lc);stroke-opacity:.45;stroke-width:1.2}
.fl .ly .tg{fill:var(--off-t);font-weight:700;font-size:11px}.fl .ly .tt{fill:var(--off-t);font-weight:600;font-size:11.5px}.fl .ly .ts{fill:var(--off-t);font-size:10px}
.fl .ly.on rect{fill:var(--lc);fill-opacity:.3;stroke:var(--fg);stroke-opacity:.85;stroke-width:1.8}
.fl .ly.on .tt,.fl .ly.on .ts,.fl .ly.on .tg{fill:var(--fg)}
.fl .ly.new rect{animation:pop 1.5s ease-out}
.fl .sep{stroke:var(--off-s);stroke-width:1;stroke-dasharray:4 3}.fl .lanet{fill:#c2410c;font-size:11px;font-weight:700}.fl .lanes{fill:var(--off-t);font-size:10.5px}
.fl .sem{stroke:#2e7d5b;stroke-width:1.5;fill:none}.fl .semt{fill:#2e7d5b;font-size:10.5px;font-weight:600}
.fl .b.done rect{--g:var(--done-s)}.fl .b.active rect{--g:var(--active-s)}.fl .b.fail rect{--g:var(--fail-s)}.fl .ly.on rect{--g:var(--lc)}
.fl .b.done rect,.fl .b.active rect,.fl .b.fail rect{filter:drop-shadow(0 0 3px var(--g))}
@keyframes pulse{0%{filter:drop-shadow(0 0 2px var(--g))}50%{filter:drop-shadow(0 0 13px var(--g))}100%{filter:drop-shadow(0 0 2px var(--g))}}
@keyframes pop{0%{filter:drop-shadow(0 0 0 transparent)}30%{filter:drop-shadow(0 0 13px var(--g))}100%{filter:drop-shadow(0 0 3px var(--g))}}
.fl .b.active rect{animation:pulse 1.2s ease-in-out infinite}
.fl .b.new:not(.active) rect{animation:pop 1.5s ease-out}
"""


def render(trace, stage, new=None, mode=None, lane=None):
    """The flow diagram (HTML with SVG) for this point of the chain. new = boxes that changed since the last drawing (they flash once)."""
    st = states(trace, stage)
    inp = input_states(trace, stage, st, mode)
    new = new or set()
    hh = H + (LANE_H if lane else 0)
    parts = [f'<style>{CSS}</style><div class="fl"><svg viewBox="0 0 {W} {hh}" preserveAspectRatio="xMinYMid meet" xmlns="http://www.w3.org/2000/svg">']
    for i in range(len(NODES) - 1):
        a, b = NODES[i][0], NODES[i + 1][0]
        cls = "done" if st.get(a) == "done" and st.get(b) in ("done", "active") else ""
        x1, x2, y = pos(i) + BOX_W, pos(i + 1), Y + BOX_H / 2
        parts.append(f'<line class="a {cls}" x1="{x1}" y1="{y}" x2="{x2 - 5}" y2="{y}"/>'
                     f'<path class="ah {cls}" d="M{x2},{y} L{x2 - 7},{y - 4.5} L{x2 - 7},{y + 4.5} Z"/>')
    rails = []
    for j, (lid, tag, title, what, color, owners) in enumerate(LAYERS):       # the six layers, with a rail up to each box that reads it
        on = inp[lid]
        x = layer_x(j)
        cx = x + LAYER_W / 2
        for owner in owners:
            ox = pos(ORDER.index(owner)) + BOX_W / 2 + (j - 2) * 9
            ox = max(pos(ORDER.index(owner)) + 10, min(pos(ORDER.index(owner)) + BOX_W - 10, ox))
            yh = 70 + j * 5
            rails.append(f'<path class="c {on}" style="--lc:{color};{"stroke:" + color if on else ""}" d="M{cx},{LAYER_Y} L{cx},{yh} L{ox},{yh} L{ox},{Y + BOX_H + 1}"/>')
        flash = "new" if on and set(owners) & new else ""
        parts.append(f'<g class="ly {on} {flash}" style="--lc:{color}"><title>{html.escape(tag + " " + title + " · " + what)}</title>'
                     f'<rect x="{x}" y="{LAYER_Y}" width="{LAYER_W}" height="{LAYER_H}" rx="6"/>'
                     f'<text class="tg" x="{x + 8}" y="{LAYER_Y + 15}">{tag}</text><text class="tt" x="{x + 28}" y="{LAYER_Y + 15}">{html.escape(title)}</text>'
                     f'<text class="ts" x="{x + 8}" y="{LAYER_Y + 30}">{html.escape(what)}</text></g>')
    parts[1:1] = rails                                                           # rails behind the boxes
    x0, x1, yb = layer_x(1), layer_x(4) + LAYER_W, LAYER_Y + LAYER_H + 8
    parts.append(f'<path class="sem" d="M{x0},{yb - 4} L{x0},{yb} L{x1},{yb} L{x1},{yb - 4}"/>'
                 f'<text class="semt" x="{(x0 + x1) / 2}" y="{yb + 13}" text-anchor="middle">semantic and data-access layers (L2 to L5)</text>')
    for i, (sid, label, sub) in enumerate(NODES):
        if sid == "sparql" and mode:
            sub = SUB["sparql"].get(mode, sub)
        cls = " ".join(["b", st.get(sid, ""), "new" if sid in new else ""])
        x = pos(i)
        parts.append(f'<g class="{cls}"><title>{html.escape(label + " · " + sub)}</title><rect x="{x}" y="{Y}" width="{BOX_W}" height="{BOX_H}" rx="6"/>'
                     f'<text class="t1" x="{x + 10}" y="{Y + 20}">{html.escape(label)}</text><text class="t2" x="{x + 10}" y="{Y + 36}">{html.escape(sub)}</text></g>')
    if lane:
        ls = lane_states(lane)
        y0 = H + 14
        parts.append(f'<line class="sep" x1="8" y1="{y0 - 8}" x2="{W - 8}" y2="{y0 - 8}"/>'
                     f'<text class="lanet" x="8" y="{y0 + 8}">WITHOUT OBDA</text>'
                     f'<text class="lanes" x="112" y="{y0 + 8}">The LLM is given the table rows and decides on its own: no ontology, mapping, typology text or SHACL</text>')
        for i, (nid, label, sub) in enumerate(LANE_NODES):
            x, y = pos(i), y0 + 16
            if i:
                a, b = LANE_NODES[i - 1][0], nid
                cls = "done" if ls.get(a) == "done" and ls.get(b) in ("done", "active") else ""
                parts.append(f'<line class="a {cls}" x1="{pos(i - 1) + BOX_W}" y1="{y + 19}" x2="{x - 5}" y2="{y + 19}"/>'
                             f'<path class="ah {cls}" d="M{x},{y + 19} L{x - 7},{y + 14.5} L{x - 7},{y + 23.5} Z"/>')
            parts.append(f'<g class="b {ls.get(nid, "")}"><title>{html.escape("Without OBDA · " + label + " · " + sub)}</title>'
                         f'<rect x="{x}" y="{y}" width="{BOX_W}" height="38" rx="6"/>'
                         f'<text class="t1" x="{x + 10}" y="{y + 17}">{html.escape(label)}</text><text class="t2" x="{x + 10}" y="{y + 31}">{html.escape(sub)}</text></g>')
    parts.append("</svg></div>")
    return "".join(parts)



# An iframe made by components.html has a fixed height, and the drawing (an SVG that keeps its proportions) is only as tall as its width allows, so the
# difference showed as empty bands above and below it. This script, run inside the iframe, sets the iframe's own height, and that of the Streamlit box around it (which has the height the page gave it), to the drawing's height (and
# again when the width changes: on the resize event, a ResizeObserver, and a slow timer, because a browser may deliver none of the first two to an iframe). If the browser does not allow it, the iframe keeps the height the page gave it and the page still works.
AUTOFIT = ("<script>(function(){function fit(){try{var s=document.querySelector('svg');if(!s)return;var h=Math.ceil(s.getBoundingClientRect().height)+2;"
           "if(window.frameElement&&h>20){var f=window.frameElement;f.style.height=h+'px';if(f.parentElement){f.parentElement.style.setProperty('height',h+'px','important');f.parentElement.style.setProperty('min-height',h+'px','important');f.parentElement.style.setProperty('flex-basis',h+'px','important')}}}catch(e){}}fit();window.addEventListener('resize',fit);setTimeout(fit,60);if(window.ResizeObserver){new ResizeObserver(fit).observe(document.documentElement)}setInterval(fit,600);})();</script>")


def iframe_page(trace, stage, new=None, mode=None, lane=None):
    """The diagram as a page for an iframe. As wide as the iframe and as tall as that makes it, but never larger than 1 unit = 1 pixel (a wide window
    must not blow it up); AUTOFIT sets the iframe's height to match."""
    return render(trace, stage, new, mode, lane) + f"<style>html,body{{margin:0}}.fl svg{{height:auto;max-height:{H + (LANE_H if lane else 0)}px;display:block}}</style>" + AUTOFIT


LEGEND_INTENT = ("⬜ not reached · 🟨 the step the chain is at · 🟩 done · 🟥 failed · a darker, outlined layer is one that step reads.  Intent mode: the model sees only the "
                 "intent vocabulary (L2 terms and the L3 requirements); Ontop runs over one graph (L1, L3 and the data), so the SQL run reads L1 to L5, and L3 decides what to fetch.")
LEGEND_LINE = ("⬜ not reached · 🟨 the step the chain is at · 🟩 done · 🟥 failed · a darker, outlined layer is one that step reads.  "
               "Ontop runs twice: early, to read the AML typology (L1) and the requirements (L3); then to write the SQL from the AML terms (L2), the bridge (L4) and the mapping (L5).")
