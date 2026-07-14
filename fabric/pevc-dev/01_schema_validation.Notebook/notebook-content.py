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
# META         },
# META         {
# META           "id": "4559f0cc-d5bd-491a-a492-0043526e94e4"
# META         }
# META       ]
# META     }
# META   }
# META }

# MARKDOWN ********************

# # WS2 · Notebook 01 — Schema validation
# 
# **Stage A of the conformed build** (`architecture.md` §3.2).
# 
# This notebook is the **front gate** of the trust boundary. Raw vendor feeds land
# in the ingestion zone with no checks. Before *anything* downstream touches them,
# this notebook verifies each row is *structurally* valid — right columns, right
# types, required fields present, keys resolvable.
# 
# - **Valid rows** pass through to a `validated_*` table that Stage B (reconciliation) reads.
# - **Invalid rows** are routed to a `quarantine_*` table — they are *not* dropped silently and they do *not* reach reconciliation.
# 
# > Structural validity only. This stage does **not** judge whether two sources
# > *agree* — that is reconciliation's job (Stage B). A round where the source
# > failed to name a lead investor is structurally valid (empty list is allowed);
# > a round missing its `amount_raised` column entirely is not.
# 
# Why this matters: principle 1.1 says *data quality is enforced upstream of AI*.
# The conformed layer is the trust boundary, and this is its first line of defence.


# MARKDOWN ********************

# ## 1. Setup and parameters
# 
# **Before running, you need (in your Fabric trial):**
# 
# 1. A workspace.
# 2. Two lakehouses in it:
#    - `landing_lakehouse` — the raw zone.
#    - `conformed_lakehouse` — where validated/reconciled/conformed tables live.
# 3. The WS1 sample data uploaded into `landing_lakehouse`:
#    - In the Fabric UI, open `landing_lakehouse` → **Files** → upload the
#      `sample-data/landing/` folder so you get
#      `Files/landing/dealroom/...`, `Files/landing/capitaliq/...`, `Files/landing/internal/...`.
#    - Upload `sample-data/reference/` too → `Files/reference/...` (used in later stages).
# 4. **Attach this notebook to `conformed_lakehouse`** as the default lakehouse
#    (Explorer panel → add lakehouse), and **also add `landing_lakehouse`** as a
#    second lakehouse so we can read from it.
# 
# > Architecture note: production puts landing and conformed in *separate
# > workspaces* with distinct RBAC (principle 1.5). For the trial build we use two
# > lakehouses in one workspace — same separation of concerns, far less setup.
# 
# The parameters below assume those names. Change them if yours differ.


# CELL ********************

# Parameters — adjust if your lakehouse names differ
LANDING_LAKEHOUSE   = "landing_lakehouse"
CONFORMED_LAKEHOUSE = "conformed_lakehouse"

# Path to the landing files inside the landing lakehouse.
# In Fabric, an attached lakehouse exposes its Files at /lakehouse/<name>/Files,
# but the robust cross-lakehouse way is the abfss path shown in the lakehouse
# properties. We use the relative Files path of the *default* attached lakehouse
# where possible, and fall back to the mount path.
LANDING_FILES = f"abfss://f1f589c3-d0a9-4c55-8dee-b180ff4b4611@onelake.dfs.fabric.microsoft.com/4559f0cc-d5bd-491a-a492-0043526e94e4/Files/landing"        # relative to the landing lakehouse Files root

# Staging schema prefix for outputs of this stage (written to conformed lakehouse Tables)
VALIDATED_PREFIX  = "stg_validated"     # e.g. stg_validated_dealroom_companies
QUARANTINE_PREFIX = "stg_quarantine"    # e.g. stg_quarantine_dealroom_companies

print("Landing lakehouse:  ", LANDING_LAKEHOUSE)
print("Conformed lakehouse:", CONFORMED_LAKEHOUSE)


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 2. What we validate, and against what
# 
# We declare an **expected schema** per entity: which columns must exist, which
# must be non-null, and the entity's primary key (for in-source uniqueness). This
# is the contract a feed must satisfy to pass the gate.
# 
# The four external entities (`companies`, `funding_rounds`, `investors`,
# `investments`) arrive from **two** sources (`dealroom`, `capitaliq`). The three
# internal entities (`people`, `deals`, `documents`) arrive from one source
# (`internal`). We validate every (source, entity) feed independently.
# 
# Nested attributes (e.g. `sector_taxonomy`) arrive as **JSON strings** in the raw
# feed — that is realistic vendor delivery. Stage A only checks the column is
# present and (where required) non-null; parsing JSON is a later concern.


# CELL ********************

# Expected schema per entity: required columns, non-null columns, primary key.
# Lineage columns (_record_id, _source_system, ...) are required on every feed.
LINEAGE_REQUIRED = ["_record_id", "_source_system", "_ingestion_ts", "_batch_id", "_is_synthetic"]

