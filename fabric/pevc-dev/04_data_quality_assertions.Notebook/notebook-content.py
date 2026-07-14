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

# # WS2 · Notebook 04 — Data Quality Assertions
# 
# **Stage D of the conformed build** (`architecture.md` §3.4) — the **post-load gate**.
# 
# Stages A–C *built* the conformed layer. Stage D *certifies* it: a suite of assertions
# that pass loudly or fail loudly, so WS3 (the Gold Warehouse) never reads a silently
# broken table. In a scheduled pipeline this notebook **raises** on any hard failure,
# halting promotion of bad data.
# 
# ### Why assert what a database would normally enforce?
# 
# Fabric warehouses treat PK / UNIQUE / FK as **metadata only — they are not enforced**
# (they don't block duplicates or orphans). So referential integrity isn't guaranteed by
# the engine; we have to **assert it ourselves**. That's exactly what this notebook does.
# 
# ### Assertion categories
# 
# | Category | Hard / Soft | What it checks |
# |---|---|---|
# | **Referential integrity** | hard | every conformed FK resolves to a parent key |
# | **Envelope sanity** | hard | exactly one `is_current` per key; no null envelope; `valid_from <= valid_to` |
# | **Row-count reconciliation** | hard | distinct keys tie back to canonical / source counts |
# | **Status domain** | hard | `reconciliation_status` only ever in the allowed set |
# | **Temporal sanity** | **soft** | `effective_date <= ingestion_date` — disclosure lag makes occasional violations legitimate, so this **warns with a count**, doesn't fail |
# 
# A small **assertions report** is written as a Delta table for auditability, and the
# notebook raises an exception if any *hard* check fails.


# MARKDOWN ********************

# ## 1. Parameters

# CELL ********************

CONFORMED_PREFIX = "conformed"
VALIDATED_PREFIX = "stg_validated"
ALLOWED_STATUS = {"clean", "conflict_resolved", "conflict_flagged"}
REPORT_TABLE = "dq_assertions_report"

# Same ABFS reference path as Notebooks 02 / 03 (ends /Files/landing/reference)
REFERENCE_FILES = "abfss://f1f589c3-d0a9-4c55-8dee-b180ff4b4611@onelake.dfs.fabric.microsoft.com/4559f0cc-d5bd-491a-a492-0043526e94e4/Files/landing/reference"

from pyspark.sql import functions as F
print("Stage D parameters set.")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 2. Helpers
# 
# `check()` accumulates a result row; `fk_unresolved()` counts child keys with no matching
# parent (via an anti-join — rows on the left with no match on the right).


# CELL ********************

def read_ref(name):
    for path in [f"{REFERENCE_FILES}/{name}.parquet", f"{REFERENCE_FILES}/{name}", f"{REFERENCE_FILES}/{name}.csv"]:
        try:
            return (spark.read.parquet(path) if not path.endswith(".csv")
                    else spark.read.option("header", True).option("inferSchema", True).csv(path))
        except Exception:
            continue
    raise FileNotFoundError(f"reference {name} not found under {REFERENCE_FILES}")

def conformed(name): return spark.read.table(f"{CONFORMED_PREFIX}_{name}")
def validated(source, entity): return spark.read.table(f"{VALIDATED_PREFIX}_{source}_{entity}")

report = []
def check(name, ok, detail, hard=True):
    status = "PASS" if ok else ("FAIL" if hard else "WARN")
    report.append((name, status, hard, str(detail)))

def fk_unresolved(child, child_col, parent, parent_col):
    c = child.select(F.col(child_col).alias("k")).filter(F.col("k").isNotNull()).distinct()
    p = parent.select(F.col(parent_col).alias("k")).distinct()
    return c.join(p, "k", "left_anti").count()

# load conformed entities
co, fr, iv, inv = conformed("companies"), conformed("funding_rounds"), conformed("investors"), conformed("investments")
pe, de, do = conformed("people"), conformed("deals"), conformed("documents")
mapping = read_ref("vendor_id_mapping").cache()
canon = {r["entity_type"]: r["n"] for r in mapping.groupBy("entity_type").agg(F.countDistinct("canonical_id").alias("n")).collect()}
print("Conformed entities + mapping loaded.")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 3. Referential integrity (hard)
# 
# Every foreign key in the conformed graph must resolve. The core investment graph
# (rounds→companies, investments→{investors, rounds, companies}) plus the internal-feed
# references (deals→companies, documents→people).


# CELL ********************

checks_ri = [
    ("RI funding_rounds.company_id -> companies", fr, "company_id", co, "company_id"),
    ("RI investments.investor_id -> investors",   inv, "investor_id", iv, "investor_id"),
    ("RI investments.round_id -> funding_rounds", inv, "round_id", fr, "round_id"),
    ("RI investments.company_id -> companies",    inv, "company_id", co, "company_id"),
    ("RI deals.company_id -> companies",          de, "company_id", co, "company_id"),
    ("RI documents.author_person_id -> people",   do, "author_person_id", pe, "person_id"),
]
for name, child, ccol, parent, pcol in checks_ri:
    n_child = child.select(ccol).filter(F.col(ccol).isNotNull()).distinct().count()
    miss = fk_unresolved(child, ccol, parent, pcol)
    check(name, miss == 0, f"{miss} unresolved of {n_child} distinct")
