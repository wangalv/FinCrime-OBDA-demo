"""Load data/amltrix.ttl into Neo4j as a property graph (full version, Link nodes included).

Mapping:
  - every typed subject becomes a node labelled :AMLO plus its rdf:type (e.g. :AMLO:Technique)
  - literals become node properties (multi-valued ones become lists)
  - object properties between typed subjects become relationships (isIndicatedBy -> IS_INDICATED_BY)
  - IRIs that point outside the graph (rdfs:seeAlso, dct:source, dct:license) stay as string properties
  - inverse properties are not expanded; edges keep the direction stored in the Turtle

The import is idempotent (MERGE on uri). --clear removes only :AMLO nodes.

Connection settings come from the environment, never from the command line:
  NEO4J_URI (default bolt://localhost:7687), NEO4J_USER (default neo4j),
  NEO4J_PASSWORD (required), NEO4J_DATABASE (default neo4j)

Run:  .venv/bin/python scripts/import_neo4j.py --dry-run
      .venv/bin/python scripts/import_neo4j.py [--clear]
"""
import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

ROOT = Path(__file__).resolve().parent.parent
BATCH = 1000
SAFE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


def local(iri):
    s = str(iri)
    name = s.rsplit("#", 1)[-1] if "#" in s else s.rsplit("/", 1)[-1]
    if not SAFE.match(name):
        raise ValueError("unexpected IRI local name: " + s)
    return name


def rel_type(predicate):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", local(predicate)).upper()


def build(path):
    g = Graph().parse(path)
    typed = set(g.subjects(RDF.type, None))

    raw = defaultdict(lambda: defaultdict(list))
    edges = defaultdict(list)
    for s, p, o in g:
        if p == RDF.type:
            continue
        if s not in typed:
            raise ValueError("untyped subject: " + str(s))
        if isinstance(o, URIRef) and o in typed:
            edges[rel_type(p)].append((str(s), str(o)))
        else:
            raw[str(s)][local(p)].append(str(o))

    nodes = {}
    for s in sorted(typed, key=str):
        labels = sorted(local(o) for o in g.objects(s, RDF.type))
        props = {"uri": str(s)}
        for name, values in raw[str(s)].items():
            values = sorted(values)
            props[name] = values[0] if len(values) == 1 else values
        pref = props.get("prefLabel")
        props["name"] = pref if isinstance(pref, str) else props.get("notation") or "%s %s" % (labels[0], str(s)[-8:])
        nodes[str(s)] = {"labels": labels, "props": props}

    for rows in edges.values():
        rows.sort()
    return nodes, edges


def chunks(rows):
    for i in range(0, len(rows), BATCH):
        yield rows[i:i + BATCH]


def write(driver, database, nodes, edges, clear):
    with driver.session(database=database) as session:
        if clear:
            session.run("MATCH (n:AMLO) DETACH DELETE n").consume()
        session.run("CREATE CONSTRAINT amlo_uri IF NOT EXISTS FOR (n:AMLO) REQUIRE n.uri IS UNIQUE").consume()

        by_labels = defaultdict(list)
        for n in nodes.values():
            by_labels[tuple(n["labels"])].append(n["props"])
        for labels, rows in by_labels.items():
            q = "UNWIND $rows AS row MERGE (n:AMLO {uri: row.uri}) SET n:%s SET n += row" % ":".join(labels)
            for batch in chunks(rows):
                session.run(q, rows=batch).consume()
            print("  nodes  %-18s %6d" % (":".join(labels), len(rows)))

        for rtype, pairs in sorted(edges.items()):
            q = ("UNWIND $rows AS row MATCH (a:AMLO {uri: row.s}), (b:AMLO {uri: row.o}) "
                 "MERGE (a)-[:%s]->(b)" % rtype)
            rows = [{"s": s, "o": o} for s, o in pairs]
            for batch in chunks(rows):
                session.run(q, rows=batch).consume()
            print("  edges  %-18s %6d" % (rtype, len(rows)))

        n = session.run("MATCH (n:AMLO) RETURN count(n) AS c").single()["c"]
        r = session.run("MATCH (:AMLO)-[r]->(:AMLO) RETURN count(r) AS c").single()["c"]
    return n, r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="parse and summarise, do not connect")
    ap.add_argument("--clear", action="store_true", help="delete existing :AMLO nodes first")
    args = ap.parse_args()

    nodes, edges = build(ROOT / "data" / "amltrix.ttl")
    n_edges = sum(len(v) for v in edges.values())
    print("parsed: %d nodes, %d relationships, %d relationship types" % (len(nodes), n_edges, len(edges)))
    if args.dry_run:
        for rtype, pairs in sorted(edges.items()):
            print("  edges  %-18s %6d" % (rtype, len(pairs)))
        return

    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        sys.exit("NEO4J_PASSWORD is not set (read from the environment only).")

    from neo4j import GraphDatabase

    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        driver.verify_connectivity()
        n, r = write(driver, database, nodes, edges, args.clear)
    print("in Neo4j now: %d nodes, %d relationships" % (n, r))
    if (n, r) != (len(nodes), n_edges):
        print("WARNING: counts differ from the parsed graph (expected %d / %d)" % (len(nodes), n_edges))


if __name__ == "__main__":
    main()
