"""SPARQL builders for the gold stand-in of the model: the same queries the gold files hold, plus the sameBank variant.
A model will later write queries like these; the pipeline only needs the column names listed in each builder."""
PREFIX = "PREFIX fcd: <https://example.org/fincrime-data#>"


def _values(ids):
    return " ".join(str(i) for i in ids)


def legs_sparql(ids):
    """IND02191: the legs for the given ids. Columns: txid, ts, from, to, amountLog. Identical to the F1 gold SPARQL."""
    return (f"{PREFIX}\nSELECT ?txid ?ts ?from ?to ?amountLog WHERE {{\n  VALUES ?txid {{ {_values(ids)} }}\n"
            f"  ?tx a fcd:Transaction ; fcd:txId ?txid ; fcd:timestamp ?ts ; fcd:fromAccount ?from ; fcd:toAccount ?to ; fcd:amountLog ?amountLog .\n}}")


def legs_bank_sparql(ids):
    """IND02195: the same legs with the between-bank flag. Columns: txid, ts, from, to, amountLog, sameBank."""
    return (f"{PREFIX}\nSELECT ?txid ?ts ?from ?to ?amountLog ?sameBank WHERE {{\n  VALUES ?txid {{ {_values(ids)} }}\n"
            f"  ?tx a fcd:Transaction ; fcd:txId ?txid ; fcd:timestamp ?ts ; fcd:fromAccount ?from ; fcd:toAccount ?to ;\n"
            f"      fcd:amountLog ?amountLog ; fcd:sameBank ?sameBank .\n}}")


def context_sparql(ids):
    """F3: customer background of every account that sends or receives. Identical to the F3 gold SPARQL."""
    return (f"{PREFIX}\nSELECT DISTINCT ?account ?customerType ?industry ?tenure ?pep ?risk WHERE {{\n"
            f"  VALUES ?txid {{ {_values(ids)} }}\n"
            f"  ?tx a fcd:Transaction ; fcd:txId ?txid .\n"
            f"  {{ ?tx fcd:fromAccount ?account }} UNION {{ ?tx fcd:toAccount ?account }}\n"
            f"  ?account fcd:customerType ?customerType ; fcd:onboardingTenureDays ?tenure ; fcd:pepFlag ?pep ; fcd:riskRating ?risk .\n"
            f"  OPTIONAL {{ ?account fcd:industry ?industry }}\n}}")
