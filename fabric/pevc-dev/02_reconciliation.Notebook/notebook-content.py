# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "d7e164cd-e1b0-46f9-9bb4-2aca4098fad5",
# META       "default_lakehouse_name": "conformed_lakehouse",
# META       "default_lakehouse_workspace_id": "f1f589c3-d0a9-4c55-8dee-b180ff4b4611",
# META       "known_lakehouses": [
# META         {
# META           "id": "d7e164cd-e1b0-46f9-9bb4-2aca4098fad5"
# META         }
# META       ]
# META     }
# META   }
# META }

# MARKDOWN ********************

# # WS2 · Notebook 02 — Reconciliation
# 
# **Stage B of the conformed build** (`architecture.md` §3.2) — the centrepiece.
# 
# Stage A proved each feed is *structurally* valid. But `dealroom` and `capitaliq`
# **disagree** about the same real-world entities. This notebook resolves those
# disagreements into one version of the truth, and — critically — **surfaces
# conflicts rather than silently picking winners** (§3.2).
# 
# ### Resolution policy
# 
# | Conflict | Rule | Status | Logged as |
# |---|---|---|---|
# | **temporal** — `announced_date` >30 days apart | auto-resolve to **earliest** (closest to true close) | `conflict_resolved` | `auto_resolved` |
# | **value** — `amount_raised` / `fund_size` >5% apart | **flag** — money is not auto-decided | `conflict_flagged` | `flagged_for_review` |
# | **existence** — entity in one source only, *company covered by both* (genuine) | **flag** | `conflict_flagged` | `flagged_for_review` |
# | **existence** — entity in one source only, *coverage gap* | auto-resolve, take available | `conflict_resolved` | `auto_resolved` |
# | sources agree | — | `clean` | — |
# 
# ### Identity
# 
# Vendor IDs are resolved to **canonical IDs** here via `vendor_id_mapping` — the
# conformed layer speaks platform identity, not vendor identity (`architecture.md` §4).
# 
# ### Self-check
# 
# The final cells **score** this notebook's `reconciliation_log` against the
# `expected_conflicts` oracle from WS1: recall + precision. 1.000/1.000 means the
# implementation faithfully applies the rules above (a spec-conformance / regression
# check — it catches drift, it does not claim the algorithm is "clever").


# MARKDOWN ********************

# ## 1. Parameters
# 
# Reads the **validated** tables Stage A wrote to `conformed_lakehouse` (set as the
# notebook's default lakehouse). Reads `vendor_id_mapping` and `expected_conflicts`
# from the reference files you uploaded to `landing_lakehouse/Files/reference`.
# 
# Set `REFERENCE_FILES` to the ABFS path of that reference folder — same base you
# used in Notebook 01, with `/landing` replaced by `/reference`.


# CELL ********************

AMOUNT_TOL = 0.05      # >5% relative difference = value disagreement
DAYS_TOL   = 30        # >30 days apart = temporal disagreement

VALIDATED_PREFIX = "stg_validated"
RECONCILED_PREFIX = "reconciled"
LOG_TABLE = "reconciliation_log"

# ABFS path to the reference folder (vendor_id_mapping, expected_conflicts).
# Same base as Notebook 01 but ending in /Files/reference
REFERENCE_FILES = "abfss://f1f589c3-d0a9-4c55-8dee-b180ff4b4611@onelake.dfs.fabric.microsoft.com/4559f0cc-d5bd-491a-a492-0043526e94e4/Files/landing/reference"

from pyspark.sql import functions as F, Window
spark.conf.set("spark.sql.caseSensitive", "true")
print("Stage B parameters set.")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 2. Helpers: read validated tables, attach canonical IDs
# 
# `vendor_id_mapping` tells us which canonical entity each vendor row refers to.
# We attach `canonical_id` to every source row so we can group the two sources by
# the *same* entity and compare them.


# CELL ********************

