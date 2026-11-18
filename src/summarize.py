"""The 'LLM summarized response': the investigation told to the investigator in business language, in five parts.

The five parts (SECTIONS), the same for both sides of the comparison (the other side is src/baseline.py, where the model sees only table rows):
  understood  how the question was read          data_used  what information was used and where it comes from
  found       what the records show              checked    what was checked and the result, indicator by indicator
  cannot_say  what these records cannot tell
The wording is business wording: no ontology, mapping, query, SQL, SHACL, table or column names (TECH_WORDS are rejected by check()).

facts(ans, names)    -> plain-text facts the report may rest on (the ONLY basis; nothing else may be claimed), built by code from the whole run
template(ans)        -> the same five parts written by code, used as the fallback and as the option without a model
llm_summary(ans, ..) -> (text, source, problems, seconds): the LLM writes the five parts from the facts; code checks it; if the check fails the template is used.
text is markdown: each part has a bold heading.
Checks: no verdict words (laundering, suspicious, illicit, guilty, ...), no technical words, no claim about places the facts never mention
(claims.unstated_place), no transaction id, account id or number that is not in the facts, all five parts present, and a statement of IND02191 that
contradicts its state is caught.
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("claims", ROOT / "demo" / "amldemo" / "claims.py")
claims = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(claims)

VERDICT_WORDS = re.compile(r"launder|illicit|criminal|fraud|guilty|suspicio|proves?\b|proof|洗钱|可疑|犯罪|欺诈", re.I)
STATE_TEXT = {"held": "the structure matches the description", "not_held": "the structure does not match the description",
              "cannot_check": "cannot be checked with this data", "facts_only": "only facts are reported (the typology gives no threshold)"}
PROMPT_VERSION = "s3-business-report-2026-11-13"
SECTIONS = [("understood", "How I read the question"), ("data_used", "What information I used"), ("found", "What the records show"),
            ("checked", "What I checked, and the result"), ("cannot_say", "What these records cannot tell")]
TECH_WORDS = re.compile(r"ontolog|\bmapping|sparql|\bsql\b|shacl|obda|ontop|r2rml|\biri\b|schema|\bquer(y|ies)\b|tx_features|kyc_profiles|\bcolumns?\b|\bdatabase\b", re.I)

# AML terms in the words an investigator uses (what is missing from the data is named this way, never by the term)
BUSINESS_LABEL = {
    "amd:originator": "the paying account", "amd:beneficiary": "the receiving account", "amd:transferTime": "the time of each payment",
    "amd:transferId": "the payment identifier", "amd:sameInstitution": "whether both accounts are at the same bank",
    "amd:Jurisdiction": "the country or jurisdiction of a payment", "amd:amountRaw": "the exact amount of each payment",
    "amd:Invoice": "invoices", "amd:Shipment": "shipment records", "amd:CompanyGroup": "the structure of company groups",
    "amd:SupportingDocument": "supporting documents", "amd:BeneficialOwnerChange": "changes of beneficial owner",
    "amd:LegalEntity": "legal entity records", "amd:DeclaredBusinessActivity": "the declared business activity",
    "amd:EntityLifecycleEvent": "company registration or closure events", "amd:LogisticsEvidence": "logistics evidence",
    "amd:FundsTransfer": "the payment records",
}
# the rules of IND02191 in business words, and where each comes from
RULE_TEXT = {
    "first_leg_starts_at_origin": ("the first payment starts at the origin account", "from the typology wording"),
    "last_leg_returns_to_origin": ("the last payment returns to the origin account", "from the typology wording"),
    "consecutive_legs_connect": ("each payment starts from the account the previous payment went to", "our reading of the wording"),
    "legs_in_time_order": ("the payments follow each other in time", "a rule we added"),      # only named when it fails: the payments are put in time order before the checks, so it holds by construction
    "at_least_2_accounts": ("more than one account is involved", "our reading of the wording"),
}
STATE_TEXT = {"held": "the structure matches the description", "not_held": "the structure does not match the description",
              "cannot_check": "cannot be checked with this data", "facts_only": "only facts are reported (the typology gives no threshold)"}


def short(text, n=75):
    """The start of an indicator's typology text, cut at a word, for naming it in one line."""
    text = text.strip()
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0].rstrip(",;:") + "..."


def label(term):
    """A term in business words. A term without a label is an error, not a guess: add it to BUSINESS_LABEL."""
    return BUSINESS_LABEL[term]


def _when(ts):
    return str(ts)[:16].replace("T", " ")


def route(ans):
    """The legs in time order: [(position, leg)], from the ids in ans['order']."""
    by = {x["tx_id"]: x for x in ans["legs"]}
    return [(i + 1, by[t]) for i, t in enumerate(ans["order"]) if t in by]


