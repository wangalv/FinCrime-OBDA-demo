# AML OBDA Demo plan: how stable is a small model at asking questions through an ontology?

Status: plan rewritten 2026-11-08; no experiment code yet. Project `aml-obda-demo` ("AML OBDA Demo"), separate from AML Triage. It holds a copy of the earlier aml-ontology project (ontology, `demo/`, `site/`) as its base.
Replies to the user in Chinese; code, identifiers and page text in English.

## 1. What this demo is meant to show

An investigator says: "I think these transactions are Circular Transactions (T0039), here are the transaction ids, please check."
A small local model turns that into SPARQL over ontology terms. Ontop turns the SPARQL into SQL through an R2RML mapping and runs it.
Code assembles the returned transactions into a candidate loop, and SHACL rules (our reading of the T0039 indicator) say which
parts of the pattern hold. The answer lists, per indicator of T0039, what was checked, what held, and what this data cannot answer.

The long-term aim is an agent that automates this kind of work. The question here is smaller and measurable: **does putting an
ontology and OBDA between a small model and the database make the model's queries more stable?** That is a hypothesis, tested below.

- H1. A small model that writes SPARQL over ontology terms (Ontop produces the SQL) is more stable than the same model writing SQL directly, with or without a data dictionary.
- H2. A SHACL check on the assembled candidate turns "ran fine but means the wrong thing" into a visible failure.
- H3. For one question, the system answers the indicators the data can answer and says plainly which it cannot.

"Guaranteed accuracy" is not a claim we can make. We report counts with intervals, and which failures a check caught versus let through.
Stability means two things and they are kept apart: **consistent** (same answer across repeats and rewordings) and **correct** (matches the hand-written gold). Consistent but wrong is the worst case, so correctness is the main measure.

## 2. Scope and decisions

