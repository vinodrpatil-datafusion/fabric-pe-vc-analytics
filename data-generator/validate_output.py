"""Post-generation validation. Not a DQ suite (that's Silver layer's job)
— just a sanity check that the generator produced internally consistent data
and distributions look PE-realistic.
"""

from pathlib import Path
import pandas as pd

DATA = Path("/home/claude/fabric-pe-vc-analytics/sample-data")

funds = pd.read_parquet(DATA / "funds.parquet")
lps = pd.read_parquet(DATA / "limited_partners.parquet")
commits = pd.read_parquet(DATA / "lp_commitments.parquet")
cos = pd.read_parquet(DATA / "portfolio_companies.parquet")
deals = pd.read_parquet(DATA / "deals.parquet")
vals = pd.read_parquet(DATA / "valuations.parquet")
cfs = pd.read_parquet(DATA / "cashflows.parquet")

print("=" * 70)
print("REFERENTIAL INTEGRITY")
print("=" * 70)

assert commits["fund_id"].isin(funds["fund_id"]).all(), "commits → funds FK broken"
assert commits["lp_id"].isin(lps["lp_id"]).all(), "commits → lps FK broken"
assert cos["fund_id"].isin(funds["fund_id"]).all(), "companies → funds FK broken"
assert deals["fund_id"].isin(funds["fund_id"]).all(), "deals → funds FK broken"
assert deals["company_id"].isin(cos["company_id"]).all(), "deals → companies FK broken"
assert vals["fund_id"].isin(funds["fund_id"]).all(), "vals → funds FK broken"
assert vals["company_id"].isin(cos["company_id"]).all(), "vals → companies FK broken"
assert cfs["fund_id"].isin(funds["fund_id"]).all(), "cfs → funds FK broken"
assert cfs["company_id"].isin(cos["company_id"]).all(), "cfs → companies FK broken"
print("PASS: all foreign keys resolve")

# Lineage columns on every entity
LINEAGE = ["_record_id", "_source_system", "_source_file", "_ingestion_ts",
           "_batch_id", "_data_version", "_is_synthetic"]
for name, df in [("funds", funds), ("lps", lps), ("commits", commits),
                 ("cos", cos), ("deals", deals), ("vals", vals), ("cfs", cfs)]:
    missing = [c for c in LINEAGE if c not in df.columns]
    assert not missing, f"{name} missing lineage cols: {missing}"
print("PASS: lineage columns present on all entities")

# Unique batch_id (one run = one batch across all entities)
batch_ids = set()
for df in [funds, lps, commits, cos, deals, vals, cfs]:
    batch_ids.update(df["_batch_id"].unique())
assert len(batch_ids) == 1, f"expected single batch_id, got {len(batch_ids)}"
print(f"PASS: single batch_id across all entities: {batch_ids.pop()[:8]}...")

print()
print("=" * 70)
print("DISTRIBUTION REALISM SPOT CHECKS")
print("=" * 70)

print("\nFund strategy mix:")
print(funds["strategy"].value_counts(normalize=True).round(3).to_string())

print("\nFund vintage range:")
print(f"  min={funds['vintage'].min()}  max={funds['vintage'].max()}")

print("\nFund size distribution by strategy (target_size_m):")
print(funds.groupby("strategy")["target_size_m"].describe()[["50%", "mean", "max"]].round(1))

print("\nLP type mix:")
print(lps["lp_type"].value_counts(normalize=True).round(3).to_string())

print("\nCompany sector concentration (top 5):")
print(cos["sector"].value_counts(normalize=True).round(3).head().to_string())

print("\nCompany country concentration (top 5):")
print(cos["country"].value_counts(normalize=True).round(3).head().to_string())

print("\nCompany status mix:")
print(cos["status"].value_counts(normalize=True).round(3).to_string())

print("\nDeal type mix:")
print(deals["deal_type"].value_counts(normalize=True).round(3).to_string())

print("\nValuation method mix:")
print(vals["valuation_method"].value_counts(normalize=True).round(3).to_string())

# Compute crude TVPI per fund as a sanity check (distributions+NAV / capital calls)
print("\nCrude TVPI per fund (sanity check on cashflow logic):")
calls = cfs[cfs["cashflow_type"] == "Capital Call"].groupby("fund_id")["amount_m"].sum()
dists = cfs[cfs["cashflow_type"] == "Distribution"].groupby("fund_id")["amount_m"].sum()
# Latest NAV per company
latest_nav = vals.sort_values("valuation_date").groupby(["fund_id", "company_id"]).tail(1)
nav_by_fund = latest_nav.groupby("fund_id")["fair_value_m"].sum()

tvpi = ((dists.reindex(calls.index).fillna(0) + nav_by_fund.reindex(calls.index).fillna(0)) / calls).round(2)
print(tvpi.describe().round(2).to_string())

print("\nFund-level TVPI summary suggests:")
median = tvpi.median()
if 1.2 <= median <= 3.0:
    print(f"  Median TVPI = {median:.2f}x — PE-realistic ✓")
else:
    print(f"  Median TVPI = {median:.2f}x — review distribution params")

print()
print("=" * 70)
print("BUDGET CHECK")
print("=" * 70)
total = sum(p.stat().st_size for p in DATA.glob("*.parquet"))
print(f"Total committed parquet: {total/1024:.1f} KB  ({total/1024/1024:.2f} MB)")
print(f"Budget: 10 MB → {'WELL WITHIN BUDGET' if total < 10*1024*1024 else 'OVER BUDGET'}")
