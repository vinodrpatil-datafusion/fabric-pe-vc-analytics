"""LP document corpus: fund-to-LP communications (DD-17).

Generates the synthetic document universe WS5's Foundry IQ leg indexes:
quarterly letters, capital call notices, and exit-notice memos. Kept separate
from internal.py's `documents` entity -- different purpose (fund-to-LP
communications, not deal-pipeline records) and a different sensitivity
profile.

Every document is templated from canonical ground truth already generated in
canonical.py -- no LLM calls, no fabricated numeric precision (DD-13/DD-17;
same discipline DD-16 applies to the IRR proxy). All three document types are
scoped to fund-type investors only (`vintage_year` populated) -- angels,
accelerators, and strategics don't raise from LPs, so it wouldn't make sense
for them to issue capital calls or LP letters.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from .canonical import TODAY

# Trailing window per fund -- keeps corpus size bounded regardless of vintage age.
MAX_LETTER_QUARTERS = 8


def _quarter_end_dates(today: date, not_before_year: int, max_n: int) -> list[date]:
    """Most recent `max_n` quarter-end dates on/before `today`, not before Jan 1 of `not_before_year`."""
    month_end = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    q = (today.month - 1) // 3 + 1
    y = today.year
    out: list[date] = []
    while len(out) < max_n and y >= not_before_year:
        m, d = month_end[q]
        cand = date(y, m, d)
        if cand <= today:
            out.append(cand)
        q -= 1
        if q < 1:
            q = 4
            y -= 1
    return list(reversed(out))


def generate_lp_documents(canonical: dict, rng: np.random.Generator) -> dict:
    companies = {c["company_id"]: c for c in canonical["companies"]}
    investors = {iv["investor_id"]: iv for iv in canonical["investors"]}
    rounds = {r["round_id"]: r for r in canonical["funding_rounds"]}
    investments = canonical["investments"]

    by_investor: dict[str, list[dict]] = {}
    for inv in investments:
        by_investor.setdefault(inv["investor_id"], []).append(inv)

    documents: list[dict] = []
    manifest: list[dict] = []
    doc_idx = 1

    def add_doc(document_type, investor_id, effective_date, body_text, refs):
        nonlocal doc_idx
        doc_id = f"LPD-{doc_idx:06d}"
        documents.append({
            "lp_document_id": doc_id,
            "document_type": document_type,
            "investor_id": investor_id,
            "effective_date": effective_date.isoformat(),
            "body_text": body_text,
        })
        for etype, eid in refs:
            manifest.append({"lp_document_id": doc_id, "entity_type": etype, "entity_id": eid})
        doc_idx += 1

    # --- quarterly letters: one per fund per trailing quarter since vintage ---
    for iv in investors.values():
        if iv.get("vintage_year") is None:
            continue
        held_company_ids = sorted({h["company_id"] for h in by_investor.get(iv["investor_id"], [])})
        if not held_company_ids:
            continue
        for qend in _quarter_end_dates(TODAY, iv["vintage_year"], MAX_LETTER_QUARTERS):
            n_highlight = min(len(held_company_ids), int(rng.integers(2, 5)))
            highlighted = sorted(rng.choice(held_company_ids, size=n_highlight, replace=False))
            names = [companies[cid]["legal_name"] for cid in highlighted]
            body = (
                f"Quarterly letter -- {iv['legal_name']}, quarter ended {qend.isoformat()}. "
                f"The fund's portfolio spans {len(held_company_ids)} companies. "
                f"This quarter's highlights include {', '.join(names)}. "
                f"Full holdings detail is available on request."
            )
            refs = [("investor", iv["investor_id"])] + [("company", cid) for cid in highlighted]
            add_doc("quarterly_letter", iv["investor_id"], qend, body, refs)

    # --- capital call notices: one per fund investment participation ---
    for inv in investments:
        iv = investors.get(inv["investor_id"])
        rd = rounds.get(inv["round_id"])
        co = companies.get(inv["company_id"])
        if iv is None or iv.get("vintage_year") is None or rd is None or co is None:
            continue
        eff = date.fromisoformat(inv["effective_date"])
        body = (
            f"Capital call notice -- {iv['legal_name']} calls "
            f"{inv['participation_amount']:,.2f} {rd['currency']} "
            f"for its participation in {co['legal_name']}'s {rd['round_type']} round, "
            f"closing {eff.isoformat()}."
        )
        refs = [("investor", inv["investor_id"]), ("round", inv["round_id"]), ("company", inv["company_id"])]
        add_doc("capital_call_notice", inv["investor_id"], eff, body, refs)

    # --- memos: exit notices, one per realised fund investment ---
    for inv in investments:
        if not inv.get("exit_date"):
            continue
        iv = investors.get(inv["investor_id"])
        co = companies.get(inv["company_id"])
        if iv is None or iv.get("vintage_year") is None or co is None:
            continue
        exit_dt = date.fromisoformat(inv["exit_date"])
        mult = inv.get("realised_return_multiple")
        mult_txt = f"{mult:.2f}x cost" if mult is not None else "an undisclosed multiple"
        body = (
            f"Memo -- {iv['legal_name']} realised its position in {co['legal_name']} "
            f"via {inv['exit_type']}, effective {exit_dt.isoformat()}, returning {mult_txt}."
        )
        refs = [("investor", inv["investor_id"]), ("company", inv["company_id"]), ("round", inv["round_id"])]
        add_doc("memo", inv["investor_id"], exit_dt, body, refs)

    return {"lp_documents": documents, "lp_document_manifest": manifest}