Decided (2026-11-08):
1. **Technique T0039 Circular Transactions, indicator IND02191 first.** Its SHACL draft already exists. T0011 is parked, not dropped: it adds question types (rapid in-out, new accounts, small cash deposits) but needs a tight definition of rapid in-out and the synthetic KYC first. IND01115 has the same loop shape, but its text says "related accounts", which this data cannot show.
2. **No minimum number of legs** (changed 2026-11-08; earlier "at least 3 legs" was ours, not the typology's, which says only "multiple accounts"). A loop involves more than one account, so a two-leg round trip counts.
3. **Legs must be in time order.**
4. **Ontop is used directly** (5.5.0, in `tools/`). We do not write our own rewriter.
5. The model writes **SPARQL**, never SQL.
6. The investigator supplies the transaction ids; code, not the model, orders the legs and fixes the origin.

Consequences to state on any page: the IBM pattern sample has cycles of 2 to 10 legs (two of seven have 2 legs, which now count; one 7-leg cycle is out of time order, so our time-order rule will reject that labelled one). The rules are our reading of one indicator sentence; the typology itself has no rules. Whether a cycle lacks a business rationale is not in the data and is left to the investigator.

## 3. What exists (checked 2026-11-08)

- **Data** (AML Triage `data/features.duckdb`, read only): `tx_features` 5,078,345 rows (`tx_id`, `ts`, `label`, `from_account`, `to_account`, `amount_log`, flags; no raw amount); `kyc_profiles` is synthetic and not needed for T0039. No country or place field anywhere.
- **Data check** (details in `docs/M0_indicator_inventory.md`): 1,242 time-ordered 3-account loops within 7 days, 843 with all legs labelled laundering, 221 with none labelled (natural look-alikes, useful as negatives); 6,452 time-ordered round trips (not counted under decision 2).
- **Ontop 5.5.0 + project JDK 21 + DuckDB JDBC 2.0.0.1** in `tools/` (git-ignored); `tools/ontop.sh`; connection file `tools/ontop-duckdb.properties`. Smoke test passed on `tx_features`. The JDBC URL must not carry `?access_mode=read_only`; read-only is a property.
- **Reusable code** in `demo/amldemo/`: `scenarios/s3_obda.py` (LLM-as-engine, becomes condition B), `sqlguard.py` (`check_closed_loop`), `claims.py` (says-more-than-evidence check), `dbrun.py`, `llm.py`. The existing `txs.r2rml.ttl` points at a view `txs` that the database does not contain; it must be rewritten for `tx_features`.
- **SHACL draft** for T0039 / IND02191: AML Triage `ontology/examples/circular_transactions.shapes.ttl` and `.sample.ttl`. Written for the demo, not run on real data; needs `amount_log` instead of `amount`, and the leg count changed to the decision above (already at least 3).
- **Models:** `qwen3.5:9b` only (Ollama); z.ai `glm-5.3-flash` as a slow reference. Earlier evidence for the baseline: qwen3.5:9b wrote working SQL for IND02191 once in four tries.
- **Not available:** `.venv` (not copied; rebuild from `requirements.txt` after asking), the full IBM pattern file (only a 55-attempt sample).

## 4. Design

### 4.1 Pipeline
1. Investigator question plus transaction ids.
2. Model, given the T0039 text, its indicators and the ontology terms, writes one SPARQL query per indicator the data can answer. For the others it states what is missing.
3. Ontop rewrites each SPARQL through the R2RML mapping to SQL and runs it on DuckDB (read only).
4. Code assembles the returned legs into a candidate loop: order by time, first leg's payer is the origin. The model does not fill these.
5. pyshacl validates the candidate against the T0039 shapes. Output is per rule: pass, or violation with its message; a Warning if a business rationale is recorded.
6. Answer per indicator: held, did not hold (which rule), cannot be checked here (what is missing). No wording stronger than "structure matches the description".

### 4.2 What the model is for (and what it is not)
The model translates the question into SPARQL over ontology terms and decides, from the indicator list, what to ask. It does not write SQL, order legs, decide whether a pattern is a loop, or decide which indicators the data can answer (that is `docs/M0_indicator_inventory.md`). Where the same question could be answered by a fixed template, the demo says so: the model earns its place only on varied wording and varied questions, so the question set must vary.

### 4.3 Question families (F1, F2, and F3 for context)
- **F1, verify given ids.** "These ids look circular, confirm." The model's SPARQL fetches the legs for the ids. Errors available to it: wrong ids filter, from and to swapped, wrong time property. The loop judgement is SHACL's.
- **F2, scoped search.** "Is there a loop through account X in these days?" The model writes a fixed-length chain (3 and 4 legs) as self-joins with time order. Ontop rewrites it; SHACL validates what comes back. This is where "ran fine but means the wrong thing" can really happen (a chain instead of a loop), so it is where H1 and H2 are tested hardest. Loops longer than the fixed length are not found; the answer must say so.
- **F3, account context (added 2026-11-08).** "Who are the customers behind these accounts?" The model's SPARQL joins transactions to the account's KYC properties; Ontop writes the two-table join, which the SQL conditions A and B must write themselves. Gold: `gold/cases_f3.json` (7 cases built from F1 transactions, checked through Ontop). The synthetic `industry` is random and unrelated to the transactions, and `onboarding_tenure_days` is a random draw with no reference date, so the answer shows them as background only and never as a reason for suspicion.

### 4.4 Mapping and ontology
Rewrite `transaction_ontology.ttl` and the R2RML for `tx_features`: Transaction (id, time, payer, receiver, `amountLog`) and Account, plus the account context from the synthetic `kyc_profiles` (customer type, industry, tenure, PEP, risk rating; added 2026-11-08, two tables). KYC is context for the investigator, not evidence for any indicator: no T0039 indicator becomes answerable because of it. The mapping records that `amount_log` is a logarithm (to be confirmed which) and that the data has no raw amount.
**First thing to verify:** whether Ontop accepts the time-order comparisons and the window (`?t2 > ?t1`, and a bound such as "within 7 days"). Timestamp arithmetic in FILTER is not standard SPARQL; if Ontop rejects it, use comparisons with computed bounds or put the window in the mapping.

### 4.5 SHACL
One shape for the candidate loop (more than one account, first leg starts at origin, last ends there, consecutive legs connect, time order) and one for a leg. Keep the Python `check_closed_loop` running in parallel so we can report if the two ever disagree. The page states the boundary: SHACL checks the structure of what was retrieved; finding the loop is the SQL's job.

### 4.6 The nine T0039 indicators
IND02191 full check; IND02195 partial (hops, same bank or not answerable; jurisdictions not); the other seven refused with the missing data named. The refusal is part of the result, not a failure.

## 5. Experiment

| Condition | Model writes | Code does |
|---|---|---|
| A | SQL from table schema only | SQL guard |
| B | SQL with a data dictionary (today's scenario 3) | SQL guard, closed-loop test |
| C | SPARQL over ontology | Ontop rewrite, SQL guard |
| D | SPARQL over ontology | Ontop rewrite, SQL guard, candidate assembly, SHACL |

- **Questions:** a small set of intents (F1 confirm ids, F1 with a broken candidate such as a chain or an open path, F2 search from an account, a question that must be refused), each in many wordings (different phrasing, different number of ids, with and without a time window). Same intent repeated verbatim only measures sampling noise.
- **Gold:** hand-written SQL per question, verified by hand, compared by the set of tx_ids returned and, for F1, by the expected structure verdict. Positives from the 843 fully labelled loops; negatives from the 221 unlabelled loops (structure holds, nobody labelled it) and from constructed chains and open paths.
- **Runs:** pilot of 5 per cell first to measure time and fix the harness, then 20 per cell, temperature 0.3, retries fixed (up to 3), report first attempt and final.
- **Outcomes recorded per run:** correct; **rejected by a check** (which one); **silently wrong** (ran, passed every check, result differs from gold). Also consistency across repeats and rewordings, attempts needed, seconds. Wilson intervals; counts shown.
- **What a good result looks like:** not necessarily more correct answers, but fewer silently wrong ones, with the difference turning into visible rejections.
- **Limits to state:** one technique, one indicator, synthetic labels and structure, one local model, small samples, single-step queries. The result is about one step of an agent; errors accumulate over several steps and this does not measure that.
- Everything saved as JSON in `generated/` with model, prompt version and date; pages call it a saved run.

## 6. Milestones

| | Output | Done when |
|---|---|---|
| M0 | Indicator inventory, data check | reviewed by the user (inventory is a first pass, no domain expert yet) |
| M1 | Ontology and R2RML for `tx_features`; Ontop runs gold SPARQL for F1 and F2; time filters verified | rewritten SQL returns the same tx_ids as the hand-written gold SQL |
| M2 | Candidate assembly and SHACL shapes on real fields; tests | shapes accept the labelled loops, reject chains, open paths and out-of-order legs; Python and SHACL checks agree |
| M3 | Question set, gold, harness for conditions A to D; pilot | pilot numbers and timings in hand |
| M4 | Full runs, saved results | complete results file; failures sorted by cause |
| M5 | Investigator flow: one question to a card per indicator, refusals included | runs end to end on one real alert |
| M6 | Pages (static, then Streamlit) and CLAUDE.md notes | user reviews before any push |

## 7. Decisions still open
- Whether F2 (scoped search) is in the first version or comes after F1.
- Whether to download a second, smaller local model (name and size to be confirmed with the user), or stay with `qwen3.5:9b` plus z.ai.
- Whether Ontop's time handling is enough (see 4.4); if not, how the window is expressed.
- What `amount_log` is (log or log1p) and whether amounts matter to any rule.
- A domain expert's review of the T0039 rules and of the inventory marks.
- Where it appears (a new scenario under the Investigation agent, keeping scenario 3 as condition B) and whether results go on the public Pages site. Not before the user reviews.

## 8. Not doing
No own SPARQL rewriter, no T0011 work and no KYC-based indicator in this version (KYC is used only as account context, F3), no live LLM call from a page, no claim of guaranteed accuracy, no accuracy figure from fewer than the planned runs, no change to the AML Triage repo, no commit or push without the user's say.
