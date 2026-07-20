"""WS5 Stage E -- evaluation harness (DD-13): groundedness + citation-accuracy,
scored per leg, not blended (per-leg separation is the whole point of DD-13's
fusion-agent design -- see its rationale in docs/design_decisions.md).

**Oracle-based, not LLM-judged.** Every LP document is templated from known
canonical facts (lp_documents.py -- "no LLM calls, no fabricated numeric
precision", DD-13/DD-17), and every DAX measure result is independently
re-derivable by just running the same query ourselves. So instead of asking
an LLM to judge whether an answer "seems grounded" (subjective, another
non-deterministic layer on top of the thing being evaluated), this harness
checks agent answers against values it already knows are correct -- the same
oracle-scoring philosophy as WS2's reconciliation being scored against
`expected_conflicts` (see CLAUDE.md).

- **Structured leg**: a fixed set of (question, oracle DAX) cases. The oracle
  query runs independently of the agent -- bypassing its own tool-calling and
  LLM narration entirely -- to get a known-correct value, then the agent's
  narrated answer is checked for that value (numeric extraction + tolerance,
  handles the LLM presenting a fraction as a percentage). This tests
  faithfulness: did the agent state what was actually computed, not a
  hallucinated or garbled number.
- **Document leg**: samples real documents per `document_type` from the
  landed corpus and parses their `body_text` (regex against the exact
  templates in lp_documents.py -- same source of truth, not a separate
  guess) to get known facts and the expected `lp_document_id`. Scores
  groundedness (does the answer contain the actual fact) and
  citation-accuracy (did it cite the right document) *separately* from
  citation-annotation coverage, because file_citation annotations are known
  to not always attach even when the model's answer is genuinely grounded
  (see document_agent.py's docstring) -- treating a missing annotation as an
  automatic failure would conflate two different things.

Usage:
    python evaluate_agents.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from agent_common import AgentContext, build_context, log as _common_log
from document_agent import answer_document_full, find_vector_store_id
from structured_agent import answer_structured, run_dax_query

REPO_ROOT = Path(__file__).resolve().parent.parent
LP_DOCUMENTS_PATH = REPO_ROOT / "sample-data" / "landing" / "internal" / "lp_documents.parquet"
NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def log(msg: str) -> None:
    _common_log("evaluate_agents", msg)


def extract_numbers(text: str) -> list[float]:
    out = []
    for m in NUMBER_RE.findall(text):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            continue
    return out


def contains_value(text: str, expected: float, tolerance: float = 0.02) -> bool:
    """True if some scaled form of `expected` appears among the numbers in
    `text` within a relative tolerance. Covers the LLM presenting a fraction
    as a percentage (oracle 0.0056 -> narrated "0.56%", *100) and dollar
    figures abbreviated in prose (oracle 610732173.26 -> narrated "$610.7
    million", /1e6) -- seen in practice: a correct $610.7M answer read as a
    false failure when only the raw and *100 forms were checked."""
    found = extract_numbers(text)
    candidates = (expected, expected * 100, expected / 1e3, expected / 1e6, expected / 1e9)
    for candidate in candidates:
        for n in found:
            denom = max(abs(candidate), 1e-9)
            if abs(n - candidate) / denom <= tolerance:
                return True
    return False


# --- Structured leg -----------------------------------------------------

@dataclass
class StructuredCase:
    name: str
    question: str
    oracle_dax: str
    tolerance: float = 0.02


STRUCTURED_CASES: list[StructuredCase] = [
    StructuredCase(
        "overall_moic",
        "What's the portfolio's overall MOIC?",
        'EVALUATE ROW("v", [MOIC])',
    ),
    StructuredCase(
        "overall_total_invested",
        "How much total capital has been invested across the whole portfolio?",
        'EVALUATE ROW("v", [Total Invested])',
    ),
    StructuredCase(
        "vintage_2022_moic",
        "What's the MOIC for the 2022 vintage?",
        'EVALUATE CALCULATETABLE(ROW("v", [MOIC]), gold_dim_investor[vintage_year] = 2022)',
    ),
    StructuredCase(
        "vintage_2022_irr",
        "What's the IRR proxy for the 2022 vintage?",
        'EVALUATE CALCULATETABLE(ROW("v", [IRR (proxy)]), gold_dim_investor[vintage_year] = 2022)',
    ),
    StructuredCase(
        "healthcare_nav",
        "What's the estimated NAV for the Healthcare sector?",
        'EVALUATE CALCULATETABLE(ROW("v", [NAV (proxy)]), gold_dim_company[sector_group] = "Healthcare")',
    ),
    StructuredCase(
        "it_sector_concentration",
        "What share of deployed capital sits in the Information Technology sector?",
        'EVALUATE CALCULATETABLE(ROW("v", [Sector Concentration %]), gold_dim_company[sector_group] = "Information Technology")',
    ),
]


def run_structured_eval(ctx: AgentContext) -> list[dict[str, Any]]:
    results = []
    for case in STRUCTURED_CASES:
        oracle_rows = run_dax_query(ctx.fabric_token, ctx.workspace_id, ctx.dataset_id, case.oracle_dax)
        oracle_value = next(iter(oracle_rows[0].values()))

        try:
            answer = answer_structured(ctx.openai_client, ctx.deployment, ctx.fabric_token, ctx.workspace_id,
                                        ctx.dataset_id, case.question)
            grounded = contains_value(answer, oracle_value, case.tolerance)
        except Exception as e:
            answer = f"(agent raised: {e})"
            grounded = False

        results.append({
            "case": case.name, "question": case.question, "oracle_value": oracle_value,
            "answer": answer, "grounded": grounded,
        })
        log(f"[{'PASS' if grounded else 'FAIL'}] {case.name}: oracle={oracle_value!r}")
    return results


# --- Document leg --------------------------------------------------------

@dataclass
class DocumentCase:
    lp_document_id: str
    question: str
    expected_fact_text: str
    expected_value: float | None = None


DOCUMENT_TEMPLATE_PATTERNS = {
    "quarterly_letter": re.compile(
        r"Quarterly letter -- (?P<investor>.+?), quarter ended (?P<date>\d{4}-\d{2}-\d{2})\. "
        r"The fund's portfolio spans (?P<count>\d+) companies\."
    ),
    "capital_call_notice": re.compile(
        r"Capital call notice -- (?P<investor>.+?) calls (?P<amount>[\d,]+\.\d{2}) (?P<currency>\w+) "
        r"for its participation in (?P<company>.+?)'s (?P<round_type>.+?) round, closing (?P<date>\d{4}-\d{2}-\d{2})\."
    ),
    "memo": re.compile(
        r"Memo -- (?P<investor>.+?) realised its position in (?P<company>.+?) via (?P<exit_type>.+?), "
        r"effective (?P<date>\d{4}-\d{2}-\d{2}), returning (?P<multiple>[\d.]+)x cost\."
    ),
}

DOC_CASES_PER_TYPE = 2


def build_document_cases() -> list[DocumentCase]:
    """Samples real documents from the landed corpus (the same one indexed
    into the vector store by index_corpus.py) and parses their body_text
    against the exact templates in lp_documents.py -- so the "expected" facts
    here are read from the real corpus, not a hardcoded guess that could
    drift if the corpus is regenerated at a different seed/scale."""
    docs = pd.read_parquet(LP_DOCUMENTS_PATH)
    cases: list[DocumentCase] = []

    for dtype, pattern in DOCUMENT_TEMPLATE_PATTERNS.items():
        subset = docs[docs["document_type"] == dtype]
        if dtype == "memo":
            subset = subset[~subset["body_text"].str.contains("undisclosed")]
        sampled = subset.head(DOC_CASES_PER_TYPE)

        for _, row in sampled.iterrows():
            m = pattern.match(row["body_text"])
            if not m:
                continue
            g = m.groupdict()
            if dtype == "quarterly_letter":
                question = (f"According to the quarterly letter from {g['investor']} for the quarter ended "
                            f"{g['date']}, how many portfolio companies did the fund report?")
                cases.append(DocumentCase(row["lp_document_id"], question, g["count"], float(g["count"])))
            elif dtype == "capital_call_notice":
                question = (f"What amount did {g['investor']} call for its participation in {g['company']}'s "
                            f"{g['round_type']} round around {g['date']}?")
                cases.append(DocumentCase(row["lp_document_id"], question, g["amount"],
                                           float(g["amount"].replace(",", ""))))
            elif dtype == "memo":
                question = (f"What multiple did {g['investor']} realise on its exit from {g['company']} "
                            f"via {g['exit_type']}, effective {g['date']}?")
                cases.append(DocumentCase(row["lp_document_id"], question, f"{g['multiple']}x", float(g["multiple"])))

    return cases


def run_document_eval(ctx: AgentContext) -> list[dict[str, Any]]:
    vector_store_id = find_vector_store_id(ctx.openai_client, ctx.vector_store_name)
    cases = build_document_cases()
    results = []

    for case in cases:
        try:
            result = answer_document_full(ctx.openai_client, ctx.deployment, vector_store_id, case.question)
            answer, cited_ids = result.text, result.cited_lp_document_ids
        except Exception as e:
            answer, cited_ids = f"(agent raised: {e})", set()

        grounded = (
            case.expected_value is not None and contains_value(answer, case.expected_value, tolerance=0.005)
        ) or case.expected_fact_text.lower() in answer.lower()
        any_citation = len(cited_ids) > 0
        cited_correctly = (case.lp_document_id in cited_ids) if any_citation else None

        results.append({
            "case": case.lp_document_id, "question": case.question, "expected_fact": case.expected_fact_text,
            "answer": answer, "grounded": grounded, "any_citation": any_citation, "cited_correctly": cited_correctly,
        })
        status = "PASS" if grounded else "FAIL"
        cite_note = "no citation" if not any_citation else ("cited correctly" if cited_correctly else "cited WRONG doc")
        log(f"[{status}] {case.lp_document_id}: fact={case.expected_fact_text!r} ({cite_note})")
    return results


# --- Report ---------------------------------------------------------------

def print_report(structured_results: list[dict], document_results: list[dict]) -> None:
    s_pass = sum(r["grounded"] for r in structured_results)
    print(f"\n=== Structured leg: {s_pass}/{len(structured_results)} grounded ===")
    for r in structured_results:
        mark = "PASS" if r["grounded"] else "FAIL"
        print(f"  [{mark}] {r['case']}: oracle={r['oracle_value']!r}")
        if not r["grounded"]:
            print(f"         answer: {r['answer']!r}")

    d_pass = sum(r["grounded"] for r in document_results)
    d_with_citation = [r for r in document_results if r["any_citation"]]
    d_cited_correctly = sum(r["cited_correctly"] for r in d_with_citation)
    print(f"\n=== Document leg: {d_pass}/{len(document_results)} grounded "
          f"| citation-accuracy {d_cited_correctly}/{len(d_with_citation)} (of cases with any citation) "
          f"| annotation coverage {len(d_with_citation)}/{len(document_results)} ===")
    for r in document_results:
        mark = "PASS" if r["grounded"] else "FAIL"
        cite = "no citation" if not r["any_citation"] else ("correct" if r["cited_correctly"] else "WRONG doc")
        print(f"  [{mark}] {r['case']}: fact={r['expected_fact']!r}, citation={cite}")
        if not r["grounded"]:
            print(f"         answer: {r['answer']!r}")


def main() -> int:
    try:
        ctx = build_context()
    except RuntimeError as e:
        log(str(e))
        return 1

    log("Running structured-leg eval...")
    structured_results = run_structured_eval(ctx)

    log("Running document-leg eval...")
    document_results = run_document_eval(ctx)

    print_report(structured_results, document_results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
