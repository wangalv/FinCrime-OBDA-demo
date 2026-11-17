"""Long rows from the unified graph -> the rows the rest of the chain reads.

The intent-level queries return one row for each (indicator, transfer, term, value): the term is a predicate IRI Ontop bound from the Alignment, for
example amd:originator. The chain after Ontop (pipeline.parse_legs / parse_context, the candidate loop, SHACL) reads one row for each transfer or
account with a column for each term. The column names come from mapping/query_vars.ttl, so they are the same as for the other modes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_ontology  # noqa: E402
import queryplan  # noqa: E402


def term_name(iri):
    """The IRI a row holds -> 'amd:originator'."""
    return data_ontology.short(iri)


def terms_in(long_rows):
    return sorted({term_name(r["term"]) for r in long_rows})


def _pivot(long_rows, key):
    out = {}
    for r in long_rows:
        var = queryplan.query_var(term_name(r["term"]))
        if var is None:
            continue                       # a term with no variable name: nothing in the chain reads it
        out.setdefault(r[key], {key: r[key]})[var] = r["v"]
    return list(out.values())


def evidence(long_rows):
    """One row for each transfer: txid, ts, from, to, sameBank (whichever the Alignment asked for and the data answered)."""
    return _pivot(long_rows, "txid")


def background(long_rows):
    """One row for each account: account, customerType, industry (if it has one), tenure, pep, risk."""
    return _pivot(long_rows, "account")
