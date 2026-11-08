# M0: which indicators can this data answer?

Draft by Claude, 2026-11-07, **not reviewed by a domain expert**. Same status as the technique-to-flag links: a first pass.
Indicator texts are from the AML typology snapshot (AMLTRIX-derived; attribution stays in the pages).

What the data has: `txs` (tx_id, ts, from_account, to_account, `amount_log`, is_cross_currency, is_self_transfer, is_same_bank, payment format)
and the synthetic `kyc_profiles` (customer_type, industry, onboarding_tenure_days, pep_flag, risk_rating).
What it does not have: country or any place, raw amount in `txs` (only a logarithm), addresses, documents, invoices, ownership,
declared profile or expected activity, branches, devices.

Marks: **yes** = answerable from the tables; **partial** = one part of the indicator is answerable, another is not (the answer must say which);
**no** = cannot be checked here (the system must say what is missing).

## T0039 Circular Transactions (9 indicators: 1 yes, 1 partial, 7 no)

| Indicator | Mark | What the data can or cannot say |
|---|---|---|
| IND02191 cycles that revert to the same origin | **yes** | closed loop of transactions, time-ordered (the scenario 3 case) |
| IND02195 convoluted routing, hops, high-risk jurisdictions | partial | hops and "between banks" (is_same_bank) yes; jurisdictions no; interbank is not cross-border |
| IND02192 intra-group transfers without documentation | no | no group structure, no documents |
| IND02193 identical VAT invoices | no | no invoices |
| IND02194 formation of entities, ownership changes | no | no entity or ownership data |
| IND02196 trade volumes vs operations | no | no declared operations |
| IND02197 circular trade in shipping and invoices | no | no shipping or invoice records |
| IND02198 establishing and dissolving entities | no | no entity data |
| IND02199 shipments with no logistics evidence | no | no logistics records |

## T0011 Money Mule Exploitation (9 indicators: 2 yes, 2 partial, 5 no; IND01115 re-marked 2026-11-08)

| Indicator | Mark | What the data can or cannot say |
|---|---|---|
| IND01115 circular patterns through related accounts | partial | loop shape yes (same as IND02191); "related accounts" (same owner or known relationship) no, the data has no relationship between accounts. Corrected 2026-11-08 from "yes" |
| IND01113 sequential transactions moving funds rapidly in and out | **yes** | an account receives, then sends on within a short window |
| IND01112 rapid outbound transfers from recently opened accounts to other institutions or crypto | **yes, with KYC** | tenure from kyc_profiles, is_same_bank = false, bitcoin format; needs the join to the account; "personal" from customer_type; what "tenure" is measured from must be checked first |
| IND01022 many small deposits below reporting thresholds | partial | many cash transactions per account yes; "small" and "below a threshold" need the raw amount, we only have a logarithm |
| IND01110 new accounts with similar addresses or nationalities | no | no addresses or nationality |
| IND01111 identical identification documents | no | no documents |
| IND01114 sudden high volume against the declared profile | no | no declared profile or expected activity |
| IND01116 source of wealth vs volumes | no | no declared source of wealth |
| IND01117 recruited via job postings | no | not in any data |

## T0083 Funnel Accounts (18 indicators: 4 yes, 7 partial, 7 no)

| Indicator | Mark | What the data can or cannot say |
|---|---|---|
| IND00944 one source, dispersed to many unrelated accounts | **yes** | fan-out after a single inflow; "unrelated" is not defined in the data; needs COUNT / GROUP BY |
| IND00523 new beneficiaries regularly added | **yes** | first-time sender/receiver pairs over time; needs NOT EXISTS |
| IND02522 beneficiaries with no prior history with the holder | **yes** | same test as above |
| IND02514 moved rapidly through a series of accounts or countries | **yes** (accounts only) | chain of accounts in a window; countries no |
| IND00521 beneficiaries in different locations | partial | number of distinct beneficiaries yes; locations no |
| IND00522 currencies not typical for the holder | partial | cross-currency or not only; no currency identity, no baseline |
| IND02512 sudden rise in international transfers | partial | rise in volume or frequency yes; "international" no (cross-currency is not international) |
| IND02521 frequent currency exchanges | partial | frequency of cross-currency transactions yes; "no business need" no |
| IND02524 sudden change in direction or volume | partial | in/out balance over time yes; "without explanation" no |
| IND02526 structured cash deposits at many branches | partial | cash format yes; branches and threshold no |
| IND02528 funnel accounts feeding one account used for trade payments | partial | fan-in yes; "trade-based" no |
| IND00943, IND00945, IND02511, IND02525 places, jurisdictions, regions | no | no place data |
| IND02516 inconsistent explanations | no | not in any data |
| IND02523 amounts structured to exploit exchange rates | no | no rates, no raw amounts |
| IND02530 accounts controlled by third parties | no | not in any data |