def read_ref(name):
    for path in [f"{REFERENCE_FILES}/{name}.parquet", f"{REFERENCE_FILES}/{name}",
                 f"{REFERENCE_FILES}/{name}.csv"]:
        try:
            return (spark.read.parquet(path) if not path.endswith(".csv")
                    else spark.read.option("header", True).option("inferSchema", True).csv(path))
        except Exception:
            continue
    raise FileNotFoundError(f"reference {name} not found under {REFERENCE_FILES}")

mapping = read_ref("vendor_id_mapping").cache()

def validated(source, entity):
    return spark.read.table(f"{VALIDATED_PREFIX}_{source}_{entity}")

def attach_canonical(df, entity_type, vendor_col, source):
    m = (mapping.filter((F.col("entity_type") == entity_type) & (F.col("source_system") == source))
                .select(F.col("vendor_id"), F.col("canonical_id")))
    return df.join(m, df[vendor_col] == m["vendor_id"], "left").drop("vendor_id")

# Company coverage: canonical company -> number of sources covering it
comp_cov = (mapping.filter(F.col("entity_type") == "company")
            .groupBy("canonical_id").agg(F.countDistinct("source_system").alias("n_sources")))
print("Mapping loaded; helpers ready.")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 3. Reconcile a two-source entity
# 
# A general routine: full-outer-join the two sources on `canonical_id`, then derive
# per-row `reconciliation_status` and emit log rows. We specialise the *comparison*
# per entity (rounds compare dates + amounts; investors compare fund_size; etc.).
# 
# We build the `reconciliation_log` incrementally as a list of small DataFrames and
# union them at the end.


# CELL ********************

log_frames = []

def log_rows(rows):
    if rows:
        log_frames.append(spark.createDataFrame(rows))

def both_sources(dr, cq, key):
    return dr.alias("d").join(cq.alias("c"), F.col(f"d.{key}") == F.col(f"c.{key}"), "full_outer")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 4. Companies — existence only (per the oracle)
# 
# Companies present in one source only are a **coverage gap** → auto-resolved, take
# the available source, log existence. Companies in both → clean. (Minor name/sector
# variations are resolved by preferring `dealroom`; richer company-attribute conflict
# logging is a documented future refinement, intentionally not scored here.)


# CELL ********************

dr = attach_canonical(validated("dealroom", "companies"), "company", "vendor_company_id", "dealroom")
cq = attach_canonical(validated("capitaliq", "companies"), "company", "vendor_company_id", "capitaliq")

drc = dr.select("canonical_id", "legal_name", "country").withColumn("in_dr", F.lit(True))
cqc = cq.select("canonical_id", F.col("legal_name").alias("legal_name_c"),
                F.col("country").alias("country_c")).withColumn("in_cq", F.lit(True))
j = drc.join(cqc, "canonical_id", "full_outer") \
       .withColumn("in_dr", F.coalesce("in_dr", F.lit(False))) \
       .withColumn("in_cq", F.coalesce("in_cq", F.lit(False)))

j = j.withColumn("reconciliation_status",
        F.when(F.col("in_dr") & F.col("in_cq"), F.lit("clean")).otherwise(F.lit("conflict_resolved"))) \
     .withColumn("legal_name", F.coalesce("legal_name", "legal_name_c")) \
     .withColumn("country", F.coalesce("country", "country_c"))

rec_companies = j.select("canonical_id", "legal_name", "country", "reconciliation_status") \
                 .withColumnRenamed("canonical_id", "company_id")
rec_companies.write.mode("overwrite").format("delta").saveAsTable(f"{RECONCILED_PREFIX}_companies")

# log existence (coverage gap) for one-source companies
co_logs = [r["company_id"] for r in rec_companies.filter(F.col("reconciliation_status") == "conflict_resolved")
           .select("company_id").collect()]
log_rows([{"entity_type": "company", "entity_id": c, "conflict_type": "existence_disagreement",
           "resolution_action": "auto_resolved", "resolved_by": "stage_b"} for c in co_logs])