SCHEMAS = {
    "companies": {
        "required": ["vendor_company_id", "legal_name", "sector_taxonomy", "founded_date", "country"],
        "non_null": ["vendor_company_id", "legal_name", "country"],
        "pk": "vendor_company_id",
    },
    "funding_rounds": {
        "required": ["vendor_round_id", "vendor_company_id", "round_type", "announced_date",
                     "amount_raised", "currency", "instrument_type", "lead_investor_vendor_ids"],
        "non_null": ["vendor_round_id", "vendor_company_id", "round_type", "announced_date",
                     "amount_raised", "currency"],
        "pk": "vendor_round_id",
    },
    "investors": {
        "required": ["vendor_investor_id", "investor_type", "legal_name",
                     "geographic_focus", "sector_focus", "stage_focus"],
        "non_null": ["vendor_investor_id", "investor_type", "legal_name"],
        "pk": "vendor_investor_id",
    },
    "investments": {
        "required": ["vendor_investment_id", "vendor_investor_id", "vendor_round_id",
                     "vendor_company_id", "is_lead"],
        "non_null": ["vendor_investment_id", "vendor_investor_id", "vendor_round_id", "vendor_company_id"],
        "pk": "vendor_investment_id",
    },
    "people": {
        "required": ["person_id", "name", "current_affiliations", "historical_affiliations"],
        "non_null": ["person_id", "name"],
        "pk": "person_id",
    },
    "deals": {
        "required": ["deal_id", "company_id", "stage", "stage_history"],
        "non_null": ["deal_id", "company_id", "stage"],
        "pk": "deal_id",
    },
    "documents": {
        "required": ["document_id", "document_type", "subject_company_ids",
                     "created_date", "sensitivity_label"],
        "non_null": ["document_id", "document_type", "created_date"],
        "pk": "document_id",
    },
}

# Which (source, entity) feeds exist
FEEDS = (
    [("dealroom", e)  for e in ["companies", "funding_rounds", "investors", "investments"]]
    + [("capitaliq", e) for e in ["companies", "funding_rounds", "investors", "investments"]]
    + [("internal", e)  for e in ["people", "deals", "documents"]]
)
print(f"{len(FEEDS)} feeds to validate")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 3. The validation function
# 
# For one feed we run four checks, in order:
# 
# 1. **Column presence** — every `required` column (plus lineage columns) exists.
#    If a *required column is missing entirely*, the feed is structurally broken;
#    we fail the whole feed loudly rather than quarantine row-by-row.
# 2. **Non-null** — `non_null` columns must have a value on each row. Rows that
#    violate this get tagged.
# 3. **Primary-key non-null & unique** — the PK must be present and unique within
#    the source. Duplicate or null PKs get tagged.
# 4. **Tag, don't drop** — each row gets `_valid` (bool) and `_quarantine_reason`
#    (string). We then split: valid rows → `validated_*`, invalid → `quarantine_*`.
# 
# This is the "route failures to a quarantine table; downstream stages do not see
# invalid rows" pattern from `architecture.md` §3.2 Stage A.


# CELL ********************

from pyspark.sql import functions as F, Window

def validate_feed(df, entity):
    """Return (valid_df, quarantine_df, missing_columns)."""
    spec = SCHEMAS[entity]

    # --- Check 1: column presence (structural; fail loud if a required col is absent) ---
    have = set(df.columns)
    need = set(spec["required"]) | set(LINEAGE_REQUIRED)
    missing = sorted(need - have)
    if missing:
        # whole-feed structural failure — return everything to quarantine with the reason
        q = df.withColumn("_valid", F.lit(False)) \
              .withColumn("_quarantine_reason", F.lit("missing_columns: " + ", ".join(missing)))
        empty = df.limit(0).withColumn("_valid", F.lit(True)).withColumn("_quarantine_reason", F.lit(None).cast("string"))
        return empty, q, missing

    # --- Build a per-row reason string, accumulating failures ---
    reason = F.lit("")

    # Check 2: non-null columns
    for c in spec["non_null"]:
        reason = F.when(F.col(c).isNull() | (F.trim(F.col(c).cast("string")) == ""),
                        F.concat(reason, F.lit(f"null:{c};"))).otherwise(reason)

    # Check 3a: PK non-null
    pk = spec["pk"]
    reason = F.when(F.col(pk).isNull(), F.concat(reason, F.lit(f"null_pk:{pk};"))).otherwise(reason)

    # Check 3b: PK uniqueness within the feed
    w = Window.partitionBy(pk)
    df = df.withColumn("_pk_count", F.count(F.lit(1)).over(w))
    reason = F.when(F.col("_pk_count") > 1, F.concat(reason, F.lit(f"dup_pk:{pk};"))).otherwise(reason)

    df = df.withColumn("_quarantine_reason", F.when(reason == "", F.lit(None).cast("string")).otherwise(reason)) \
           .withColumn("_valid", F.col("_quarantine_reason").isNull()) \
           .drop("_pk_count")

    valid_df = df.filter(F.col("_valid"))
    quarantine_df = df.filter(~F.col("_valid"))
    return valid_df, quarantine_df, []


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 4. Reading a landing feed
# 
# Each feed is a folder of Parquet (or CSV) under `Files/landing/<source>/<entity>`.
# `spark.read` handles a folder of part-files transparently. We try Parquet first
# (what the generator produces with `pyarrow`), then CSV as a fallback.
# 
# > If you uploaded the files exactly as `sample-data/landing/<source>/<entity>.parquet`,
# > the path below resolves. If your upload nested them differently, adjust
# > `LANDING_FILES`.


