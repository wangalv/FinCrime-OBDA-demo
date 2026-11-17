"""Prompt for the model that writes SPARQL. PROMPT_VERSION is saved with every run.

p4 (build_plan): the model sees the vocabulary of the terms the plan uses (AML terms and data terms, read from the merged data ontology, see
src/data_ontology.py), the task and the output variables of each query (src/queryplan.py, derived from the Alignment), one worked example about a
different question, and the investigator's question. p1 (build) is the first trial: the vocabulary of ontology/alignment/source_vocabulary.ttl, one hand-set role per call.
It is NOT told the T0039 rules or the shape of the answer: judging the loop is SHACL's job, not the model's.
"""
import json
import sys
from pathlib import Path

from rdflib import Graph, Namespace, RDF, RDFS
from rdflib.namespace import OWL

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_ontology  # noqa: E402
import paths  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FCD = Namespace("https://example.org/fincrime-data#")
PROMPT_VERSION = "p1-2026-11-08"                 # one call per query role (src/try_model.py)
PROMPT_VERSION_PLAN = "p4-aml-terms-2026-11-09"  # one call returns the queries the Alignment asks for, in AML terms (src/demo_run.py); p3 used data terms, p2 had three hand-set roles

# p1 only (src/try_model.py and generated/trial_p1-*.json, kept as the record of the first trial). The page no longer uses it:
# its queries come from src/queryplan.py.
ROLES = {
    "legs": {"vars": ["txid", "ts", "from", "to", "amountLog"],
             "task": "Return one row for each transaction the investigator names: its id, time, paying account, receiving account and amountLog."},
    "legs_bank": {"vars": ["txid", "ts", "from", "to", "amountLog", "sameBank"],
                  "task": "Return one row for each transaction the investigator names: its id, time, paying account, receiving account, "
                          "amountLog, and whether the two accounts are at the same bank."},
    "context": {"vars": ["account", "customerType", "industry", "tenure", "pep", "risk"],
                "task": "Return one row for each distinct account that pays or receives in the named transactions: its customer type, "
                        "industry (absent for individuals, so the industry must be OPTIONAL), days since opening, PEP flag and risk rating."},
}

EXAMPLE = '''Example (a different question, only to show the format).
Question: "Which account received transaction 5?"
Answer: {"sparql": "PREFIX fcd: <https://example.org/fincrime-data#>\\nSELECT ?txid ?to WHERE {\\n  VALUES ?txid { 5 }\\n  ?tx a fcd:Transaction ; fcd:txId ?txid ; fcd:toAccount ?to .\\n}"}'''


def vocabulary():
    g = Graph().parse(paths.SOURCE_VOCABULARY)
    lines = []
    for kind, label in ((OWL.Class, "class"), (OWL.ObjectProperty, "property (links to an Account)"), (OWL.DatatypeProperty, "property (a value)")):
        for s in sorted(g.subjects(RDF.type, kind)):
            if not str(s).startswith(str(FCD)):
                continue
            dom, rng = g.value(s, RDFS.domain), g.value(s, RDFS.range)
            d = f" of {dom.split('#')[1]}" if dom is not None else ""
            r = f", range {rng.split('#')[1]}" if rng is not None else ""
            lines.append(f"fcd:{str(s).split('#')[1]}  [{label}{d}{r}] {g.value(s, RDFS.comment) or ''}")
    return "\n".join(lines)


def terms():
    """Set of fcd: IRIs the model may use."""
    g = Graph().parse(paths.SOURCE_VOCABULARY)
    return {str(s) for s in g.subjects(RDF.type, None) if str(s).startswith(str(FCD))}


def build(question, role):
    spec = ROLES[role]
    system = ("You translate an investigator's question about bank transactions into one SPARQL SELECT query over a small vocabulary. "
              "Use only the terms listed. Do not write SQL. Answer with a JSON object {\"sparql\": \"...\"} and nothing else.")
    user = (f"Prefix: PREFIX fcd: <https://example.org/fincrime-data#>\n\nVocabulary:\n{vocabulary()}\n\n"
            f"Task: {spec['task']}\nThe query must return exactly these variables, with these names: "
            + ", ".join("?" + v for v in spec["vars"]) + ".\n\n" + EXAMPLE + f"\n\nQuestion: \"{question}\"\nAnswer:")
    return system, user


