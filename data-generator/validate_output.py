"""Validate v2 output: integrity, coverage, and emergent conflict rates.

Reconciliation logic itself lives in WS2 (02_reconciliation.py). This script
only confirms the generator produced internally consistent feeds and that the
three conflict types occur at meaningful, measurable rates.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pevc_generator import reference as R
from pevc_generator.io_utils import read_table

DATA = (Path(__file__).resolve().parent.parent / "sample-data")
LANDING = DATA / "landing"
REF = DATA / "reference"


def load(src, entity):
    return read_table(LANDING / src / entity)


def loadref(name):
    return read_table(REF / name)


def jloads(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return json.loads(v) if isinstance(v, str) else v


print("=" * 72)
print("REFERENTIAL INTEGRITY (via vendor_id_mapping)")
print("=" * 72)

mapping = loadref("vendor_id_mapping")
# canonical id sets from ground truth
gt_co = set(loadref("ground_truth_companies")["company_id"])
gt_rd = set(loadref("ground_truth_funding_rounds")["round_id"])
gt_iv = set(loadref("ground_truth_investors")["investor_id"])
gt_inv = set(loadref("ground_truth_investments")["investment_id"])

map_co = set(mapping[mapping.entity_type == "company"]["canonical_id"])
map_rd = set(mapping[mapping.entity_type == "funding_round"]["canonical_id"])
map_iv = set(mapping[mapping.entity_type == "investor"]["canonical_id"])
map_inv = set(mapping[mapping.entity_type == "investment"]["canonical_id"])

assert map_co <= gt_co, "mapping has companies not in ground truth"
assert map_rd <= gt_rd, "mapping has rounds not in ground truth"
assert map_iv <= gt_iv, "mapping has investors not in ground truth"
assert map_inv <= gt_inv, "mapping has investments not in ground truth"
print("PASS: all vendor mappings resolve to ground-truth canonical IDs")

# every vendor id in a source feed must exist in mapping
for src in R.EXTERNAL_SOURCES:
    co = load(src, "companies")
    msrc = set(mapping[(mapping.source_system == src) & (mapping.entity_type == "company")]["vendor_id"])
    assert set(co["vendor_company_id"]) <= msrc, f"{src} company vendor ids missing from mapping"
print("PASS: source vendor IDs all present in vendor_id_mapping")

# rounds reference companies within same source
for src in R.EXTERNAL_SOURCES:
    co = set(load(src, "companies")["vendor_company_id"])
    rd = load(src, "funding_rounds")
    assert set(rd["vendor_company_id"]) <= co, f"{src} rounds reference unknown company vendor id"
print("PASS: funding_rounds reference in-source companies")

# lineage columns
for src in R.EXTERNAL_SOURCES:
    for e in ("companies", "funding_rounds", "investors", "investments"):
        df = load(src, e)
        miss = [c for c in R.SOURCE_PROFILES and [] for c in []]  # noop
        for c in ["_record_id", "_source_system", "_batch_id", "_is_synthetic"]:
            assert c in df.columns, f"{src}/{e} missing {c}"
        assert (df["_source_system"] == src).all()
print("PASS: landing lineage columns present and source-stamped")

print()
print("=" * 72)
print("COVERAGE")
print("=" * 72)
n_canonical = len(gt_co)
dr = set(mapping[(mapping.source_system == "dealroom") & (mapping.entity_type == "company")]["canonical_id"])
ciq = set(mapping[(mapping.source_system == "capitaliq") & (mapping.entity_type == "company")]["canonical_id"])
both = dr & ciq
dr_only = dr - ciq
ciq_only = ciq - dr
union = dr | ciq
print(f"Canonical companies: {n_canonical}")
print(f"  dealroom covers : {len(dr)}  ({len(dr)/n_canonical:.0%})")
print(f"  capitaliq covers: {len(ciq)} ({len(ciq)/n_canonical:.0%})")
print(f"  both            : {len(both)} ({len(both)/n_canonical:.0%})")
print(f"  dealroom-only   : {len(dr_only)} ({len(dr_only)/n_canonical:.0%})  <- existence_disagreement")
print(f"  capitaliq-only  : {len(ciq_only)} ({len(ciq_only)/n_canonical:.0%}) <- existence_disagreement")
print(f"  union           : {len(union)} ({len(union)/n_canonical:.0%})")

print()
print("=" * 72)
print("CONFLICT RATES (rounds present in BOTH sources)")
print("=" * 72)

# Build canonical-round -> per-source view via mapping
mr = mapping[mapping.entity_type == "funding_round"]
dr_rmap = dict(zip(mr[mr.source_system == "dealroom"]["vendor_id"], mr[mr.source_system == "dealroom"]["canonical_id"]))
ciq_rmap = dict(zip(mr[mr.source_system == "capitaliq"]["vendor_id"], mr[mr.source_system == "capitaliq"]["canonical_id"]))

dr_rounds = load("dealroom", "funding_rounds").copy()
ciq_rounds = load("capitaliq", "funding_rounds").copy()
dr_rounds["canon"] = dr_rounds["vendor_round_id"].map(dr_rmap)
ciq_rounds["canon"] = ciq_rounds["vendor_round_id"].map(ciq_rmap)

merged = dr_rounds.merge(ciq_rounds, on="canon", suffixes=("_dr", "_ciq"))
n_both = len(merged)

# value disagreement on amount_raised
rel = (merged["amount_raised_dr"] - merged["amount_raised_ciq"]).abs() / \
      merged[["amount_raised_dr", "amount_raised_ciq"]].max(axis=1)
value_dis = (rel > R.AMOUNT_DISAGREE_TOLERANCE).sum()

# temporal disagreement on announced_date
d_dr = pd.to_datetime(merged["announced_date_dr"])
d_ciq = pd.to_datetime(merged["announced_date_ciq"])
temporal_dis = ((d_dr - d_ciq).abs().dt.days > R.ANNOUNCE_DISAGREE_DAYS).sum()

print(f"Rounds in both sources: {n_both}")
print(f"  value_disagreement (amount >5% apart): {value_dis} ({value_dis/n_both:.0%})")
print(f"  temporal_disagreement (>30 days apart): {temporal_dis} ({temporal_dis/n_both:.0%})")

# investment edge existence disagreement
mi = mapping[mapping.entity_type == "investment"]
dr_inv = set(mi[mi.source_system == "dealroom"]["canonical_id"])
ciq_inv = set(mi[mi.source_system == "capitaliq"]["canonical_id"])
edge_union = dr_inv | ciq_inv
edge_both = dr_inv & ciq_inv
edge_dis = len(edge_union) - len(edge_both)
print(f"\nInvestment edges union: {len(edge_union)}")
print(f"  in both sources     : {len(edge_both)} ({len(edge_both)/len(edge_union):.0%})")
print(f"  existence_disagreement: {edge_dis} ({edge_dis/len(edge_union):.0%})")

print()
print("=" * 72)
print("VERDICT")
print("=" * 72)
checks = {
    "existence (company-level)": len(dr_only) + len(ciq_only) > 0,
    "value (amount)": value_dis > 0,
    "temporal (announced)": temporal_dis > 0,
    "existence (investment edges)": edge_dis > 0,
}
for k, v in checks.items():
    print(f"  {'PASS' if v else 'FAIL'}: {k} conflicts present")
print()
total = sum(p.stat().st_size for p in DATA.rglob("*.csv")) + sum(p.stat().st_size for p in DATA.rglob("*.parquet"))
print(f"Total sample size: {total/1024/1024:.2f} MB")
print("All conflict types present — WS2 02_reconciliation will have real work to do." if all(checks.values())
      else "WARNING: some conflict types absent — tune SOURCE_PROFILES.")
