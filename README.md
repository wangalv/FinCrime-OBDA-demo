# AML Ontology-Based Data Access Demo

An experiment in answering an investigator's question about flagged transactions with LLM that only writes **SPARQL**, over terms from an ontology. A deterministic engine (**Ontop**) rewrites that SPARQL into SQL using an ontology and an R2RML mapping, runs it on the transaction database, and **SHACL plus plain code** decide the verdicts. The model never writes SQL and never decides a verdict.

The hypothesis: this is more reliable than asking the model to write SQL directly, and it says plainly what it cannot check.

**Status: exploratory.** Only one typology technique, **T0039 Circular Transactions**, works end to end. The AML terms, the bridge to the data, the indicator requirements and the rules are drafts that no domain expert has reviewed. The customer (KYC) profiles are **synthetic**. A page run is an illustration, not a measurement.

The repository also contains a copy of the earlier **aml-ontology** project (the typology as RDF, SHACL and SPARQL); see [Earlier work](#earlier-work-aml-typology-ontology) at the end.

## How a question is answered

```
question ──► ids ──► intent ──► typology ──► query plan ──► SPARQL ──► guard
 (investigator) (code)  (LLM)    (Ontop)       (code)        (LLM)     (code)
                                                                          │
 summary ◄── verdicts ◄── SHACL ◄── candidate ◄── rows ◄── SQL ◄── Ontop ◄┘
  (LLM)       (code)      (code)     (code)        (DB)   (Ontop) (ontology + R2RML)
```

| # | Step | Who | What happens |
|---|---|---|---|
| 1 | Ask | Investigator | Describes the suspicious pattern in their own words and gives the flagged transaction ids. |
| 2 | Find the ids | Code | Pulls the transaction ids out of the question. No ids, no run. |
| 3 | **Intent** | **LLM** | picks one technique from the AML typology's technique list (here, T0039). |
| 4 | Check the intent | Code | The chosen id must be in the list and under the tactic the model named. A technique the demo cannot check is named and declined. |
| 5 | Read the typology | Ontop | A SPARQL query over the typology data gives the technique's indicators, their text, what each one needs, and which needed terms the data lacks. |
| 6 | Plan the queries | Code | From the requirements, the AML terms and the bridge, decides which queries to run and which terms each one fetches. Terms with no data behind them are listed as missing, not queried. |
| 7 | **Write SPARQL** | **LLM** | writes the queries in one call. It sees only a list of AML terms and a task description, not the data, the mapping or the SQL. |
| 8 | Guard the SPARQL | Code | Checks syntax, read-only `SELECT`, unknown terms (Ontop returns zero rows for a term it does not know, instead of failing), the output variables, and that the ids match the question. |
| 9 | **Rewrite** | **Ontop** | Loads the ontology and the R2RML mapping, expands the mapping with the ontology (a data term that sits under an AML term answers it), unfolds the SPARQL through the mapping, optimises, and produces the **SQL**. |
| 10 | Run the SQL | Ontop, DuckDB | Read-only, on `tx_features` and `kyc_profiles`. |
| 11 | Assemble | Code | Puts the returned payments in time order and builds the candidate chain, with account background. |
| 12 | **SHACL** | pyshacl | Checks the structure against the rules in `validation/shapes/t0039.shapes.ttl`. |
| 13 | Verdicts | Code | For each indicator: held, not held, facts only, or cannot check. |
| 14 | Summary | LLM | Rewrites code-built facts into five plain-language parts. An optional rule check ("Checked by code") rejects a report that uses verdict words, technical words, unknown places or numbers, or contradicts SHACL; a rejected report is replaced by a fixed template. |

### Who does what

- **The model** does three things: reads the question to pick the technique (step 3), writes the SPARQL (step 7), and phrases the summary (step 14).
- **Ontop (OBDA)** turns SPARQL into SQL and runs it (steps 5, 9, 10). It reads the ontology and mapping when it starts, then answers each query from the expanded mapping. It does not load the data into a graph.
- **Code and SHACL** do everything else, including all verdicts. Plain Python in `src/`; the SHACL rules are data in `validation/`.

### What the page shows

The Streamlit page has two chat panels that receive the same question:

- **Without ontology**: LLM is given only the table rows of the flagged transactions and decides for itself. No typology, no mapping, no SHACL, no check.
- **With ontology**: the whole chain above.

Both panels answer in the same five parts (how the question was read, what information was used, what the records show, what was checked, what the records cannot tell), in business language, and show their processing time. A flow diagram shows which step and which layer is running.

## The six layers

Layers 2 to 5 are the semantic and data-access layers. Every path is defined once, in `src/paths.py`.

| Layer | Role | Files |
|---|---|---|
| 1 External knowledge | The AML typology (schema and data) as published | `ontology/amlo.ttl`, `data/amltrix.ttl`, `ontology/external/amltrix/typology_adapter.ttl` |
| 2 AML core ontology | AML terms (transfer, account, originator, beneficiary, ...), independent of any database | `ontology/core/aml_core.ttl` |
| 3 Requirements | What each indicator needs (`needsTerm`), what is background only (`backgroundTerm`), where it is recorded (`recordedIn`) | `ontology/application/typology_requirements.ttl` |
| 4 Data semantics | The database's own terms, and the bridge from AML terms to them (`fcd:fromAccount` is a `amd:originator`) | `ontology/alignment/source_vocabulary.ttl`, `ontology/alignment/aml_data_alignment.ttl` |
| 5 OBDA mapping | Table and column to term (R2RML), plus the Ontop view and connection settings | `mappings/transaction/`, `mappings/customer/`, `mappings/lenses/`, `config/ontop/` |
| 6 Validation | SHACL rules and the indicator registry | `validation/shapes/`, `validation/indicator_registry.json` |

A term with no bridge to the data (for example `amd:Jurisdiction`: the data has no country) is declared but unanswerable, which is how "cannot check" is derived rather than hard-coded.

## Code structure

```
app/            the Streamlit page
src/            the chain, step by step (plain Python); see below
tests/          unit tests and Ontop-backed regression tests
gold/           the frozen gold cases (hand-written SQL, SPARQL, expected rows and verdicts)
ontology/       layers 1 to 4: core, application, alignment, external
mappings/       layer 5: R2RML for the transaction and customer tables, the Ontop view
config/ontop/   Ontop connection settings (DuckDB)
validation/     layer 6: SHACL rules and the indicator registry
mapping/        query_vars.ttl: which variable name each AML term gets in a query
generated/      saved experiment runs (files that can be rebuilt are git-ignored)
data/, vendor/  the AML typology as RDF, and its unmodified CSV export with licence
docs/           design documents and the T0039 walkthrough
tools/          Ontop, JDK and the DuckDB driver (git-ignored, not in the repository)
PLAN.md         design, experiment conditions, milestones
SETUP.md        how to get the demo running (LLM, Ontop, database)
```

`scripts/`, `shapes/`, `site/`, `jsonld/`, `rdfxml/` and `demo/` belong to the earlier work (see the end of this file); `demo/` has its own older scenarios, mappings and tests. `ontology/amlo.ttl`, `data/` and `vendor/` also come from it, but the experiment reads them as layer 1.

**`src/`, in the order a question uses it**

| Module | Step | What it does |
|---|---|---|
| `demo_run.py` | all | Runs one question through the whole chain and yields an event per step. The page and the tests both call it. |
| `intent.py` | 3, 4 | Asks the model for a technique from the typology's list and checks the answer against that list. |
| `typology.py`, `sources.py` | 5 | Reads the technique, its indicators and data sources through Ontop and cross-checks them against the registry. |
| `queryplan.py` | 6 | Derives which queries to run from the requirements, the AML terms and the bridge. |
| `prompt.py` | 7 | The prompt that makes the model write SPARQL; the prompt version is saved with every run. |
| `sparql_guard.py` | 8 | Checks the model's SPARQL before it reaches Ontop. |
| `data_ontology.py`, `ontop_run.py` | 9, 10 | Builds the ontology file Ontop is given, calls Ontop, and returns the rows and the SQL it wrote. |
| `pivot.py`, `pipeline.py`, `loop_check.py` | 11, 12 | Turns the rows into a candidate chain and checks it with SHACL (pyshacl). |
| `indicators.py` | 13 | Gives each indicator its answer: held, not held, facts only, or cannot check. |
| `summarize.py` | 14 | Builds the facts, asks the model to phrase them in five parts, and runs the optional rule check. |
| `baseline.py` | | The "Without ontology" side: the model sees only the table rows. |
| `llm.py` | | A small client for any LLM with an OpenAI-compatible chat API. It reads the key and model from `.env`; no key is in the code. |
| `flow_view.py`, `graph_view.py` | | The flow diagram and the graph the page draws while a question runs. |
| `paths.py` | | The one place that says where every knowledge, mapping and validation file lives. |

Also in `src/`, not on the page's path:

- `gold_build.py`, `gold_build_f3.py`, `gold_selftest.py`, `gold_selftest_f3.py`, `judge.py`, `queries.py`: build the gold cases, check them through Ontop, and compare a run with the gold. `pipeline.py` can run the back half of the chain with the gold SPARQL standing in for the model.
- `try_model.py`: a small trial of the model writing queries (saved under `generated/`; not a measurement).
- `unified.py`, `typology_ontop.py`, `build_amltrix_mapping.py`: an alternative "intent only" mode (one virtual graph over the typology and the transaction data) and the Ontop reading of the typology. The page does not offer that mode.

## Example: T0039 Circular Transactions

**Question** (Investigator):

> I think these transactions may be Circular Transactions. The ids are 2131053, 2204314, 2282865. Please check.

**Intent** (LLM, checked by code): technique **T0039 Circular Transactions**, tactic Layering.

**SPARQL** (LLM, in AML terms; the transaction query):

```sparql
SELECT ?txid ?to ?from ?sameBank ?ts WHERE {
  VALUES ?txid { 2131053 2204314 2282865 }
  ?tx a amd:FundsTransfer ;
      amd:transferId ?txid ;
      amd:beneficiary ?to ;
      amd:originator ?from ;
      amd:sameInstitution ?sameBank ;
      amd:transferTime ?ts .
}
```

**SQL** (written by Ontop from the mapping, not by the model):

```sql
SELECT "v1"."from_account", "v1"."is_same_bank", "v1"."to_account", "v1"."tx_id", STRFTIME("v1"."ts", '%xT%X')
FROM "tx_features" "v1", (VALUES (2131053), (2204314), (2282865)) AS "v2" ("tx_id1m1")
WHERE ("v1"."to_account" IS NOT NULL AND "v1"."from_account" IS NOT NULL
   AND "v1"."is_same_bank" IS NOT NULL AND "v1"."ts" IS NOT NULL AND "v1"."tx_id" = "v2"."tx_id1m1")
```

**Rows** (3 returned; a second query returns the background of the three accounts):

| Transaction | Time | From account | To account | Same bank |
|---|---|---|---|---|
| 2131053 | 2022-09-04 04:53 | 812D22980 | 811C597B0 | no |
| 2204314 | 2022-09-04 14:05 | 811C597B0 | 811B83280 | no |
| 2282865 | 2022-09-04 23:49 | 811B83280 | 812D22980 | no |

The money goes 812D22980 → 811C597B0 → 811B83280 → back to 812D22980.

**SHACL and verdicts** (code, not the model):

| Indicator | Result |
|---|---|
| IND02191 Cyclical pattern | **Held**: first payment starts at the origin, each payment starts where the previous one went, the last returns to the origin, more than one account is involved |
| IND02195 Convoluted routing | Facts only: 3 payments, all between different banks. The typology gives no number for "multiple hops", so there is no verdict |
| IND02192, 02193, 02194, 02196, 02197, 02198, 02199 | Cannot check: they need company groups, invoices, shipments, legal-entity records, declared activity or exact amounts, none of which the data holds |

**Summary** (LLM's wording of those facts; one run, shortened):

> **What the records show.** The payments occurred in order: transaction 2131053 moved funds from account 812D22980 to 811C597B0, transaction 2204314 moved them from 811C597B0 to 811B83280, and transaction 2282865 returned funds from 811B83280 to 812D22980.
>
> **What I checked, and the result.** The first payment started at the origin account, the last payment returned to it, each payment followed the previous destination, and more than one account was involved.
>
> **What these records cannot tell.** Whether a legitimate business reason exists is not in the data. Indicators that need company group structures, invoices, shipment records or legal-entity records cannot be checked.

The report never says the activity is suspicious or money laundering: the system only says whether a structure matches the typology's description. Whether the cycle has a business reason is the investigator's call.

## Run it

Full steps are in **[SETUP.md](SETUP.md)**. In short, you need:

- Python 3.9 and `pip install -r requirements.txt`.
- **Any LLM with an OpenAI-compatible chat API.** Copy `.env.example` to `.env` and set `LLM_API_KEY`, `LLM_BASE_URL` and `LLM_MODEL`. Nothing is installed locally.
- **Ontop 5.5.0**, a JDK 21 and the DuckDB JDBC driver, placed under `tools/` (git-ignored).
- The transaction database `features.duckdb` (tables `tx_features` and `kyc_profiles`). It is built from the IBM AML sample, the KYC table is synthetic, and **it is not in this repository** yet; see [SETUP.md](SETUP.md#4-the-database).

```
.venv/bin/streamlit run app/streamlit_app.py
```

Then open <http://localhost:8501>. Restart the page after changing `.env` or anything in `src/`.

Tests (several call Ontop and the database, so they need the setup above):

```
.venv/bin/python -m unittest discover -s tests -t .
```

## What is not done

- Only T0039 is covered. Other techniques have no requirements or SHACL rules yet.
- The AML terms, bridge and requirements are my reading of the typology, not reviewed by a domain expert.
- There is no measurement yet. The planned comparison (SQL written directly, SPARQL through Ontop, with and without SHACL) is in `PLAN.md`.
- The model's SPARQL is checked for form, not for meaning: a query can pass the guard and still miss something.
- Namespaces under `https://example.org/` are placeholders.

More: `docs/solution_design_v2.pdf` (the six layers and the design), `docs/blog_T0039_walkthrough.pdf` (a walkthrough of this example), `PLAN.md` (design and experiments), `docs/M0_indicator_inventory.md` (which indicators this data can answer).

## Attribution

The typology text and data are derived from **AMLTRIX** by UAB Amlyze
(<https://framework.amltrix.com>), used under the AMLTRIX License Terms
(<https://framework.amltrix.com/license>, copy in `vendor/amltrix/LICENSE.txt`).
This work is a derivative and is not endorsed by AMLTRIX. Derivative works must keep this
attribution and be distributed under the same terms.

---

# Earlier work: AML typology ontology

The rest of this file is the README of the earlier **aml-ontology** project, unchanged. Its static pages (formerly `docs/`) now live in `site/`.

## AML ontology (middle layer)

A worked example of turning the AMLTRIX money-laundering framework into a validated RDF ontology.

| Path | What it is |
|---|---|
| `ontology/amlo.ttl` | Hand-written schema (classes and properties) |
| `scripts/build_abox.py` | Converts the AMLTRIX CSV export into `data/amltrix.ttl` |
| `data/amltrix.ttl` | Generated instance data (about 78k triples) |
| `shapes/amlo-shapes.ttl` | SHACL integrity rules |
| `scripts/validate.py` | Validates the data, then proves the rules catch broken copies |
| `scripts/run_queries.py` | SPARQL competency questions |
| `scripts/import_neo4j.py` | Loads `data/amltrix.ttl` into Neo4j as a property graph (optional, for visual exploration) |
| `vendor/amltrix/` | Unmodified AMLTRIX 1.0-beta.4 CSV export, licence and notice |

Run in order, from this folder:

```
.venv/bin/python scripts/build_abox.py
.venv/bin/python scripts/validate.py
.venv/bin/python scripts/run_queries.py
```

Optional: view the graph in Neo4j. The connection settings are read from the environment
(`NEO4J_PASSWORD` is required; `NEO4J_URI`, `NEO4J_USER`, `NEO4J_DATABASE` default to
`bolt://localhost:7687`, `neo4j`, `neo4j`). Re-running is safe; `--clear` removes only the imported `:AMLO` nodes.

```
.venv/bin/python scripts/import_neo4j.py --dry-run
NEO4J_PASSWORD=... .venv/bin/python scripts/import_neo4j.py
```

### Known source-data issues (AMLTRIX 1.0-beta.4)

- The ID `T0098` is assigned to two different techniques (Loan Schemes, Service Contract Manipulation).
  The converter keeps them as separate nodes, disambiguated by STIX UUID.
- The website says `T0020.002` was redefined as `T0150`; the CSV still lists it as Cryptojacking and has no `T0150`.
- The references table has 1,302 rows but only 74 have a name; it is not converted.