def cycle_ignoring_time(legs):
    """If the payments, taken without their times, form one cycle of accounts that uses every payment once, the accounts in that cycle order (starting at the
    paying account of the earliest payment); otherwise None. This is what 'wrong time order' is: a cycle on paper, which the money cannot have gone round in the order it happened."""
    if not legs:
        return None
    first = min(legs, key=lambda x: (x["ts"], x["tx_id"]))["from"]
    nxt = {}
    for x in legs:
        if x["from"] in nxt:
            return None
        nxt[x["from"]] = x["to"]
    seq, a = [first], nxt.get(first)
    while a is not None and a != first and len(seq) <= len(legs):
        seq.append(a)
        a = nxt.get(a)
    return seq if a == first and len(seq) == len(legs) else None


def first_break(rt):
    """In the time-ordered route [(position, leg)], the first payment that does not start where the one before it went: (position, account it starts at, account the previous went to), or None."""
    for (i, x), (_, prev) in zip(rt[1:], rt):
        if x["from"] != prev["to"]:
            return i, x["from"], prev["to"]
    return None


def leg_text(i, x):
    bank = {False: "between different banks", True: "within the same bank"}.get(x.get("same_bank"), "bank relationship not known")
    return f"Payment {i} (transaction {x['tx_id']}, {_when(x['ts'])}): from account {x['from']} to account {x['to']}, {bank}."


def sections_facts(ans, names):
    """{part: [fact sentences]}: everything the report may say, in business words."""
    byid = {e["id"]: e for e in ans["indicators"]}
    tech = ans.get("technique") or {}
    u, d, f, c, n = [], [], [], [], []
    ids = ", ".join(str(t) for t in ans["asked"])
    u.append(f"The investigator asked about transactions {ids}.")
    if tech.get("name"):
        how = {"model": "matched from the question", "investigator": "chosen by the investigator", "assumed": "assumed (no model reading of the question in this mode)"}.get(tech.get("how"), "")
        u.append(f"The question was read as {tech['name']}" + (f" (tactic: {tech['tactic']})" if tech.get("tactic") else "") + (f", {how}." if how else "."))
    if names.get("IND02191"):
        u.append(f"The typology describes it as: {names['IND02191']}")
    if ans["missing_ids"]:
        u.append(f"Not found in the data: {ans['missing_ids']}. The others were judged.")
    d.append("From the payment records: for each payment the paying account, the receiving account, the time" + (
        " and whether both accounts are at the same bank." if any(x.get("same_bank") is not None for x in ans["legs"]) else "."))
    if ans.get("context"):
        d.append("From customer profiles of the accounts involved (synthetic profiles made for this demo, not real customers): customer type, industry, time since the account was opened, politically exposed person flag, risk rating.")
    else:
        d.append("Customer profiles of the accounts were not obtained in this run.")
    for i, x in route(ans):
        f.append(leg_text(i, x))
    if ans["order"] and ans["legs"]:
        r = route(ans)
        f.append(f"The route starts at account {r[0][1]['from']} and the last payment goes to account {r[-1][1]['to']}.")
    if ans.get("context"):
        f.append("Account background (synthetic, context only): " + "; ".join(
            f"{x['account']}: {x['customer_type']}" + (f", {x['industry']}" if x["industry"] else "") + f", open {x['tenure']} days, PEP {'yes' if x['pep'] else 'no'}, risk {x['risk']}"
            for x in ans["context"]) + ".")
    e1 = byid.get("IND02191")
    if e1:
        failed = set(e1.get("failed") or [])
        ok = [RULE_TEXT[r] for r in RULE_TEXT if r not in failed and r != "legs_in_time_order"]
        bad = [RULE_TEXT[r] for r in RULE_TEXT if r in failed]
        if e1["state"] in ("held", "not_held"):
            c.append("The payments were first put in the order they happened (by time), and then checked as a chain, because the money can only have gone round in that order (a rule we added).")
            c.append("Circular pattern (IND02191), rules checked: " + "; ".join(f"{t} ({w})" for t, w in ok) + "." if ok else "Circular pattern (IND02191): no rule was met.")
            if bad:
                c.append("Rules that were not met: " + "; ".join(f"{t} ({w})" for t, w in bad) + ".")
            cyc = cycle_ignoring_time(ans["legs"])
            brk = first_break(route(ans))
            if e1["state"] == "not_held" and cyc and brk:
                f.append("Ignoring the times, these payments do form a cycle of accounts: " + " -> ".join(cyc + [cyc[0]]) + ". But in the order they happened they do not link up: "
                         f"payment {brk[0]} starts at account {brk[1]}, while the payment before it went to account {brk[2]}. So the money cannot have gone round this cycle in that order.")
        c.append(f"IND02191 ({short(names.get('IND02191', ''))}): {STATE_TEXT[e1['state']]}.")
    e5 = byid.get("IND02195")
    if e5 and e5.get("facts"):
        fa = e5["facts"]
        banks = "unknown" if fa["interbank_legs"] is None else f"{fa['interbank_legs']} of them between different banks"
        c.append(f"IND02195 (convoluted routing): the route has {fa['hops']} payments, {banks}. The typology gives no number for 'multiple hops', so this is reported as a fact, not as a verdict.")
    for e in ans["indicators"]:
        if e["state"] != "cannot_check":
            continue
        miss = ", ".join(label(t) for t in e["missing_terms"])
        src = "; ".join(x["name"] for x in (e.get("missing_sources") or []))
        c.append(f"{e['id']} ({short(names[e['id']])}): cannot be checked with this data. Missing: {miss}." + (f" Such information is held in: {src}." if src else ""))
    n.append("Whether a cycle has a legitimate business reason is not in the data; it cannot be judged from payments alone.")
    n.append("The data has no country information, so cross-border cannot be checked; a transfer between banks is not a cross-border transfer.")
    n.append("Exact amounts are not available, only a scaled value, so amounts cannot be compared in money terms.")
    if ans.get("context"):
        n.append("The customer profiles are synthetic.")
    return {"understood": u, "data_used": d, "found": f, "checked": c, "cannot_say": n}