print(f"companies reconciled; {len(co_logs)} coverage-gap existence conflicts logged")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 5. Funding rounds — temporal (auto) + value (flag) + existence
# 
# The richest entity. For rounds in both sources we compare `announced_date`
# (temporal → earliest) and `amount_raised` (value → flag). A round can have both;
# **flag outranks resolved** for the row status.


# CELL ********************

dr = attach_canonical(validated("dealroom", "funding_rounds"), "funding_round", "vendor_round_id", "dealroom")
cq = attach_canonical(validated("capitaliq", "funding_rounds"), "funding_round", "vendor_round_id", "capitaliq")

d = dr.select("canonical_id", F.col("announced_date").alias("ad_d"), F.col("amount_raised").alias("amt_d")).withColumn("in_dr", F.lit(True))
c = cq.select("canonical_id", F.col("announced_date").alias("ad_c"), F.col("amount_raised").alias("amt_c")).withColumn("in_cq", F.lit(True))
j = d.join(c, "canonical_id", "full_outer") \
     .withColumn("in_dr", F.coalesce("in_dr", F.lit(False))) \
     .withColumn("in_cq", F.coalesce("in_cq", F.lit(False)))

both = F.col("in_dr") & F.col("in_cq")
days_apart = F.abs(F.datediff(F.to_date("ad_d"), F.to_date("ad_c")))
rel_amt = F.abs(F.col("amt_d") - F.col("amt_c")) / F.greatest("amt_d", "amt_c")

j = j.withColumn("is_temporal", both & (days_apart > DAYS_TOL)) \
     .withColumn("is_value", both & (F.greatest("amt_d", "amt_c") > 0) & (rel_amt > AMOUNT_TOL)) \
     .withColumn("is_existence", ~both) \
     .withColumn("announced_date_resolved",
                 F.when(both, F.least(F.to_date("ad_d"), F.to_date("ad_c")).cast("string"))
                  .otherwise(F.coalesce("ad_d", "ad_c"))) \
     .withColumn("amount_raised", F.coalesce("amt_d", "amt_c")) \
     .withColumn("reconciliation_status",
                 F.when(F.col("is_value"), F.lit("conflict_flagged"))
                  .when(F.col("is_temporal") | F.col("is_existence"), F.lit("conflict_resolved"))
                  .otherwise(F.lit("clean")))

rec_rounds = j.select(F.col("canonical_id").alias("round_id"),
                      "amount_raised", F.col("announced_date_resolved").alias("announced_date"),
                      "reconciliation_status")
rec_rounds.write.mode("overwrite").format("delta").saveAsTable(f"{RECONCILED_PREFIX}_funding_rounds")

def ids_where(cond_col):
    return [r["canonical_id"] for r in j.filter(F.col(cond_col)).select("canonical_id").collect()]

log_rows([{"entity_type":"funding_round","entity_id":i,"conflict_type":"temporal_disagreement","resolution_action":"auto_resolved","resolved_by":"stage_b"} for i in ids_where("is_temporal")])
log_rows([{"entity_type":"funding_round","entity_id":i,"conflict_type":"value_disagreement","resolution_action":"flagged_for_review","resolved_by":"stage_b"} for i in ids_where("is_value")])
log_rows([{"entity_type":"funding_round","entity_id":i,"conflict_type":"existence_disagreement","resolution_action":"auto_resolved","resolved_by":"stage_b"} for i in ids_where("is_existence")])
print("funding_rounds reconciled and logged")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 6. Investors — value (fund_size) only
# 
# Both sources carry every investor (full coverage), so no existence conflicts.
# `fund_size` disagreements >5% are flagged.


# CELL ********************

