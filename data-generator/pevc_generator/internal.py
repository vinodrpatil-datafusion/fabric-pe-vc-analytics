"""Internal feed: deal pipeline (data_model 1.6) and documents (1.7).

Single-source (the firm's own data). No multi-source conflict — internal
pipeline is forward-only; documents are immutable artefacts.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from . import reference as R
from .canonical import TODAY, _rand_date, _weighted


def generate_internal(canonical: dict, profile, rng: np.random.Generator) -> dict:
    companies = canonical["companies"]
    rounds = canonical["funding_rounds"]
    people = canonical["people"]

    company_ids = [c["company_id"] for c in companies]
    rounds_by_company = {}
    for rd in rounds:
        rounds_by_company.setdefault(rd["company_id"], []).append(rd["round_id"])
    person_ids = [p["person_id"] for p in people]

    deals = _gen_deals(profile, company_ids, rounds_by_company, rng)
    documents = _gen_documents(profile, company_ids, deals, person_ids, rng)
    return {"deals": deals, "documents": documents}


def _gen_deals(profile, company_ids, rounds_by_company, rng) -> list[dict]:
    out = []
    targets = list(rng.choice(company_ids, size=min(profile.n_internal_deals, len(company_ids)), replace=False))
    for i, cid in enumerate(targets, start=1):
        # stage with a forward-only history
        terminal = _weighted(rng, R.DEAL_STAGES,
                             [0.12, 0.15, 0.18, 0.12, 0.05, 0.10, 0.13, 0.15])
        order = ["sourcing", "screening", "due_diligence", "ic_review", "closing", "closed_won"]
        if terminal in order:
            path = order[: order.index(terminal) + 1]
        elif terminal == "closed_lost":
            path = ["sourcing", "screening", "due_diligence", "ic_review", "closed_lost"]
        else:  # passed
            cut = int(rng.integers(1, 4))
            path = ["sourcing", "screening", "due_diligence"][:cut] + ["passed"]

        start = _rand_date(rng, date(2024, 1, 1), date(2026, 3, 1))
        stage_history = []
        t = start
        for stg in path:
            stage_history.append({"stage": stg, "at": t.isoformat()})
            t = t + timedelta(days=int(rng.integers(7, 60)))

        ic_reached = "ic_review" in path or terminal in ("closing", "closed_won", "closed_lost")
        ic_outcome = None
        ic_dt = None
        if ic_reached:
            ic_dt = _rand_date(rng, start + timedelta(days=30), TODAY).isoformat()
            ic_outcome = _weighted(rng, R.IC_OUTCOMES, [0.5, 0.3, 0.2])

        target_round = None
        if cid in rounds_by_company and rng.random() < 0.5:
            target_round = str(rng.choice(rounds_by_company[cid]))

        out.append({
            "deal_id": f"D-{i:05d}",
            "company_id": cid,
            "stage": terminal,
            "stage_history": stage_history,
            "analyst_owner": f"analyst_{int(rng.integers(1, 9))}",
            "partner_owner": f"partner_{int(rng.integers(1, 5))}",
            "proposed_check_size": round(float(rng.lognormal(2.0, 0.8)), 2),
            "target_round_id": target_round,
            "ic_date": ic_dt,
            "ic_outcome": ic_outcome,
        })
    return out


_DOC_TEXT_TEMPLATES = {
    "ic_memo": "Investment committee memo assessing {co}. Thesis centres on market position and team. Recommended: proceed to diligence.",
    "dd_report": "Due diligence findings for {co}. Financials reviewed; customer references positive; key risk is concentration.",
    "news_article": "{co} announced new funding and expansion plans, citing strong demand in its core market.",
    "transcript": "Call transcript with {co} leadership covering roadmap, hiring plans, and competitive dynamics.",
    "vendor_report": "Third-party market report referencing {co} among notable players in its category.",
    "analyst_note": "Internal analyst note on {co}: monitoring traction metrics ahead of the next round.",
}


def _gen_documents(profile, company_ids, deals, person_ids, rng) -> list[dict]:
    out = []
    deal_ids = [d["deal_id"] for d in deals]
    deal_company = {d["deal_id"]: d["company_id"] for d in deals}
    for i in range(1, profile.n_documents + 1):
        dtype = _weighted(rng, R.DOCUMENT_TYPES, R.DOCUMENT_TYPE_WEIGHTS)
        subj_companies = [str(rng.choice(company_ids))]
        subj_deals = []
        if dtype in ("ic_memo", "dd_report", "analyst_note") and deal_ids:
            d = str(rng.choice(deal_ids))
            subj_deals = [d]
            subj_companies = [deal_company[d]]
        author = str(rng.choice(person_ids)) if dtype in ("ic_memo", "dd_report", "analyst_note") else None
        sens = {
            "ic_memo": "Highly Confidential", "dd_report": "Confidential",
            "analyst_note": "Confidential", "transcript": "Confidential",
            "vendor_report": "Internal", "news_article": "Public",
        }[dtype]
        out.append({
            "document_id": f"DOC-{i:05d}",
            "document_type": dtype,
            "subject_company_ids": subj_companies,
            "subject_deal_ids": subj_deals,
            "author_person_id": author,
            "created_date": _rand_date(rng, date(2023, 1, 1), TODAY).isoformat(),
            "storage_location": f"abfss://landing@onelake/documents/{dtype}/DOC-{i:05d}.txt",
            "extracted_text": _DOC_TEXT_TEMPLATES[dtype].format(co=subj_companies[0]),
            "embedding_index_id": None,
            "sensitivity_label": sens,
        })
    return out
