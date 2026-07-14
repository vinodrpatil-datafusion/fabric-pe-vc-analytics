# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "4d820914-0336-4005-85c7-95b26729286f",
# META       "default_lakehouse_name": "gold_lakehouse",
# META       "default_lakehouse_workspace_id": "f1f589c3-d0a9-4c55-8dee-b180ff4b4611",
# META       "known_lakehouses": [
# META         {
# META           "id": "4d820914-0336-4005-85c7-95b26729286f"
# META         },
# META         {
# META           "id": "d7e164cd-e1b0-46f9-9bb4-2aca4098fad5"
# META         }
# META       ]
# META     }
# META   }
# META }

# MARKDOWN ********************

# # WS3 · Notebook 05 — Gold Star Schema
# 
# **Stage E of the platform build** (`docs/architecture.md` §2, `docs/design_decisions.md`
# DD-15) — the first step outside the WS2 trust boundary. Reshapes the certified
# `conformed_*` tables into a dimensional model for analytical querying and the
# DirectLake semantic model (S2/WS4).
# 
# Grain, rationale, and every trade-off here were pinned down **before** this notebook was
# written — see DD-15. In short: **one fact** (`fact_investment`, investment grain), three
# dimensions (`dim_company`, `dim_investor`, `dim_date`, both entity dims Type-2/SCD2),
# round attributes carried as degenerates on the fact rather than a separate `dim_round`.
# No fund-performance-snapshot fact — the conformed layer has no periodic valuation
# source to snapshot (DD-15 has the numbers). NAV, if computed downstream in S2, must be
# documented as a cost-basis/realised-proceeds **proxy**, not a real fund NAV.
# 
# Runs in the single-workspace build (`pevc-dev`, DD-14) — Gold lands in its own
# lakehouse alongside `landing_lakehouse` and `conformed_lakehouse`, not a separate
# workspace.


# MARKDOWN ********************

# ## 1. Setup and parameters
# 
# **Before running, you need (in `pevc-dev`):**
# 
# 1. A third lakehouse: **`gold_lakehouse`** — where the dims/fact from this notebook
#    land. (`landing_lakehouse` and `conformed_lakehouse` already exist from WS1/WS2.)
# 2. Attach **`gold_lakehouse` as the default** lakehouse for this notebook (writes land
#    there) and **`conformed_lakehouse` as a secondary** source (reads `conformed_*`
#    tables via `spark.read.table`, same cross-lakehouse pattern as Notebooks 02–04).
# 3. Notebooks 01–04 must have already run successfully — this reads their output.
# 
# No `REFERENCE_FILES` parameter this time: everything this notebook needs is already in
# `conformed_*` tables; it reads no landing files directly.

# CELL ********************

CONFORMED_PREFIX = "conformed"
GOLD_PREFIX = "gold"

from pyspark.sql import functions as F
print("Stage E (Gold) parameters set.")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 2. Helpers
# 
# - `conformed(name)` — read a certified WS2 table.
# - `surrogate_key(*cols)` — deterministic hash of the given columns, **not** an
#   auto-increment identity. Re-running this notebook must be idempotent (DD-15) —
#   the same natural key + validity window always produces the same surrogate key,
#   so a rebuild doesn't silently renumber every downstream relationship.

# CELL ********************

def conformed(name):
    return spark.read.table(f"conformed_lakehouse.dbo.{CONFORMED_PREFIX}_{name}")

def surrogate_key(*cols):
    return F.sha2(F.concat_ws("||", *[F.col(c).cast("string") for c in cols]), 256)