PREFIX_LINES = "PREFIX amd: <https://example.org/aml-data#>\\nPREFIX fcd: <https://example.org/fincrime-data#>\\n"
EXAMPLE_PARTS = {      # a different question, only to show the format: one entry per query key
    "transaction": ('Question: "Who received transfer 5?"\n', "transaction",
                    PREFIX_LINES + "SELECT ?txid ?to WHERE {\\n  VALUES ?txid { 5 }\\n"
                    "  ?tx a amd:FundsTransfer ; amd:transferId ?txid ; amd:beneficiary ?to .\\n}"),
    "account": ("", "account",
                PREFIX_LINES + "SELECT DISTINCT ?account ?customerType WHERE {\\n  VALUES ?txid { 5 }\\n"
                "  ?tx a amd:FundsTransfer ; amd:transferId ?txid ; amd:beneficiary ?account .\\n  ?account fcd:customerType ?customerType .\\n}"),
}


def terms_vocabulary(terms):
    """The vocabulary lines for the given terms ('amd:x' / 'fcd:y'), read from the merged data ontology: kind, domain, range, comment."""
    g = data_ontology.graph()
    lines = []
    for t in sorted(terms):
        s = data_ontology.full(t)
        kind = ("class" if (s, RDF.type, OWL.Class) in g else "property (links to an Account)" if (s, RDF.type, OWL.ObjectProperty) in g
                else "property (a value)")
        dom, rng = g.value(s, RDFS.domain), g.value(s, RDFS.range)
        d = f" of {data_ontology.short(dom)}" if dom is not None else ""
        r = f", range {data_ontology.short(rng).replace('http://www.w3.org/2001/XMLSchema#', 'xsd:')}" if rng is not None and kind != "class" else ""
        lines.append(f"{t}  [{kind}{d}{r}] {g.value(s, RDFS.comment) or ''}")
    return "\n".join(lines)


def all_terms():
    """Every IRI a query may use (the data terms and the AML terms): what the query checks allow."""
    return data_ontology.all_terms()


def build_plan(question, specs):
    """One prompt for the queries a technique needs (src/queryplan.py): the model answers with {"<key>": "<SPARQL>", ...}.
    The task and the variables of each query come from the Alignment and the data ontology, not from this file."""
    keys = [s["key"] for s in specs]
    system = (f"You translate an investigator's question about bank transactions into {len(specs)} SPARQL SELECT queries over a small vocabulary. "
              "Use only the terms listed. Do not write SQL. Answer with one JSON object whose keys are "
              + ", ".join(keys) + " and whose values are the SPARQL queries as strings, and nothing else.")
    tasks = "\n".join(f"- {s['key']}: {s['task']}" for s in specs)
    shown = [EXAMPLE_PARTS[k] for k in keys if k in EXAMPLE_PARTS]
    example = ""
    if shown:
        example = ("Example (a different question, only to show the format).\n" + shown[0][0]
                   + "Answer: {" + ", ".join(f'"{k}": "{q}"' for _, k, q in shown) + "}\n\n")
    user = (f"Prefixes: PREFIX amd: <https://example.org/aml-data#> and PREFIX fcd: <https://example.org/fincrime-data#>\n\nVocabulary:\n{terms_vocabulary({t for sp in specs for t in sp['vocab']})}\n\nThe queries:\n{tasks}\n\n"
            + example + f"Question: \"{question}\"\nAnswer:")
    return system, user


def extract_plan(text, specs):
    """The model's reply -> {key: SPARQL string or None}. A query may be given as a string or as {"sparql": "..."}."""
    try:
        v = json.loads(text)
    except json.JSONDecodeError:
        v = None
    out = {}
    for s in specs:
        q = v.get(s["key"]) if isinstance(v, dict) else None
        if isinstance(q, dict):
            q = q.get("sparql")
        out[s["key"]] = q if isinstance(q, str) and q.strip() else None
    return out


def extract_sparql(text):
    """The model's reply -> SPARQL string, or None if it is not the expected JSON."""
    try:
        v = json.loads(text)
    except json.JSONDecodeError:
        return None
    s = v.get("sparql") if isinstance(v, dict) else None
    return s if isinstance(s, str) and s.strip() else None


