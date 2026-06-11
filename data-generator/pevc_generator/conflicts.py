"""Derive the expected-conflict ledger from projected source feeds.

This is the oracle WS2's 02_reconciliation.py is scored against: for each
canonical entity, what conflict (if any) SHOULD be detected, and of what type.

Crucially, it distinguishes the two existence causes that the headline edge
metric previously conflated:
  - existence_disagreement / genuine_dispute : company covered by BOTH sources,
    but the edge (or entity) appears in only one -> a real disagreement.
  - existence_disagreement / coverage_gap    : entity appears in one source only
    because the other source never covered the underlying company -> NOT a
    dispute, just incomplete coverage.

conflict_type stays within the reconciliation_log enum
(value_disagreement | existence_disagreement | temporal_disagreement);
the genuine/coverage distinction is carried in `existence_subtype`.
"""

from __future__ import annotations

from datetime import date

from . import reference as R

AMOUNT_TOL = R.AMOUNT_DISAGREE_TOLERANCE
DAYS_TOL = R.ANNOUNCE_DISAGREE_DAYS


def _by_canonical(mapping_rows, entity_type):
    """canonical_id -> {source: vendor_id} for an entity type."""
    out = {}
    for row in mapping_rows:
        if row["entity_type"] != entity_type:
            continue
        out.setdefault(row["canonical_id"], {})[row["source_system"]] = row["vendor_id"]
    return out


def derive_expected_conflicts(canonical: dict, feeds: dict) -> list[dict]:
    mapping = feeds["vendor_id_mapping"]
    coverage = feeds["_coverage"]
    n_sources = len(R.EXTERNAL_SOURCES)
    ledger = []

    # Index source rows by vendor id for attribute lookups
    dr_rounds = {r["vendor_round_id"]: r for r in feeds[R.SOURCE_DEALROOM]["funding_rounds"]}
    ciq_rounds = {r["vendor_round_id"]: r for r in feeds[R.SOURCE_CAPITALIQ]["funding_rounds"]}
    dr_inv = {r["vendor_investor_id"]: r for r in feeds[R.SOURCE_DEALROOM]["investors"]}
    ciq_inv = {r["vendor_investor_id"]: r for r in feeds[R.SOURCE_CAPITALIQ]["investors"]}

    # ---- Company existence ----
    comp_map = _by_canonical(mapping, "company")
    for cid, srcs in comp_map.items():
        if len(srcs) < n_sources:
            ledger.append({
                "entity_type": "company", "canonical_id": cid,
                "conflict_type": "existence_disagreement",
                "existence_subtype": "coverage_gap",
                "detail": f"covered by {sorted(srcs)} only",
            })

    # ---- Funding round value + temporal ----
    round_map = _by_canonical(mapping, "funding_round")
    for rid, srcs in round_map.items():
        if R.SOURCE_DEALROOM in srcs and R.SOURCE_CAPITALIQ in srcs:
            r1 = dr_rounds.get(srcs[R.SOURCE_DEALROOM])
            r2 = ciq_rounds.get(srcs[R.SOURCE_CAPITALIQ])
            if not r1 or not r2:
                continue
            a1, a2 = r1["amount_raised"], r2["amount_raised"]
            if max(a1, a2) > 0 and abs(a1 - a2) / max(a1, a2) > AMOUNT_TOL:
                ledger.append({
                    "entity_type": "funding_round", "canonical_id": rid,
                    "conflict_type": "value_disagreement", "existence_subtype": None,
                    "detail": f"amount_raised {a1} vs {a2}",
                })
            d1 = date.fromisoformat(r1["announced_date"])
            d2 = date.fromisoformat(r2["announced_date"])
            if abs((d1 - d2).days) > DAYS_TOL:
                ledger.append({
                    "entity_type": "funding_round", "canonical_id": rid,
                    "conflict_type": "temporal_disagreement", "existence_subtype": None,
                    "detail": f"announced {r1['announced_date']} vs {r2['announced_date']}",
                })
        else:
            # round visible to one source only -> attributable to company coverage
            ledger.append({
                "entity_type": "funding_round", "canonical_id": rid,
                "conflict_type": "existence_disagreement",
                "existence_subtype": "coverage_gap",
                "detail": f"round in {list(srcs)} only (company coverage)",
            })

    # ---- Investor value disagreement (fund_size) ----
    inv_map = _by_canonical(mapping, "investor")
    for iid, srcs in inv_map.items():
        if R.SOURCE_DEALROOM in srcs and R.SOURCE_CAPITALIQ in srcs:
            i1 = dr_inv.get(srcs[R.SOURCE_DEALROOM])
            i2 = ciq_inv.get(srcs[R.SOURCE_CAPITALIQ])
            if i1 and i2 and i1.get("fund_size") and i2.get("fund_size"):
                f1, f2 = i1["fund_size"], i2["fund_size"]
                if max(f1, f2) > 0 and abs(f1 - f2) / max(f1, f2) > AMOUNT_TOL:
                    ledger.append({
                        "entity_type": "investor", "canonical_id": iid,
                        "conflict_type": "value_disagreement", "existence_subtype": None,
                        "detail": f"fund_size {f1} vs {f2}",
                    })

    # ---- Investment edge existence (genuine vs coverage) ----
    invst_map = _by_canonical(mapping, "investment")
    # map investment canonical -> company canonical, via ground truth
    inv_company = {i["investment_id"]: i["company_id"] for i in canonical["investments"]}
    for invid, srcs in invst_map.items():
        if len(srcs) >= n_sources:
            continue  # present in both -> no existence conflict
        company = inv_company.get(invid)
        company_cov = coverage.get(company, [])
        if len(company_cov) >= n_sources:
            subtype = "genuine_dispute"   # both sources saw the company; one omitted the edge
        else:
            subtype = "coverage_gap"      # company only in one source
        ledger.append({
            "entity_type": "investment", "canonical_id": invid,
            "conflict_type": "existence_disagreement",
            "existence_subtype": subtype,
            "detail": f"edge in {list(srcs)}; company coverage {company_cov}",
        })

    return ledger