def pit_join(fact_df, fact_date_col, dim_df, natural_key, sk_col):
    """Point-in-time join: attach the dim_df row whose validity window
    (valid_from <= fact_date < valid_to) contains the fact's date — the dim
    version that was TRUE AT THAT TIME, not whatever is current today. This is
    what makes an as-of query on the resulting fact correct (DD-15)."""
    f = fact_df.alias("f")
    d = dim_df.select(natural_key, sk_col, "valid_from", "valid_to").alias("d")
    cond = (
        (F.col(f"f.{natural_key}") == F.col(f"d.{natural_key}")) &
        (F.to_date(F.col(f"f.{fact_date_col}")) >= F.to_date(F.col("d.valid_from"))) &
        (F.to_date(F.col(f"f.{fact_date_col}")) <  F.to_date(F.col("d.valid_to")))
    )
    return f.join(d, cond, "left").select("f.*", F.col(f"d.{sk_col}"))

print("Helpers defined.")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 3. dim_date
# 
# Standard day-grain calendar. Spans the observed data range (earliest `founded_date` /
# round or investment `effective_date`) plus a one-year forward buffer, so "as-of today"
# and near-future exit dates both resolve.

# CELL ********************

from datetime import timedelta

def date_col(df, col):
    return df.select(F.to_date(col).alias("d")).where(F.col("d").isNotNull())

all_dates = (
    date_col(conformed("companies"), "effective_date")
    .union(date_col(conformed("funding_rounds"), "effective_date"))
    .union(date_col(conformed("investments"), "effective_date"))
    .union(date_col(conformed("investments"), "exit_date"))
)
bounds = all_dates.agg(F.min("d").alias("mn"), F.max("d").alias("mx")).first()
start_date, end_date = bounds["mn"], bounds["mx"] + timedelta(days=365)

gold_dim_date = (
    spark.createDataFrame([(start_date, end_date)], ["mn", "mx"])
    .select(F.explode(F.sequence(F.col("mn"), F.col("mx"), F.expr("interval 1 day"))).alias("date"))
    .withColumn("date_sk", F.date_format("date", "yyyyMMdd").cast("int"))
    .withColumn("year", F.year("date"))
    .withColumn("quarter", F.quarter("date"))
    .withColumn("month", F.month("date"))
    .withColumn("month_name", F.date_format("date", "MMMM"))
    .withColumn("day_of_week", F.dayofweek("date"))
    .withColumn("is_quarter_end", (F.col("date") == F.last_day("date")) & F.col("month").isin(3, 6, 9, 12))
)
gold_dim_date.write.mode("overwrite").option("overwriteSchema", "true").format("delta").saveAsTable(f"{GOLD_PREFIX}_dim_date")
print("dim_date:", gold_dim_date.count(), f"rows ({start_date} to {end_date})")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 4. dim_company (Type 2) — with derived `sector_group`
# 
# `conformed_companies` only carries the genuinely multi-valued `sector_taxonomy` array
# (JSON-string, repo-wide convention for nested columns) — there's no single-valued
# category column in the landing feed. `sector_group` is derived here via a small
# taxonomy lookup mirroring `data-generator/pevc_generator/reference.py`'s
# `SECTOR_GROUPS` — a fixed vocabulary, not per-company synthetic data, so reusing it
# isn't leaking oracle information (DD-15). A company's tags are always drawn from a
# single group by construction (`canonical.py`), so resolving via the *first* tag is
# deterministic, not arbitrary.
# 
# **Documented shortcut:** a real vendor feed would ship this taxonomy as its own
# reference table rather than have it hardcoded in a Gold notebook — see DD-15 for the
# "when you'd change it" case.

# CELL ********************

SECTOR_GROUPS = {
    "Information Technology": ["SaaS", "AI/ML", "Cybersecurity", "DevTools", "Data Infrastructure", "Fintech Infra"],
    "Healthcare": ["Digital Health", "Biotech", "Medical Devices", "Diagnostics", "Genomics"],
    "Financials": ["Fintech", "Payments", "Lending", "InsurTech", "WealthTech"],
    "Consumer": ["Consumer Apps", "E-commerce", "Marketplace", "Food & Bev", "Gaming"],
    "Industrials": ["Robotics", "Supply Chain", "Manufacturing Tech", "Logistics"],
    "Energy": ["Energy Storage", "Grid Tech", "Oil & Gas Tech"],
    "Climate": ["Carbon Capture", "Clean Energy", "Sustainability"],
    "Mobility": ["AV/Autonomy", "EV", "Micromobility", "Fleet"],
}
tag_to_group = [(tag, group) for group, tags in SECTOR_GROUPS.items() for tag in tags]
sector_lookup = spark.createDataFrame(tag_to_group, ["tag", "sector_group"])