# ---- p5: the intent-level queries (mode 'intent' of src/demo_run.py). The model names only the technique and the transfer ids; the data to fetch is
# decided by the Alignment (align:needsTerm / align:backgroundTerm), which Ontop joins with the data in the unified graph (src/unified.py).
PROMPT_VERSION_INTENT = "p5-intent-2026-11-10"
INTENT_PREFIXES = ("PREFIX amlo: <https://example.org/amlo#>\nPREFIX skos: <http://www.w3.org/2004/02/skos/core#>\n"
                   "PREFIX align: <https://example.org/align#>\nPREFIX amx: <https://example.org/amltrix/>\nPREFIX amd: <https://example.org/aml-data#>\n")
INTENT_VOCABULARY = """amx:<technique id>  a technique of the AML typology, for example amx:T0039
amlo:isIndicatedBy  [property] links a technique to its indicators
skos:prefLabel  [property] the label (the identifier) of an indicator
align:needsTerm  [property] links an indicator to a term of the data it needs; the term can be used as the predicate of a transfer
align:backgroundTerm  [property] links a technique to a term of the account background to show the investigator; the term can be used as the predicate of an account
amd:FundsTransfer  [class] a transfer of funds from one account to another
amd:transferId  [property (a value) of amd:FundsTransfer] identifier of the transfer
amd:originator  [property (links to an account) of amd:FundsTransfer] the account the funds leave
amd:beneficiary  [property (links to an account) of amd:FundsTransfer] the account the funds arrive at"""
INTENT_TASKS = {
    "evidence": "Return, for the technique, the data that each of its indicators needs about the transfers the investigator names: one row for each "
                "indicator, transfer, term and value, with these variables: ?ind (the indicator), ?txid (amd:transferId), ?term (what the indicator needs, "
                "bound by align:needsTerm), ?v (the value of that term for the transfer). Use ?term as the predicate of the transfer. Do not name any "
                "other data term yourself.",
    "background": "Return, for the technique, the account background to show: one row for each account that is the originator or the beneficiary of a "
                  "named transfer, term and value, with these variables: ?account, ?term (bound by align:backgroundTerm), ?v (its value for the account). "
                  "Use ?term as the predicate of the account. Do not name any other data term yourself.",
}
_EV = ("SELECT DISTINCT ?ind ?txid ?term ?v WHERE {\\n  amx:T0001 amlo:isIndicatedBy ?i .\\n  ?i skos:prefLabel ?ind ; align:needsTerm ?term .\\n"
       "  VALUES ?txid { 1111111 2222222 }\\n  ?tx a amd:FundsTransfer ; amd:transferId ?txid ; ?term ?v .\\n}")
_BG = ("SELECT DISTINCT ?account ?term ?v WHERE {\\n  amx:T0001 align:backgroundTerm ?term .\\n  VALUES ?txid { 1111111 2222222 }\\n"
       "  ?tx a amd:FundsTransfer ; amd:transferId ?txid .\\n  { ?tx amd:originator ?account } UNION { ?tx amd:beneficiary ?account }\\n"
       "  ?account ?term ?v .\\n}")
_PFX_ESCAPED = INTENT_PREFIXES.replace("\n", "\\n")
INTENT_EXAMPLE = ("Example (a different technique and different ids, only to show the format).\n"
                  'Technique: T0001. Question: "Look at transfers 1111111 and 2222222."\n'
                  'Answer: {"evidence": "' + _PFX_ESCAPED + _EV + '", "background": "' + _PFX_ESCAPED + _BG + '"}')
INTENT_KEYS = [{"key": "evidence"}, {"key": "background"}]


def build_intent(question, technique):
    """One prompt for the two intent-level queries. technique is the id the intent analysis found and the code checked (for example 'T0039')."""
    system = ("You translate an investigator's request about bank transfers into two SPARQL SELECT queries over a small vocabulary. You name only the "
              "technique and the transfer ids. The data to fetch is decided elsewhere: you ask for it through align:needsTerm and align:backgroundTerm. "
              "Use only the terms listed. Do not write SQL. Answer with one JSON object whose keys are evidence and background and whose values are the "
              "SPARQL queries as strings, and nothing else.")
    tasks = "\n".join(f"- {k}: {t}" for k, t in INTENT_TASKS.items())
    user = (f"Prefixes:\n{INTENT_PREFIXES}\nVocabulary:\n{INTENT_VOCABULARY}\n\nThe queries:\n{tasks}\n\n{INTENT_EXAMPLE}\n\n"
            f"Technique: {technique}. Question: \"{question}\"\nAnswer:")
    return system, user


def extract_intent(text):
    """The model's reply -> {'evidence': SPARQL or None, 'background': SPARQL or None}."""
    return extract_plan(text, INTENT_KEYS)