print("RI checks done.")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 4. Envelope sanity (hard)
# 
# For each entity: exactly one `is_current = true` row per business key, no null envelope
# columns, and `valid_from <= valid_to`. (Robust to versions created by the SCD2 demo —
# a key may have multiple rows but only one current.)


# CELL ********************

entities = [("companies", co, "company_id"), ("funding_rounds", fr, "round_id"),
            ("investors", iv, "investor_id"), ("investments", inv, "investment_id"),
            ("people", pe, "person_id"), ("deals", de, "deal_id"), ("documents", do, "document_id")]
for name, df, key in entities:
    cur = df.filter(F.col("is_current") == True).groupBy(key).count()
    multi = cur.filter(F.col("count") > 1).count()
    keys_with_current = cur.count()
    total_keys = df.select(key).distinct().count()
    ok = (multi == 0) and (keys_with_current == total_keys)
    check(f"envelope one-current-per-key [{name}]", ok, f"{multi} keys >1 current; {keys_with_current}/{total_keys} keys have a current row")
    null_env = df.filter(F.col("valid_from").isNull() | F.col("valid_to").isNull() | F.col("is_current").isNull()).count()
    check(f"envelope no-nulls [{name}]", null_env == 0, f"{null_env} null envelope rows")
    inverted = df.filter(F.to_date("valid_from") > F.to_date("valid_to")).count()
    check(f"envelope valid_from<=valid_to [{name}]", inverted == 0, f"{inverted} inverted ranges")
print("envelope checks done.")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 5. Row-count reconciliation (hard)
# 
# Distinct keys must tie back to expected counts — the multi-source entities to the
# canonical counts in `vendor_id_mapping`; the internal entities to their validated
# source-table counts (no hard-coded numbers).


# CELL ********************

recon = [
    ("companies", co, "company_id", canon["company"]),
    ("funding_rounds", fr, "round_id", canon["funding_round"]),
    ("investors", iv, "investor_id", canon["investor"]),
    ("investments", inv, "investment_id", canon["investment"]),
    ("people", pe, "person_id", validated("internal", "people").count()),
    ("deals", de, "deal_id", validated("internal", "deals").count()),
    ("documents", do, "document_id", validated("internal", "documents").count()),
]
for name, df, key, expected in recon:
    n = df.select(key).distinct().count()
    check(f"rowcount reconcile [{name}]", n == expected, f"{n} distinct keys vs {expected} expected")
print("rowcount checks done.")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 6. Status domain (hard) + temporal sanity (soft)
# 
# Status must stay within the allowed set. The temporal check counts rows where
# `effective_date > ingestion_date` and **warns** rather than fails — disclosure lag means
# a fact can legitimately be learned before its formal effective date in some feeds.


# CELL ********************

for name, df in [("companies", co), ("funding_rounds", fr), ("investors", iv), ("investments", inv),
                 ("people", pe), ("deals", de), ("documents", do)]:
    bad = df.filter(~F.col("reconciliation_status").isin(list(ALLOWED_STATUS))).count()
    check(f"status domain [{name}]", bad == 0, f"{bad} rows outside allowed set")

for name, df in [("companies", co), ("funding_rounds", fr), ("investments", inv), ("documents", do)]:
    v = df.filter(F.to_date("effective_date") > F.to_date("ingestion_date")).count()
    check(f"temporal effective<=ingestion [{name}]", v == 0,
          f"{v} rows effective > ingestion (disclosure-lag expected)", hard=False)
print("status + temporal checks done.")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 7. Report + verdict
# 
# Render every check, write the report as a Delta table for audit, and **raise** if any
# hard assertion failed (so a scheduled run halts on bad data).


# CELL ********************

rep_df = spark.createDataFrame(report, ["check_name", "status", "is_hard", "detail"])
rep_df.write.mode("overwrite").option("overwriteSchema", "true").format("delta").saveAsTable(REPORT_TABLE)

print("="*92)
print("STAGE D — DATA QUALITY ASSERTIONS")
print("="*92)
for name, status, hard, detail in report:
    print(f"  [{status:4s}] {name:54s} {detail}")

hard_fail = [r for r in report if r[2] and r[1] == "FAIL"]
warns = [r for r in report if r[1] == "WARN"]
n_hard = len([r for r in report if r[2]])
print("-"*92)
print(f"Hard checks: {n_hard}  |  Hard failures: {len(hard_fail)}  |  Warnings: {len(warns)}")
if hard_fail:
    print("VERDICT: FAIL")
    raise Exception(f"Stage D: {len(hard_fail)} hard assertion(s) failed: {[r[0] for r in hard_fail]}")
print("VERDICT: PASS — conformed layer certified. WS2 complete.")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 8. WS2 complete
# 
# The conformed layer is built **and certified**:
# - **Stage A** (01) — schema validation gate: structure checked, bad rows quarantined with reasons.
# - **Stage B** (02) — reconciliation: source disagreements resolved or flagged, scored 1.000/1.000 vs the oracle.
# - **Stage C** (03) — bitemporal load: point-in-time integrity + working SCD2 version history.
# - **Stage D** (04) — data-quality assertions: referential integrity, envelope, reconciliation, status all certified; raises on hard failure.
# 
# The 7 `conformed_*` tables are the trust boundary's product. **WS3** (Gold Warehouse —
# dimensional star schema) reads these and reshapes them for analytical querying and the
# Power BI hero report.