dr = attach_canonical(validated("dealroom", "investors"), "investor", "vendor_investor_id", "dealroom")
cq = attach_canonical(validated("capitaliq", "investors"), "investor", "vendor_investor_id", "capitaliq")
d = dr.select("canonical_id", F.col("fund_size").alias("fs_d"))
c = cq.select("canonical_id", F.col("fund_size").alias("fs_c"))
j = d.join(c, "canonical_id", "full_outer")
rel = F.abs(F.col("fs_d") - F.col("fs_c")) / F.greatest("fs_d", "fs_c")
j = j.withColumn("is_value", F.col("fs_d").isNotNull() & F.col("fs_c").isNotNull()
                 & (F.greatest("fs_d", "fs_c") > 0) & (rel > AMOUNT_TOL)) \
     .withColumn("reconciliation_status", F.when(F.col("is_value"), F.lit("conflict_flagged")).otherwise(F.lit("clean"))) \
     .withColumn("fund_size", F.coalesce("fs_d", "fs_c"))
rec_investors = j.select(F.col("canonical_id").alias("investor_id"), "fund_size", "reconciliation_status")
rec_investors.write.mode("overwrite").format("delta").saveAsTable(f"{RECONCILED_PREFIX}_investors")
log_rows([{"entity_type":"investor","entity_id":r["canonical_id"],"conflict_type":"value_disagreement","resolution_action":"flagged_for_review","resolved_by":"stage_b"}
          for r in j.filter(F.col("is_value")).select("canonical_id").collect()])
print("investors reconciled and logged")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 7. Investments — existence split: genuine dispute vs coverage gap
# 
# An investment edge in one source only is either:
# - **genuine** — its company is covered by *both* sources, so the missing edge is a
#   real disagreement → **flag**.
# - **coverage gap** — its company is only in one source → auto-resolve.
# 
# We classify using `comp_cov` (company coverage) joined via the edge's company.


# CELL ********************

dr = attach_canonical(validated("dealroom", "investments"), "investment", "vendor_investment_id", "dealroom")
cq = attach_canonical(validated("capitaliq", "investments"), "investment", "vendor_investment_id", "capitaliq")

# canonical company per edge
ccm = mapping.filter(F.col("entity_type") == "company").select(
        F.col("source_system").alias("src"), F.col("vendor_id").alias("vcid"),
        F.col("canonical_id").alias("canon_company"))

def with_company(df, source):
    return df.join(ccm.filter(F.col("src") == source), df["vendor_company_id"] == F.col("vcid"), "left") \
             .drop("vcid", "src")

dr2 = with_company(dr, "dealroom").select("canonical_id", "canon_company").withColumn("in_dr", F.lit(True))
cq2 = with_company(cq, "capitaliq").select("canonical_id", F.col("canon_company").alias("cc_c")).withColumn("in_cq", F.lit(True))

j = dr2.join(cq2, "canonical_id", "full_outer") \
       .withColumn("in_dr", F.coalesce("in_dr", F.lit(False))) \
       .withColumn("in_cq", F.coalesce("in_cq", F.lit(False))) \
       .withColumn("company", F.coalesce("canon_company", "cc_c"))

# Rename comp_cov key to avoid ambiguous canonical_id after the join
cov = comp_cov.select(F.col("canonical_id").alias("cov_company"), "n_sources")
j = j.join(cov, j["company"] == cov["cov_company"], "left").drop("cov_company")

both = F.col("in_dr") & F.col("in_cq")
j = j.withColumn("is_genuine", (~both) & (F.col("n_sources") >= 2)) \
     .withColumn("is_coverage", (~both) & (F.coalesce("n_sources", F.lit(0)) < 2)) \
     .withColumn("reconciliation_status",
                 F.when(F.col("is_genuine"), F.lit("conflict_flagged"))
                  .when(F.col("is_coverage"), F.lit("conflict_resolved"))
                  .otherwise(F.lit("clean")))

rec_inv = j.select(F.col("canonical_id").alias("investment_id"), "reconciliation_status")
rec_inv.write.mode("overwrite").format("delta").saveAsTable(f"{RECONCILED_PREFIX}_investments")

