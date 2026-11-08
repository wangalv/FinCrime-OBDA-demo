"""Run one SPARQL query through Ontop (tools/ontop.sh) against the real database. Returns (rows, normalised SQL, seconds, error)."""
import csv, io, os, re, subprocess, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_ontop(sparql):
    with tempfile.TemporaryDirectory() as d:
        q, o = Path(d) / "q.rq", Path(d) / "out.csv"
        q.write_text(sparql, encoding="utf-8")
        env = dict(os.environ, ONTOP_LOG_LEVEL="debug")
        t = time.time()
        p = subprocess.run([str(ROOT / "tools" / "ontop.sh"), "query", "-m", "mapping/tx_features.r2rml.ttl",
                            "-p", "tools/ontop-duckdb.properties", "-v", "mapping/tx_features.lens.json",
                            "-q", str(q), "-o", str(o)], cwd=ROOT, capture_output=True, text=True, env=env)
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
            sql = re.sub(r"1m\d+", "1mN", "\n".join(sql_lines))   # Ontop numbers column aliases differently on each run
        return rows, sql, secs, None
