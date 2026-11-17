"""Checks on a SPARQL query written by the model, before it goes to Ontop.

check(sparql, required_vars, question_ids=None) -> list of (check_name, message). Empty list = nothing found.
Checks:
  syntax          the query does not parse
  query_form      not a plain SELECT (CONSTRUCT, ASK, DESCRIBE, updates are refused)
  unknown_term    an IRI that is not a term of the data ontology (fcd:) or of the AML terms (amd:), or an IRI from another namespace.
                  Why: Ontop answers an unknown term with an EMPTY result, not an error, so without this check a typo looks like
                  "no such transactions".
  missing_output  the query does not project every variable in required_vars (the pipeline reads them by name)
  ids_differ      only when question_ids is given: the integers in VALUES / FILTER are not exactly the ids in the question
  allowed_iris    when given, REPLACES the vocabulary above: only these IRIs may appear (used for the intent-level queries)
  must_use        IRIs the query has to contain (missing_term)
What it does not check: whether the query means what the investigator asked (joins, filters). That is measured against the gold.
"""
import re

from rdflib.namespace import RDF
from rdflib.plugins.sparql import parser
from rdflib.plugins.sparql.algebra import translateQuery

import prompt

ALLOWED_OTHER = {str(RDF.type)}
XSD_NS = "http://www.w3.org/2001/XMLSchema#"   # datatype IRIs of literals such as the integers in VALUES


def check(sparql, required_vars, question_ids=None, allowed_iris=None, must_use=None):
    problems = []
    try:
        parsed = parser.parseQuery(sparql)
        algebra = translateQuery(parsed)
    except Exception as e:  # rdflib raises several exception types for bad queries
        return [("syntax", f"the query does not parse: {str(e)[:160]}")]
    form = algebra.algebra.name
    if form not in ("SelectQuery",):
        problems.append(("query_form", f"only SELECT queries are allowed, got {form}"))
        return problems
    allowed = prompt.all_terms() if allowed_iris is None else set(allowed_iris)
    iris = set(re.findall(r"URIRef\('([^']+)'\)", repr(algebra.algebra)))
    for iri in sorted(iris):
        if iri not in allowed and iri not in ALLOWED_OTHER and not iri.startswith(XSD_NS):
            problems.append(("unknown_term", f"{iri} is not a term of the vocabulary"))
    for iri in sorted(must_use or []):
        if iri not in iris:
            problems.append(("missing_term", f"the query must use {iri}"))
    projected = {str(v) for v in algebra.algebra.get("PV", [])}
    missing = [v for v in required_vars if v not in projected]
    if missing:
        problems.append(("missing_output", f"the query does not return {missing}; it returns {sorted(projected)}"))
    if question_ids is not None:
        in_query = {int(n) for n in re.findall(r"(?<![\w.])\d{4,}(?!\w|\.\d)", re.sub(r"<[^>]*>", "", sparql))}
        if in_query != set(question_ids):
            problems.append(("ids_differ", f"ids in the query {sorted(in_query)} differ from ids in the question {sorted(question_ids)}"))
    return problems


AMLO = "https://example.org/amlo#"
ALIGN = "https://example.org/align#"
AMX = "https://example.org/amltrix/"
SKOS = "http://www.w3.org/2004/02/skos/core#"
AMD = "https://example.org/aml-data#"
INTENT_VARS = {"evidence": ["ind", "txid", "term", "v"], "background": ["account", "term", "v"]}


def check_intent(sparql, kind, technique, question_ids):
    """The checks for an intent-level query (kind = 'evidence' or 'background'): it may name only the technique, the transfer ids and the
    structure terms. The data to fetch is decided by the Alignment through align:needsTerm / align:backgroundTerm, so a query that names a data
    term itself (amd:sameInstitution, fcd:fromAccount, ...) is refused, and so is one that does not ask the Alignment."""
    structure = {AMD + "FundsTransfer", AMD + "transferId"}
    if kind == "background":
        structure |= {AMD + "originator", AMD + "beneficiary"}        # how the accounts are reached from the transfers
    asks = ALIGN + ("needsTerm" if kind == "evidence" else "backgroundTerm")
    allowed = structure | {str(RDF.type), asks, AMX + technique}
    if kind == "evidence":
        allowed |= {AMLO + "isIndicatedBy", SKOS + "prefLabel"}
    return check(sparql, INTENT_VARS[kind], question_ids, allowed_iris=allowed, must_use=[asks, AMX + technique])