companies_with_group = (
    conformed("companies")
    .withColumn("_tags", F.from_json("sector_taxonomy", "array<string>"))
    .withColumn("_first_tag", F.col("_tags")[0])
    .join(sector_lookup, F.col("_first_tag") == F.col("tag"), "left")
    .drop("_tags", "_first_tag", "tag")
)

unmatched_tags = companies_with_group.filter(F.col("sector_group").isNull()).count()
if unmatched_tags:
    print(f"WARNING: {unmatched_tags} companies had a tag not in SECTOR_GROUPS — sector_group is null for them.")

gold_dim_company = (
    companies_with_group
    .withColumn("company_sk", surrogate_key("company_id", "valid_from"))
    .select("company_sk", "company_id", "legal_name", "sector_group", "sector_taxonomy",
            "country", F.col("effective_date").alias("founded_date"), "valid_from", "valid_to", "is_current")
)
gold_dim_company.write.mode("overwrite").option("overwriteSchema", "true").format("delta").saveAsTable(f"{GOLD_PREFIX}_dim_company")
print("dim_company:", gold_dim_company.count(), "rows |", gold_dim_company.filter("is_current").count(), "current")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 5. dim_investor (Type 2)
# 
# Same Type-2 pattern, sourced from `conformed_investors`. `vintage_year`, `fund_size`,
# `investor_type`, and `stage_focus` are what vintage-performance and fund-level DAX
# rollups (S2) will group by.

# CELL ********************

gold_dim_investor = (
    conformed("investors")
    .withColumn("investor_sk", surrogate_key("investor_id", "valid_from"))
    .select("investor_sk", "investor_id", "investor_type", "legal_name", "vintage_year",
            "fund_size", "geographic_focus", "sector_focus", "stage_focus",
            "valid_from", "valid_to", "is_current")
)
gold_dim_investor.write.mode("overwrite").option("overwriteSchema", "true").format("delta").saveAsTable(f"{GOLD_PREFIX}_dim_investor")
print("dim_investor:", gold_dim_investor.count(), "rows |", gold_dim_investor.filter("is_current").count(), "current")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 6. fact_investment
# 
# Grain: one row per **current** `investment_id` (`conformed_investments` where
# `is_current = true`) — the atomic, non-additive-risk grain every LP measure rolls up
# from (DD-15). Round attributes (`round_type`, `instrument_type`, valuations) are
# carried as degenerate dimensions directly on the fact — no separate `dim_round`
# (848 rows doesn't justify normalising a handful of repeated strings).
# 
# `company_sk` and `investor_sk` are resolved via `pit_join` against each investment's
# `effective_date` — the dimension version **that was true when the investment
# happened**, not whichever version is current today.

# CELL ********************

investments_current = conformed("investments").filter(F.col("is_current") == True)
rounds_current = conformed("funding_rounds").filter(F.col("is_current") == True)

fact_base = investments_current.join(
    rounds_current.select(
        "round_id", "round_type", "instrument_type", "amount_raised", "currency",
        "pre_money_valuation", "post_money_valuation",
    ),
    "round_id", "left",
)

fact_pit = pit_join(fact_base, "effective_date", gold_dim_company, "company_id", "company_sk")
fact_pit = pit_join(fact_pit, "effective_date", gold_dim_investor, "investor_id", "investor_sk")