Totals: 36 indicators, **7 yes, 10 partial, 19 no** (IND01115 re-marked from yes to partial on 2026-11-08). Most indicators of these techniques cannot be checked on transaction and KYC tables.
That is a finding to keep on the page, not something to hide: the system's honest answer to most of the typology is "not from this data".

## Suggested choice for A to D (for the user to decide)

The alert in the demo is a money-mule flag, so the question is about **T0011** and stays inside one technique:

- A = IND01115 circular transactions (loop; same shape as IND02191, answers the loop part only; superseded by the T0039 / IND02191 start, see PLAN.md update)
- B = IND01113 rapid in-and-out (two-step, time window)
- C = IND01112 new accounts, outbound to other institutions or crypto (the KYC join, the multi-table case)
- D = IND01022 many small cash deposits, marked **partial** (shows a part answered and a part refused)
- Refused, with the reason shown: IND01110, IND01111, IND01114, IND01116, IND01117

This needs SPARQL v1 only (self-joins, filters, time arithmetic) except D, which needs a count. T0083's four "yes" indicators all
need aggregation or NOT EXISTS, so they wait for v2 and are not part of the first version.

Things to check before M1:
- What `onboarding_tenure_days` is measured from (the generator in AML Triage `data/build_kyc_profiles.py`), or "recently opened" has no meaning.
- What `amount_log` is (log or log1p of the amount), and whether a raw amount can be exposed in the `txs` view for D.
- IND01115 and IND02191 are close to the same sentence: decide whether to count them as two questions or one.

## Data check (2026-11-08): are there cases in the data?

Read-only scan of `tx_features` (self-transfers excluded; 18 days, 1 to 18 Sep 2022). Counts are exact for the definitions stated; they are not a detection result.

| Question | Count |
|---|---|
| Transactions labelled laundering (`label = 1`), self-transfers excluded | 5,166 |
| Pairs of accounts with a payment each way (any time) | 3,693 |
| Time-ordered round trips A to B to A, within 7 days | 6,452 (1,470 involve a laundering-labelled transaction) |
| Time-ordered 3-account loops A to B to C to A, within 7 days | 1,242 across 323 starting transactions |
| ...of those: all three legs labelled laundering / none labelled / mixed | 843 / 221 / 178 |
| Receive-then-send-on within 1 hour (different counterparty) | 1,965,042 pairs over 56,159 accounts; only 2,971 involve a laundering label |

What this means:
- **IND02191 / IND01115 (loops) have cases, and negatives.** 843 labelled 3-account loops are positives; the 221 loops with no laundering label are natural look-alikes, so the demo can show a loop that the shape accepts structurally but nobody labelled as laundering. Whether those are "false alarms" is for the investigator, not for us to say.
- **Real loops are longer and messier than a fixed 3-leg query.** The IBM pattern sample in AML Triage `data/HI-Small_Patterns_sample.txt` has 7 CYCLE patterns: lengths 2, 2, 3, 7, 10, 10, 10. One of them (the 7-leg one) is not in time order. So a query that searches for 3-leg loops finds about one in seven of these, and a time-ordered rule would reject a labelled one. This is why the investigator supplies transaction ids and the loop is checked, rather than searched for.
- **Round trips (2 legs) are the commonest labelled cycle.** The first SHACL draft required at least 3 legs; on 2026-11-08 that minimum was dropped (the typology gives no number), so round trips count.
- **IND01113 (rapid in-and-out) needs a tighter definition.** Two million pairs in one hour is ordinary traffic, not a signal. Without a raw amount only `amount_log` can compare sizes; a usable definition (similar amount, fixed window, minimum chain) must be chosen before this is a question worth asking.
- Not available locally: the full IBM pattern file (only the 55-attempt sample), so labelled cycles longer than 3 legs cannot be recovered from `label` alone.

