"""Convert the Turtle files to JSON-LD and check each result round-trips to the same graph.

Run:  .venv/bin/python scripts/to_jsonld.py
Output: jsonld/amlo.jsonld, jsonld/amlo-shapes.jsonld, jsonld/amltrix.jsonld
"""
from pathlib import Path

from rdflib import Graph
from rdflib.compare import isomorphic

ROOT = Path(__file__).resolve().parent.parent
# source file -> indent (None keeps the large data file compact)
FILES = {"ontology/amlo.ttl": 2, "shapes/amlo-shapes.ttl": 2, "data/amltrix.ttl": None}

out_dir = ROOT / "jsonld"
out_dir.mkdir(exist_ok=True)
for rel, indent in FILES.items():
    src = ROOT / rel
    out = out_dir / (src.stem + ".jsonld")
    g = Graph().parse(src)
    out.write_text(g.serialize(format="json-ld", auto_compact=True, indent=indent), encoding="utf-8")
    back = Graph().parse(out, format="json-ld")
    same = isomorphic(g, back)
    print(f"{rel:28} -> jsonld/{out.name:20} {len(g):>6} triples  {out.stat().st_size / 1e6:6.2f} MB  round-trip identical: {same}")
    if not same:
        raise SystemExit("round-trip mismatch: " + rel)