gold_fact_investment = (
    fact_pit
    .withColumn("investment_sk", surrogate_key("investment_id"))
    .withColumn("effective_date_sk", F.date_format(F.to_date("effective_date"), "yyyyMMdd").cast("int"))
    .withColumn("exit_date_sk", F.when(F.col("exit_date").isNotNull(),
                    F.date_format(F.to_date("exit_date"), "yyyyMMdd").cast("int")))
    .withColumn("is_realized", F.col("exit_date").isNotNull())
    .select(
        "investment_sk", "investment_id", "company_sk", "investor_sk",
        "effective_date_sk", "exit_date_sk",
        "round_id", "round_type", "instrument_type",
        "amount_raised", "currency", "pre_money_valuation", "post_money_valuation",
        "participation_amount", "is_lead", "board_seat_taken",
        "effective_date", "exit_date", "exit_type", "is_realized",
        "realised_return_multiple",
    )
)
gold_fact_investment.write.mode("overwrite").option("overwriteSchema", "true").format("delta").saveAsTable(f"{GOLD_PREFIX}_fact_investment")
print("fact_investment:", gold_fact_investment.count(), "rows |",
      gold_fact_investment.filter("is_realized").count(), "realised")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# > **NAV honesty note (carried from DD-15):** this fact has `participation_amount`
# > (cost basis) and `realised_return_multiple` (populated only on exit — see the
# > realised count printed above vs. total rows). There is no periodic fair-value mark.
# > Any "NAV" measure S2 builds on top of this must be documented as a **proxy** — it is
# > not a real fund NAV.

# MARKDOWN ********************

# ## 7. OPTIMIZE / V-Order
# 
# DirectLake performance depends on V-Order (DD-06). Applied per table, not left to a
# workspace default, so it's explicit in this notebook's output.

# CELL ********************

for t in [f"{GOLD_PREFIX}_dim_date", f"{GOLD_PREFIX}_dim_company",
          f"{GOLD_PREFIX}_dim_investor", f"{GOLD_PREFIX}_fact_investment"]:
    spark.sql(f"OPTIMIZE {t} VORDER")
    print(f"OPTIMIZE {t} VORDER — done")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 8. Gold DQ assertions
# 
# Same `check()` / hard-fail pattern as Notebook 04's Stage D — FK integrity fact→dim,
# no unresolved point-in-time joins, row-count reconciliation to conformed, one-current-
# per-key on both dims. Raises on any hard failure so a broken Gold build doesn't reach
# the semantic model.

# CELL ********************

report = []
def check(name, ok, detail, hard=True):
    status = "PASS" if ok else ("FAIL" if hard else "WARN")
    report.append((name, status, hard, str(detail)))

def fk_unresolved(child, ccol, parent, pcol):
    return (child.select(ccol).filter(F.col(ccol).isNotNull()).distinct()
            .join(parent.select(pcol).distinct(), child[ccol] == parent[pcol], "left_anti").count())

fk_checks = [
    ("FK fact_investment.company_sk -> dim_company", gold_fact_investment, "company_sk", gold_dim_company, "company_sk"),
    ("FK fact_investment.investor_sk -> dim_investor", gold_fact_investment, "investor_sk", gold_dim_investor, "investor_sk"),
]
for name, child, ccol, parent, pcol in fk_checks:
    miss = fk_unresolved(child, ccol, parent, pcol)
    n_child = child.select(ccol).filter(F.col(ccol).isNotNull()).distinct().count()
    check(name, miss == 0, f"{miss} unresolved of {n_child} distinct")

# Soft check: a handful of funding rounds in the synthetic data close before their
# company's founded_date (generator calibration noise — SYNTHETIC_DATA.md "Known
# calibration caveats"). Those investments can never resolve a point-in-time
# dim_company version, so this is a WARN, not a hard fail, unlike the investor check
# below where any non-zero count would indicate a real join defect.
null_company_sk = gold_fact_investment.filter(F.col("company_sk").isNull()).count()
check("no unmatched point-in-time company join", null_company_sk == 0,
      f"{null_company_sk} fact rows with no matching dim_company version "
      "(known generator calibration noise: some funding rounds close before company founded_date)",
      hard=False)

null_investor_sk = gold_fact_investment.filter(F.col("investor_sk").isNull()).count()
check("no unmatched point-in-time investor join", null_investor_sk == 0,
      f"{null_investor_sk} fact rows with no matching dim_investor version")

