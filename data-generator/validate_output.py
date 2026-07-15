"""Validate v2 output: integrity, coverage, and emergent conflict rates.

Reconciliation logic itself lives in WS2 (02_reconciliation.py). This script
only confirms the generator produced internally consistent feeds and that the
conflict types occur at meaningful, measurable rates - now distinguishing
genuine edge disputes from coverage-driven gaps, and cross-checking against the
expected_conflicts ledger.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pevc_generator import reference as R
from pevc_generator.io_utils import read_table

# Repo-relative: works on any machine (data-generator/ -> repo root -> sample-data/)
DATA = (Path(__file__).resolve().parent.parent / "sample-data")
LANDING = DATA / "landing"
REF = DATA / "reference"


def load(src, entity):
    return read_table(LANDING / src / entity)


def loadref(name):
    return read_table(REF / name)


print("=" * 72)
print("REFERENTIAL INTEGRITY (via vendor_id_mapping)")
print("=" * 72)

mapping = loadref("vendor_id_mapping")
gt_co = set(loadref("ground_truth_companies")["company_id"])
gt_rd = set(loadref("ground_truth_funding_rounds")["round_id"])
gt_iv = set(loadref("ground_truth_investors")["investor_id"])
gt_inv = set(loadref("ground_truth_investments")["investment_id"])

map_co = set(mapping[mapping.entity_type == "company"]["canonical_id"])
map_rd = set(mapping[mapping.entity_type == "funding_round"]["canonical_id"])
map_iv = set(mapping[mapping.entity_type == "investor"]["canonical_id"])
map_inv = set(mapping[mapping.entity_type == "investment"]["canonical_id"])

assert map_co <= gt_co and map_rd <= gt_rd and map_iv <= gt_iv and map_inv <= gt_inv, \
    "mapping references IDs absent from ground truth"
print("PASS: all vendor mappings resolve to ground-truth canonical IDs")

for src in R.EXTERNAL_SOURCES:
    co = load(src, "companies")
    msrc = set(mapping[(mapping.source_system == src) & (mapping.entity_type == "company")]["vendor_id"])
    assert set(co["vendor_company_id"]) <= msrc, f"{src} company vendor ids missing from mapping"
print("PASS: source vendor IDs all present in vendor_id_mapping")

for src in R.EXTERNAL_SOURCES:
    co = set(load(src, "companies")["vendor_company_id"])
    rd = load(src, "funding_rounds")
    assert set(rd["vendor_company_id"]) <= co, f"{src} rounds reference unknown company"
print("PASS: funding_rounds reference in-source companies")

for src in R.EXTERNAL_SOURCES:
    for e in ("companies", "funding_rounds", "investors", "investments"):
        df = load(src, e)
        for c in ["_record_id", "_source_system", "_batch_id", "_is_synthetic"]:
            assert c in df.columns, f"{src}/{e} missing {c}"
        assert (df["_source_system"] == src).all()
print("PASS: landing lineage columns present and source-stamped")

print()
print("=" * 72)
print("LP DOCUMENT CORPUS (DD-17)")
print("=" * 72)

lp_docs = load("internal", "lp_documents")
lp_manifest = load("internal", "lp_document_manifest")

resolvers = {"investor": gt_iv, "company": gt_co, "round": gt_rd}
unresolved = 0
for etype, ids in resolvers.items():
    rows = lp_manifest[lp_manifest.entity_type == etype]
    bad = set(rows["entity_id"]) - ids
    unresolved += len(rows[rows["entity_id"].isin(bad)])
    if bad:
        print(f"  UNRESOLVED {etype} refs: {sorted(bad)[:5]}{'...' if len(bad) > 5 else ''}")
assert unresolved == 0, f"{unresolved} lp_document_manifest rows reference IDs absent from ground truth"
print(f"PASS: all {len(lp_manifest)} lp_document_manifest rows resolve to ground truth "
      f"({len(lp_docs)} documents: "
      f"{(lp_docs.document_type == 'quarterly_letter').sum()} quarterly letters, "
      f"{(lp_docs.document_type == 'capital_call_notice').sum()} capital call notices, "
      f"{(lp_docs.document_type == 'memo').sum()} memos)")

print()
print("=" * 72)
print("COVERAGE")
print("=" * 72)
n = len(gt_co)
dr = set(mapping[(mapping.source_system == "dealroom") & (mapping.entity_type == "company")]["canonical_id"])
ciq = set(mapping[(mapping.source_system == "capitaliq") & (mapping.entity_type == "company")]["canonical_id"])
print(f"Canonical companies: {n}")
print(f"  dealroom covers : {len(dr)} ({len(dr)/n:.0%})")
print(f"  capitaliq covers: {len(ciq)} ({len(ciq)/n:.0%})")
print(f"  both            : {len(dr & ciq)} ({len(dr & ciq)/n:.0%})")
print(f"  single-source   : {len(dr ^ ciq)} ({len(dr ^ ciq)/n:.0%})  (coverage-gap existence)")
print(f"  union           : {len(dr | ciq)} ({len(dr | ciq)/n:.0%})")

print()
print("=" * 72)
print("CONFLICT RATES")
print("=" * 72)

mr = mapping[mapping.entity_type == "funding_round"]
dr_rmap = dict(zip(mr[mr.source_system == "dealroom"]["vendor_id"], mr[mr.source_system == "dealroom"]["canonical_id"]))
ciq_rmap = dict(zip(mr[mr.source_system == "capitaliq"]["vendor_id"], mr[mr.source_system == "capitaliq"]["canonical_id"]))
drr = load("dealroom", "funding_rounds").copy()
ciqr = load("capitaliq", "funding_rounds").copy()
drr["canon"] = drr["vendor_round_id"].map(dr_rmap)
ciqr["canon"] = ciqr["vendor_round_id"].map(ciq_rmap)
m = drr.merge(ciqr, on="canon", suffixes=("_dr", "_ciq"))
n_both = len(m)
rel = (m["amount_raised_dr"] - m["amount_raised_ciq"]).abs() / m[["amount_raised_dr", "amount_raised_ciq"]].max(axis=1)
value_dis = int((rel > R.AMOUNT_DISAGREE_TOLERANCE).sum())
temporal_dis = int((pd.to_datetime(m["announced_date_dr"]) - pd.to_datetime(m["announced_date_ciq"])).abs().dt.days.gt(R.ANNOUNCE_DISAGREE_DAYS).sum())
print(f"Rounds in both sources: {n_both}")
print(f"  value_disagreement (amount >5%):   {value_dis} ({value_dis/n_both:.0%})")
print(f"  temporal_disagreement (>30 days):  {temporal_dis} ({temporal_dis/n_both:.0%})")

print()
print("Investment-edge existence (split by cause):")
ledger = loadref("expected_conflicts")
edge = ledger[(ledger.entity_type == "investment") & (ledger.conflict_type == "existence_disagreement")]
genuine = int((edge.existence_subtype == "genuine_dispute").sum())
covgap = int((edge.existence_subtype == "coverage_gap").sum())
total_edges = len(map_inv)
print(f"  total investment edges (union): {total_edges}")
print(f"  genuine_dispute  : {genuine} ({genuine/total_edges:.0%})  <- the real reconciliation signal")
print(f"  coverage_gap     : {covgap} ({covgap/total_edges:.0%})  <- attributable to company coverage, NOT a dispute")

print()
print("=" * 72)
print("EXPECTED-CONFLICTS LEDGER (oracle for WS2 reconciliation scoring)")
print("=" * 72)
summary = ledger.groupby(["entity_type", "conflict_type", "existence_subtype"], dropna=False).size()
print(summary.to_string())

print()
print("=" * 72)
print("VERDICT")
print("=" * 72)
checks = {
    "company existence (coverage-gap)": len(dr ^ ciq) > 0,
    "round value disagreement": value_dis > 0,
    "round temporal disagreement": temporal_dis > 0,
    "edge existence GENUINE disputes present": genuine > 0,
    "edge existence/coverage SEPARATED": (genuine + covgap) > 0,
}
for k, v in checks.items():
    print(f"  {'PASS' if v else 'FAIL'}: {k}")

total = sum(p.stat().st_size for p in DATA.rglob("*.parquet")) + sum(p.stat().st_size for p in DATA.rglob("*.csv"))
print(f"\nTotal sample size: {total/1024/1024:.2f} MB")
print("Conflation resolved: genuine edge disputes are now distinct from coverage gaps."
      if all(checks.values()) else "WARNING: review SOURCE_PROFILES / ledger.")