def facts(ans, names):
    """The facts as plain text, one block per part (the model is told to write each part from its own block)."""
    sf = sections_facts(ans, names)
    return "\n\n".join(f"[{key}] {title}\n" + "\n".join(sf[key]) for key, title in SECTIONS)


def as_markdown(parts):
    return "\n\n".join(f"**{title}**  \n{parts[key].strip()}" for key, title in SECTIONS if parts.get(key))


def template(ans, names):
    """The five parts written by code from the facts (no model)."""
    sf = sections_facts(ans, names)
    return as_markdown({k: " ".join(v) for k, v in sf.items()})


def check(text, ans, names):
    basis = facts(ans, names)
    problems = []
    m = VERDICT_WORDS.search(text)
    if m:
        problems.append(f"verdict word '{m.group(0)}'")
    m = TECH_WORDS.search(text)
    if m:
        problems.append(f"technical word '{m.group(0)}'")
    problems += claims.unstated_place(text, basis)
    allowed = set(re.findall(r"\d+", basis))
    stray = sorted({n for n in re.findall(r"\d{4,}", text) if n not in allowed})
    if stray:
        problems.append(f"numbers not in the facts: {stray}")
    for sentence in claims._sentences(text):
        if re.search(r"\black(s|ed|ing)?\b[^.]*\b(rationale|justification)", sentence, re.I) and not re.search(
                r"\b(whether|not|cannot|can't|no data|unknown|unavailable|neither|nor|describes?|described|typology)\b", sentence, re.I):
            problems.append("states that the activity lacks a business rationale, which the data cannot show")
            break
    byid = {e["id"]: e for e in ans["indicators"]}
    if byid["IND02191"]["state"] == "not_held" and re.search(r"IND02191[^.]*\bmatch(es)?\b(?! the description\b.*\bnot\b)", text) and not re.search(r"(not|n't) match|does not|do not", text, re.I):
        problems.append("says IND02191 matches while the facts say it does not")
    return problems


def llm_summary(ans, names, model=llm.DEFAULT_MODEL, temperature=0.3, enforce=True):
    """enforce=True: the rules in check() decide; a report that breaks one is replaced by the template. enforce=False: the model's report is shown as it is
    (the rules are still run, and what they would have flagged comes back as `problems` with source "model"); the template is then used only when the
    model gave no usable report at all."""
    basis = facts(ans, names)
    system = ("You write a short report for a bank's financial-crime investigator, in plain business language. Use ONLY the facts given. Do not add anything that is "
              "not in them. Never say the activity is money laundering, suspicious, illicit or criminal: say only whether a structure matches a description. "
              "Never use technical words (ontology, mapping, query, SQL, schema, table, column). Say plainly which indicators cannot be checked and why. "
              "Whether an activity lacks a business rationale is NEVER known: do not say it does. Give the payments as listed, with their account ids, in the order listed. "
              "Mention account background only as context. Reply in the language of the investigator's question. Answer with one JSON object with the keys "
              + ", ".join(f'"{k}"' for k, _ in SECTIONS) + ", each a string of one to three sentences written from the block of the same name in the facts, and nothing else.")
    user = f"Investigator's question: {ans.get('question', '')}\n\nFacts:\n{basis}"
    try:
        text, secs = llm.chat(system, user, model=model, temperature=temperature, num_ctx=8192)
        d = json.loads(text)
        parts = {k: d.get(k) for k, _ in SECTIONS}
    except (llm.LLMError, json.JSONDecodeError, AttributeError) as e:
        return template(ans, names), "template", [f"model summary unavailable: {e}"], 0.0
    if not all(isinstance(v, str) and v.strip() for v in parts.values()):
        return template(ans, names), "template", ["the model did not write all five parts"], secs
    md = as_markdown(parts)
    problems = check(md, ans, names)
    if problems and not enforce:
        return md, "model", problems, secs
    if problems:
        return template(ans, names), "template", ["the model report was rejected: " + "; ".join(problems)], secs
    return md, "model", [], secs