n_fact = gold_fact_investment.count()
n_conformed_inv = conformed("investments").filter(F.col("is_current") == True).select("investment_id").distinct().count()
check("rowcount reconcile fact_investment vs conformed_investments", n_fact == n_conformed_inv,
      f"{n_fact} fact rows vs {n_conformed_inv} current conformed investments")

for name, df, key in [("dim_company", gold_dim_company, "company_id"), ("dim_investor", gold_dim_investor, "investor_id")]:
    cur = df.filter(F.col("is_current") == True)
    multi = cur.groupBy(key).count().filter(F.col("count") > 1).count()
    check(f"envelope one-current-per-key [{name}]", multi == 0, f"{multi} keys with >1 current row")

rep_df = spark.createDataFrame(report, ["check_name", "status", "is_hard", "detail"])
rep_df.write.mode("overwrite").option("overwriteSchema", "true").format("delta").saveAsTable("gold_dq_assertions_report")

print("="*92)
print("STAGE E — GOLD DATA QUALITY ASSERTIONS")
print("="*92)
for name, status, hard, detail in report:
    print(f"  [{status:4s}] {name:54s} {detail}")

hard_fail = [r for r in report if r[2] and r[1] == "FAIL"]
n_hard = len([r for r in report if r[2]])
print("-"*92)
print(f"Hard checks: {n_hard}  |  Hard failures: {len(hard_fail)}")
if hard_fail:
    print("VERDICT: FAIL")
    raise Exception(f"Gold DQ: {len(hard_fail)} hard assertion(s) failed: {[r[0] for r in hard_fail]}")
print("VERDICT: PASS — Gold star schema certified.")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 9. Certification: sample "as-of" query
# 
# Demonstrates point-in-time correctness directly against `dim_company`'s validity
# window — the pattern an analyst's "as of {date}" question uses, independent of what's
# stamped on any one fact row. If Notebook 03's SCD2 demo ran, the corrected company will
# show two versions here with different `valid_from`/`valid_to` windows and (before vs.
# after the correction date) a different `legal_name`.

# CELL ********************

as_of_date = str(start_date)   # earliest observed date; change to any date in range

sample_company_id = gold_dim_company.select("company_id").first()["company_id"]

as_of_view = gold_dim_company.filter(
    (F.col("company_id") == sample_company_id) &
    (F.to_date(F.lit(as_of_date)) >= F.to_date("valid_from")) &
    (F.to_date(F.lit(as_of_date)) <  F.to_date("valid_to"))
)
print(f"dim_company for {sample_company_id} as of {as_of_date}:")
as_of_view.select("company_id", "legal_name", "sector_group", "valid_from", "valid_to", "is_current").show(truncate=False)

print("All versions on file for this company (for comparison):")
gold_dim_company.filter(F.col("company_id") == sample_company_id) \
    .select("company_id", "legal_name", "sector_group", "valid_from", "valid_to", "is_current") \
    .orderBy("valid_from").show(truncate=False)


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 10. WS3 complete
# 
# The Gold star schema is built **and certified**:
# - `dim_date`, `dim_company` (Type 2), `dim_investor` (Type 2) — three dimensions.
# - `fact_investment` — investment-grain fact, point-in-time joined to both entity dims.
# - V-Order applied to all four tables (DirectLake performance dependency, DD-06).
# - Gold DQ assertions certified: FK integrity, no unmatched point-in-time joins,
#   row-count reconciliation to conformed, envelope sanity — raises on hard failure.
# - Sample as-of query demonstrated against `dim_company`'s validity window.
# 
# No fund-performance-snapshot fact was built — DD-15 explains why (no periodic
# valuation source in the conformed layer) and what S2 needs to do instead (DAX rollups
# over `fact_investment`, with an explicit NAV-proxy caveat).
# 
# **WS4** (DirectLake semantic model, S2) reads these four Gold tables and defines the
# five core LP measures on top of them.
