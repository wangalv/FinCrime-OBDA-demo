# Setup

How to get the demo running on your own machine. The README says what the demo does; this file says what you need and in what order.

The demo needs four things, and the first three you can get yourself:

| Need | For | Where it comes from |
|---|---|---|
| Python 3.9 and the packages in `requirements.txt` | the page, the checks, SHACL | `pip` |
| **Any LLM with an OpenAI-compatible chat API** | reading the question, writing SPARQL, phrasing the summary | your provider; nothing runs locally |
| Ontop 5.5.0, a JDK 21 and the DuckDB JDBC driver | rewriting SPARQL into SQL | downloaded into `tools/` |
| The transaction database `features.duckdb` | the data the SQL runs on | **not in this repository**, see step 4 |

Tested on macOS. The Ontop wrapper (`tools/ontop.sh`) expects the macOS JDK layout; on Linux, edit its `JAVA_HOME` line.

## 1. Python

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`requirements.txt` includes `neo4j`; it is only used by an optional script from the earlier work (`scripts/import_neo4j.py`) and the demo does not need it.

## 2. The LLM

The demo calls the chat API of whatever provider you choose: the request goes to `<LLM_BASE_URL>/chat/completions`, so any provider with an OpenAI-compatible API works (OpenAI, OpenRouter, Z.ai, and others). No model is installed on your machine.

```bash
cp .env.example .env
```

Then edit `.env` (it is git-ignored; never commit a real key):

```
LLM_API_KEY=...        your provider's key
LLM_BASE_URL=...       the API root, for example https://api.openai.com/v1
LLM_MODEL=...          the model name your provider uses
```

Two optional lines are described in `.env.example`: `LLM_EXTRA_BODY` (a provider-specific switch, such as turning thinking off) and `LLM_JSON_MODE=off` (if your provider rejects the `response_format` field; the call is retried without it anyway). The older names `Z_AI_API_KEY`, `Z_AI_BASE_URL` and `Z_AI_CHAT_MODEL` are also read, for the AML Triage Demo.

Things to know:

- **What is sent out:** the investigator's question, the typology text, the SPARQL task, the facts the summary is built from, and, in the "Without ontology" panel, the rows of the transactions you name. Nothing else, and never the whole database. Use a provider you are allowed to send that to.
- **Cost and time:** one question makes 3 model calls for the chain (the intent, the SPARQL, the summary) plus 1 for the comparison panel. A slow or reasoning model makes the page slow.
- **Which model:** a small model is enough. The demo was built against a small model on purpose, to see how well the ontology and the checks hold it up. A reasoning model that thinks for a long time will make every step slow; use `LLM_EXTRA_BODY` to switch thinking off if your provider allows it.
- **A local model still works.** Any local server that offers the same API (for example one that serves `http://localhost:.../v1`) can be used by setting `LLM_BASE_URL` to it and leaving the key empty. It is not required.

Check it:

```bash
.venv/bin/python -m unittest tests.test_llm
```

That test uses a fake server on localhost and sends nothing out. To try your real provider with one tiny call:

```bash
.venv/bin/python -c "import sys; sys.path.insert(0,'src'); import llm; print(llm.chat('Reply with one JSON object.', 'Return {\"ok\": true}.'))"
```

## 3. Ontop, JDK and the DuckDB driver

All three go under `tools/` (git-ignored). The layout the wrapper expects:

```
tools/
  jdk/<jdk folder>/Contents/Home/    a JDK 21 (the demo used Eclipse Temurin 21; https://adoptium.net)
  ontop/                             the unpacked Ontop CLI, version 5.5.0 (https://github.com/ontop/ontop/releases)
    jdbc/duckdb_jdbc.jar             the DuckDB JDBC driver goes here ...
  jdbc/duckdb_jdbc.jar               ... and a copy here
```

The DuckDB JDBC driver is `duckdb_jdbc` from Maven Central (<https://repo1.maven.org/maven2/org/duckdb/duckdb_jdbc/>); the demo used 2.0.0.1. Use a driver at least as new as the DuckDB that wrote your database file, or it cannot read it.

Check it:

```bash
tools/ontop.sh --version
```

It should print `ontop version 5.5.0`. Ontop reads files by **relative path from the repository root**, and cannot read an absolute path that has a space in it, so always run the demo from the repository root.

## 4. The database

The SQL runs on a read-only DuckDB file with two tables:

- `tx_features`: one row per transaction (about 5 million rows in the original), built from the IBM AML sample. Columns used include `tx_id`, `ts`, `from_account`, `to_account`, `is_same_bank` and a log of the amount (there is no raw amount and no country).
- `kyc_profiles`: one row per account. **It is synthetic** (generated for the demo, not IBM data): customer type, industry, onboarding tenure, PEP flag and risk rating.

**This file is not in this repository.** It comes from the author's AML Triage project, and this repository does not yet contain a script that builds it. Without it the page cannot answer, and most Ontop tests cannot run. At the moment two places expect it at a fixed location next to this folder:

- `config/ontop/ontop-duckdb.properties`: `jdbc.url=jdbc:duckdb:../AML Triage Demo/data/features.duckdb`
- `src/baseline.py` and the gold scripts: the same file, and the Python of that project (`../AML Triage Demo/.venv/bin/python`), because the DuckDB package in this repository's Python 3.9 environment is older than the one that wrote the file.

If you have your own file with the same tables and columns, put it at that path (or edit the two places above). Making the location configurable, and shipping a small sample database so that anyone can run the demo, are not done yet.

## 5. Run it

From the repository root:

```bash
.venv/bin/streamlit run app/streamlit_app.py
```

Open <http://localhost:8501>. If the sidebar says no LLM is configured, step 2 is not finished. Restart the page after changing `.env` or anything in `src/`.

Tests, from the repository root:

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

Tests that call Ontop or the database need steps 3 and 4. Those that call the LLM use a stub, not your provider.

## Where things can go wrong

- **"the LLM is not configured"**: `LLM_BASE_URL` or `LLM_MODEL` is empty. Both are required; the key is only required if your provider needs one.
- **HTTP 401 or 403 from the LLM**: the key is wrong or the model name is not available to your key.
- **Zero rows and no error from Ontop**: a term in the query is not in the ontology (Ontop does not fail on an unknown term), or the database path is wrong. The page's checks catch the first case.
- **An empty `.duckdb` file appears next to the real one**: someone added `?access_mode=read_only` to the JDBC URL. Do not; the read-only setting is a separate line in the properties file.
- **The page still shows old behaviour**: Streamlit caches imported modules. Restart it after changing `src/`.
