"""Run one SPARQL query through Ontop (tools/ontop.sh) against the real database. Returns (rows, normalised SQL, seconds, error)."""
import csv, io, os, re, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
from rdflib import Graph  # noqa: E402

ROOT = paths.ROOT


def data_mapping():
    """Ontop takes ONE mapping: the R2RML files of the data (transfers, customer profiles) are merged into a generated file; returns its path relative to the repo root."""
    g = Graph()
    for m in paths.DATA_MAPPINGS:
        g.parse(m)
    text = g.serialize(format="turtle")
    out = paths.DATA_MAPPING_MERGED
    if not out.exists() or out.read_text(encoding="utf-8") != text:
        out.parent.mkdir(exist_ok=True)
        out.write_text(text, encoding="utf-8")
    return paths.rel(out)


def run_ontop(sparql, normalize=True, ontology=None, mapping=None, props=None, lens=True):
    """ontology: path (relative to the repo root) of an ontology file for Ontop's -t. With it Ontop also rewrites the query by the ontology
    (subclasses, subproperties); without it only the mapping is used and a term that has no mapping silently returns no rows."""
    with tempfile.TemporaryDirectory() as d:
        q, o = Path(d) / "q.rq", Path(d) / "out.csv"
        q.write_text(sparql, encoding="utf-8")
        env = dict(os.environ, ONTOP_LOG_LEVEL="debug")
        t = time.time()
        cmd = [str(paths.ONTOP_SH), "query", "-m", mapping or data_mapping(),
               "-p", props or paths.rel(paths.ONTOP_PROPS), "-q", str(q), "-o", str(o)]
        if lens:
            cmd += ["-v", paths.rel(paths.LENS)]
        if ontology:
            cmd += ["-t", ontology]
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env)
        secs = time.time() - t
        log = p.stdout + p.stderr
        if p.returncode != 0 or not o.exists():
            return None, None, secs, log[-600:]
        rows = list(csv.DictReader(io.StringIO(o.read_text(encoding="utf-8"))))
        lines = log.splitlines()
        start = next((i for i, l in enumerate(lines) if l.startswith(('SELECT "', 'SELECT DISTINCT "'))), None)
        sql = ""
        if start is not None:
            sql_lines = [lines[start]]
            for l in lines[start + 1:]:
                if not l.strip():          # Ontop prints the SQL as a block that ends at an empty line
                    break
                sql_lines.append(l)
            sql = "\n".join(sql_lines)
            if normalize:
                sql = re.sub(r"1m\d+", "1mN", sql)   # Ontop numbers column aliases differently on each run
        return rows, sql, secs, None