# CELL ********************

def read_landing(source, entity):
    base = f"{LANDING_FILES}/{source}/{entity}"
    # A single file or a folder both work; try parquet then csv
    for fmt, path in [("parquet", base + ".parquet"), ("parquet", base),
                      ("csv", base + ".csv")]:
        try:
            if fmt == "parquet":
                return spark.read.parquet(path)
            else:
                return spark.read.option("header", True).option("inferSchema", True).csv(path)
        except Exception:
            continue
    raise FileNotFoundError(f"Could not read landing feed for {source}/{entity} under {base}")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 5. Run validation across all feeds
# 
# We loop every (source, entity), validate, and write two Delta tables to the
# **conformed** lakehouse:
# 
# - `stg_validated_<source>_<entity>` — clean rows for Stage B.
# - `stg_quarantine_<source>_<entity>` — rejected rows, written **only if non-empty**.
# 
# Writing Delta (not just filtering in memory) is deliberate: each stage's output
# is **independently observable** (§3.2). You can open the staging tables in the
# SQL endpoint and see exactly what passed and what didn't.


# CELL ********************

from pyspark.sql import functions as F

summary = []
for source, entity in FEEDS:
    df = read_landing(source, entity)
    n_in = df.count()
    valid_df, quarantine_df, missing = validate_feed(df, entity)
    n_valid = valid_df.count()
    n_quar = quarantine_df.count()

    vname = f"{VALIDATED_PREFIX}_{source}_{entity}"
    qname = f"{QUARANTINE_PREFIX}_{source}_{entity}"

    valid_df.write.mode("overwrite").format("delta").saveAsTable(vname)
    if n_quar > 0:
        quarantine_df.write.mode("overwrite").format("delta").saveAsTable(qname)

    status = "STRUCTURAL FAIL" if missing else ("OK" if n_quar == 0 else "QUARANTINED ROWS")
    summary.append((source, entity, n_in, n_valid, n_quar, status))
    print(f"{source:9s} {entity:15s} in={n_in:5d} valid={n_valid:5d} quar={n_quar:4d}  {status}")

print("\nValidation complete.")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 6. Validation summary
# 
# A compact table you can eyeball. With the WS1 sample, expect **zero quarantined
# rows** — the generator produces structurally valid feeds (the *conflicts* it
# injects are cross-source disagreements, which are reconciliation's problem, not
# schema violations). An all-OK run means the gate is working and passing clean
# input through.
# 
# To prove the gate actually catches problems, the optional cell at the end injects
# a broken row and re-validates one feed.


# CELL ********************

import pandas as pd
sdf = pd.DataFrame(summary, columns=["source", "entity", "rows_in", "valid", "quarantined", "status"])
print(sdf.to_string(index=False))
print()
total_in = sdf["rows_in"].sum(); total_q = sdf["quarantined"].sum()
print(f"Total rows in: {total_in}   quarantined: {total_q}   pass-through: {total_in - total_q}")
if total_q == 0:
    print("\nAll feeds structurally valid. Gate is in place; nothing rejected. Proceed to Stage B (reconciliation).")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 7. (Optional) Prove the quarantine works
# 
# The sample data is clean, so quarantine is empty — which can feel like the check
# "did nothing". This cell deliberately corrupts a couple of rows (nulls the
# primary key, blanks a required field) and re-validates, so you can *see*
# rejected rows land in quarantine with a reason. It does not write anything.


# CELL ********************

from pyspark.sql import functions as F

demo = read_landing("dealroom", "companies")
# Corrupt: null the PK on one row, blank legal_name on another
ids = [r["vendor_company_id"] for r in demo.select("vendor_company_id").limit(2).collect()]
demo_bad = demo.withColumn(
    "vendor_company_id",
    F.when(F.col("vendor_company_id") == ids[0], F.lit(None)).otherwise(F.col("vendor_company_id"))
).withColumn(
    "legal_name",
    F.when(F.col("vendor_company_id") == ids[1], F.lit("")).otherwise(F.col("legal_name"))
)

v, q, _ = validate_feed(demo_bad, "companies")
print(f"valid={v.count()}  quarantined={q.count()}  (expected ~2 quarantined)")
q.select("vendor_company_id", "legal_name", "_quarantine_reason").show(5, truncate=False)


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