log_rows([{"entity_type":"investment","entity_id":r["canonical_id"],"conflict_type":"existence_disagreement","resolution_action":"flagged_for_review","resolved_by":"stage_b"}
          for r in j.filter(F.col("is_genuine")).select("canonical_id").collect()])
log_rows([{"entity_type":"investment","entity_id":r["canonical_id"],"conflict_type":"existence_disagreement","resolution_action":"auto_resolved","resolved_by":"stage_b"}
          for r in j.filter(F.col("is_coverage")).select("canonical_id").collect()])
print("investments reconciled and logged")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 8. Write the reconciliation_log
# 
# One row per detected conflict, matching `data_model.md` §1.8. This is the audit
# trail an analyst consults when they ask *"why does our platform show X?"*


# CELL ********************

from functools import reduce
log_df = reduce(lambda a, b: a.unionByName(b), log_frames)
log_df = log_df.withColumn("resolved_date", F.current_timestamp()) \
               .withColumn("reconciliation_id", F.expr("uuid()"))
log_df.write.mode("overwrite").format("delta").saveAsTable(LOG_TABLE)
print(f"reconciliation_log written: {log_df.count()} conflicts")
log_df.groupBy("entity_type", "conflict_type", "resolution_action").count().orderBy("entity_type", "conflict_type").show(20, truncate=False)


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 9. Score against the oracle (the proof)
# 
# Join `reconciliation_log` to WS1's `expected_conflicts`. **Recall** = of conflicts
# that should exist, how many we detected. **Precision** = of conflicts we detected,
# how many were expected. 1.000/1.000 = implementation faithful to spec.


# CELL ********************

oracle = read_ref("expected_conflicts")
E = oracle.select("entity_type", F.col("canonical_id").alias("entity_id"), "conflict_type").distinct()
D = log_df.select("entity_type", "entity_id", "conflict_type").distinct()
inter = E.intersect(D)
nE, nD, nI = E.count(), D.count(), inter.count()
recall = nI / nE if nE else 0
precision = nI / nD if nD else 0
print(f"Expected : {nE}\nDetected : {nD}\nMatched  : {nI}")
print(f"Recall    : {recall:.3f}")
print(f"Precision : {precision:.3f}")

# subtype correctness on investment edges
gen = oracle.filter((F.col("entity_type")=="investment") & (F.col("existence_subtype")=="genuine_dispute")).select("canonical_id")
cov = oracle.filter((F.col("entity_type")=="investment") & (F.col("existence_subtype")=="coverage_gap")).select("canonical_id")
inv_log = log_df.filter(F.col("entity_type")=="investment").select("entity_id","resolution_action")
gen_bad = gen.join(inv_log, gen.canonical_id==inv_log.entity_id, "inner").filter(F.col("resolution_action")!="flagged_for_review").count()
cov_bad = cov.join(inv_log, cov.canonical_id==inv_log.entity_id, "inner").filter(F.col("resolution_action")!="auto_resolved").count()
print(f"\nGenuine edges mis-handled (should be 0): {gen_bad}")
print(f"Coverage edges mis-handled (should be 0): {cov_bad}")
print("\nVERDICT:", "PASS — reconciliation matches oracle" if (recall==1 and precision==1 and gen_bad==0 and cov_bad==0) else "REVIEW")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 10. Outputs
# 
# Written to `conformed_lakehouse`:
# - `reconciled_companies`, `reconciled_funding_rounds`, `reconciled_investors`, `reconciled_investments` — one row per **canonical** entity, with `reconciliation_status`.
# - `reconciliation_log` — every conflict, typed and resolved.
# 
# Stage C (Notebook 03) reads these four reconciled tables plus the three validated
# internal tables, and applies the **bitemporal load** (`effective_date` /
# `ingestion_date`, Type-2 SCD) to produce the final conformed entities.

