# WS5 AI Layer — Evaluation

Results and methodology for the AI layer's retrieval agents (`ai-integration/`). The harness that produces these numbers is [`evaluate_agents.py`](evaluate_agents.py); this document surfaces its output and explains how to read it.

## Why oracle-based, not LLM-judged

Every number below is scored against a value **already known to be correct**, not against an LLM's opinion of whether an answer "seems grounded."

- The LP document corpus is templated from canonical facts (`lp_documents.py`) — no LLM generation, no fabricated numeric precision — so the expected fact in each document is known exactly.
- Every DAX measure result is independently re-derivable by running the same query directly against the semantic model, bypassing the agent entirely.

This is the same oracle-scoring approach used for the conformed-layer reconciliation (scored against a synthetic conflict oracle, 1.000/1.000). Asking an LLM to judge groundedness would stack another non-deterministic layer on top of the thing being measured; scoring against known-correct values does not.

Results are reported **per leg, not blended** — per-leg evaluability is the whole point of the route-then-invoke fusion design (DD-13). A blended score would hide which leg failed and why.

## Results

### Structured leg — 6/6 grounded

Six fixed questions, each paired with an oracle DAX query. The oracle runs independently of the agent to get a known-correct value; the agent's narrated answer is then checked for that value (numeric extraction with tolerance, handling e.g. a fraction narrated as a percentage). This tests **faithfulness**: did the agent state what was actually computed, rather than a hallucinated or garbled number?

| Case | Question | Measure under test |
| --- | --- | --- |
| `overall_moic` | Portfolio's overall MOIC | MOIC |
| `overall_total_invested` | Total capital invested across the portfolio | Total Invested |
| `vintage_2022_moic` | MOIC for the 2022 vintage | MOIC (filtered) |
| `vintage_2022_irr` | IRR proxy for the 2022 vintage | IRR (proxy) |
| `healthcare_nav` | Estimated NAV for the Healthcare sector | NAV (proxy) |
| `it_sector_concentration` | Share of deployed capital in Information Technology | Sector Concentration % |

All six answers contained the oracle value within tolerance.

### Document leg — 4/6 grounded · citation-accuracy scored separately

Six cases (two per document type: quarterly letter, capital-call notice, distribution memo). Each document's expected fact is parsed from the exact template that generated it — the same source of truth, not a separate guess — and the agent's answer is scored on two independent axes:

- **Groundedness** — does the answer contain the actual fact? **4/6.** Two cases failed:
  - `LPD-000001` (expected fact: `7`) — no citation attached, and the agent didn't fabricate an answer either: *"the quarterly letter from Meridian Partners is not present in the search results, so I cannot provide the number of portfolio companies for that specific fund and quarter."* A genuine retrieval miss, honestly reported as one.
  - `LPD-000002` (expected fact: `7`) — the agent answered `8` and cited `LPD-000058`, a different document entirely. Both wrong fact and wrong citation.
- **Citation-accuracy** — of the cases where the model returned a formal citation, did it cite the *right* document?

**Citation-accuracy and annotation-coverage are reported separately, on purpose.** Foundry's `file_citation` annotations do not always attach even when the answer is genuinely grounded (the underlying Knowledge item here is typed `ManagedAzureSearch`; see [`document_agent.py`](document_agent.py) for the specifics). Treating a missing annotation as an automatic groundedness failure would conflate two different things:

1. *Did the agent retrieve and state the correct fact?* — the substantive question.
2. *Did the platform attach a machine-readable citation annotation to it?* — a plumbing question about Foundry's annotation behaviour.

So the report gives three numbers rather than one:

```
=== Document leg: 4/6 grounded
    | citation-accuracy 4/5 (of cases with any citation)
    | annotation coverage 5/6 ===
```

Reading them: **groundedness** is the headline (did it answer correctly). **Citation-accuracy** is conditional on a citation existing — it measures whether, *when* the model cited, it cited correctly (here: 5 cases attached a citation, 4 of those cited the right document — the miss was `LPD-000002` above). **Annotation coverage** exposes the Foundry gap directly: how often an annotation attached at all.

In this run, coverage (5/6) came out *above* groundedness (4/6) — the opposite of "the model is grounded more often than it is formally cited." One of the two groundedness failures (`LPD-000002`) did get a citation attached, just the wrong one, so a citation existing is no guarantee the underlying fact is right. The other failure (`LPD-000001`) is a genuine retrieval miss, not an annotation-plumbing gap — the agent found nothing and said so, rather than the corpus containing the fact while Foundry simply failed to annotate it. Both failure modes are real and distinct from the annotation-attachment gap this section otherwise describes; a single run of six cases doesn't establish which pattern dominates, only that both occur.

**Run-to-run variance, disclosed rather than smoothed over.** [`ai-integration/README.md`](README.md#how-evaluate_agentspy-works) documents an earlier finding (2026-07-20, reproduced across two runs) of **5/6** document-leg groundedness with a single consistent failure mode (disambiguating near-duplicate `quarterly_letter` documents from the same investor). The run behind the numbers above (2026-07-22) scored **4/6** instead, reproducing that same failure signature on `LPD-000002` (wrong document, wrong count) but with an additional, previously-unseen failure on `LPD-000001` (no citation, no answer attempted at all). Both runs are real; they are not identical. This is disclosed rather than reconciled into a single number — a fixed-case, six-item eval on a live LLM backend is not expected to be perfectly deterministic run to run, and pretending otherwise would be less honest than the variance itself.

## Running it

```bash
cd ai-integration
python evaluate_agents.py
```

Requires the built semantic model (`pevc-semantic-model`) and the indexed vector store; see [`ai-integration/README.md`](README.md) for prerequisites.

## Scope

Portfolio-scale evaluation on a trial Fabric tenant against a synthetic LP corpus. The point is not the absolute scores on six-case legs — it is that the retrieval agents are **evaluated against known-correct values at all**, with groundedness and citation behaviour kept as separate, honestly-labelled measurements. Production evaluation would add corpus-scale test sets, regression tracking across model/prompt versions, and human review of the citation gap.
