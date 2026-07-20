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

# # WS2 · Notebook 03 — Bitemporal Load
# 
# **Stage C of the conformed build** (`architecture.md` §3.3, principle 1.3) — the final
# step inside the trust boundary. Produces the **conformed entities** every downstream
# consumer (Warehouse, semantic model, AI) reads.
# 
# ### What this stage adds
# 
# Stage B gave us one reconciled version of each entity. Stage C stamps each row with
# **point-in-time integrity** so we can always reproduce *what we knew, when*.
# 
# - **`effective_date`** — when the fact became true **in the real world** (a company's
#   founding, a round's close).
# - **`ingestion_date`** — when **the platform learned** it (the landing timestamp).
#   These two differ constantly in investment data — a round closes in March but is only
#   disclosed in May. Tracking both is what **bitemporal** means: two independent time axes.
# 
# - **SCD2 envelope** — *Slowly Changing Dimension, type 2*: a way to keep history when an
#   attribute changes. Instead of overwriting the old value, we keep the old row **and** add
#   a new one, each tagged with the window it was true. Three columns implement it:
#   - **`valid_from`** — when this version started being the truth.
#   - **`valid_to`** — when it stopped (a high sentinel `9999-12-31` = "still current").
#   - **`is_current`** — `true` on the live version; a query for "now" filters on this.
# 
# ### Temporal pattern per entity (`data_model.md` §3)
# 
# | Entity | Pattern | `effective_date` source |
# |---|---|---|
# | companies, funding_rounds, investments | **bitemporal** | founding / resolved close / round close |
# | investors, people | **Type-2 SCD** | ingestion (no natural business date) |
# | deals, documents | **single-temporal** | ingestion / created_date |
# 
# All seven get the envelope columns so downstream querying is uniform.
# 
# ### Inputs / outputs
# 
# - **Reads:** the 4 `reconciled_*` tables (status + resolved values from Stage B) and the
#   3 `stg_validated_internal_*` tables (people, deals, documents — they skip reconciliation).
# - **Enrichment:** full business attributes pulled from the validated source tables,
#   preferring `dealroom` where both sources carry a row.
# - **Writes:** 7 `conformed_*` Delta tables — the finished trust-boundary product.
# 
# ### Single-snapshot caveat (honest scope)
# 
# We have **one batch** of data, so on the initial load each entity has exactly **one**
# version (`is_current = true`). The SCD2 *machinery* (the merge that closes an old version
# and inserts a new one) is built and correct — and the final cell **demonstrates it** by
# manufacturing a synthetic "data correction" batch and showing an entity gain a second
# version. A real second batch (e.g. monthly vendor refresh) is a future exercise.


# MARKDOWN ********************

# ## 1. Parameters

# CELL ********************

RECONCILED_PREFIX = "reconciled"
VALIDATED_PREFIX  = "stg_validated"
CONFORMED_PREFIX  = "conformed"
SENTINEL = "9999-12-31"            # SCD2 high-date: row is the current/open version
LOW_SENTINEL = "1900-01-01"        # SCD2 genesis date: initial version of an entity with no natural business date

# Same ABFS reference path you used in Notebook 02 (ends in /Files/landing/reference)
REFERENCE_FILES = "abfss://f1f589c3-d0a9-4c55-8dee-b180ff4b4611@onelake.dfs.fabric.microsoft.com/4559f0cc-d5bd-491a-a492-0043526e94e4/Files/landing/reference"

from pyspark.sql import functions as F, Window
print("Stage C parameters set.")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 2. Helpers
# 
# - `read_ref` / `mapping` — the vendor->canonical lookup (same as Stage B).
# - `attach_canonical` — stamp each source row with its canonical ID.
# - `preferred(entity, ...)` — build one enriched row per canonical entity, **preferring
#   dealroom** when both sources have it (so we keep the richest attribute set). This is
#   where full business attributes come from; status + resolved values come from `reconciled_*`.
# - `add_envelope` — append `valid_from` / `valid_to` / `is_current` for the initial load.


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
                .select("vendor_id", "canonical_id"))
    return df.join(m, df[vendor_col] == m["vendor_id"], "left").drop("vendor_id")

def preferred(entity, entity_type, vendor_col):
    """One enriched row per canonical entity, dealroom preferred over capitaliq."""
    dr = attach_canonical(validated("dealroom", entity), entity_type, vendor_col, "dealroom").withColumn("_pref", F.lit(0))
    cq = attach_canonical(validated("capitaliq", entity), entity_type, vendor_col, "capitaliq").withColumn("_pref", F.lit(1))
    u = dr.unionByName(cq, allowMissingColumns=True)
    w = Window.partitionBy("canonical_id").orderBy("_pref")
    return u.withColumn("_rn", F.row_number().over(w)).filter(F.col("_rn") == 1).drop("_rn", "_pref")

def add_envelope(df, effective_col):
    return (df.withColumn("valid_from", F.col(effective_col))
              .withColumn("valid_to", F.lit(SENTINEL))
              .withColumn("is_current", F.lit(True)))

def add_envelope_low(df):
    """Envelope for entities with no natural business date (investors, people).
    valid_from uses a low sentinel, not ingestion_date — ingestion_date is 'now' at
    generator run time for every row, so using it as valid_from would put the window
    after every historical fact date and break point-in-time joins against it."""
    return (df.withColumn("valid_from", F.lit(LOW_SENTINEL))
              .withColumn("valid_to", F.lit(SENTINEL))
              .withColumn("is_current", F.lit(True)))

# canonical company lookup for FK remapping
ccm = mapping.filter(F.col("entity_type") == "company").select(
        F.col("source_system").alias("c_src"), F.col("vendor_id").alias("c_vid"), F.col("canonical_id").alias("company_id"))
print("Helpers ready.")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 3. Companies — bitemporal · effective = founded_date
# 
# Enrich from preferred source (sector, founded_date, description), carry
# `reconciliation_status` from `reconciled_companies`, stamp the two time axes and envelope.


# CELL ********************

enr = preferred("companies", "company", "vendor_company_id")
rec = spark.read.table(f"{RECONCILED_PREFIX}_companies").select(
        F.col("company_id").alias("canonical_id"), "reconciliation_status")
co = (enr.join(rec, "canonical_id", "left")
         .withColumn("effective_date", F.col("founded_date"))
         .withColumnRenamed("_ingestion_ts", "ingestion_date")
         .withColumnRenamed("canonical_id", "company_id")
         .select("company_id", "legal_name", "sector_taxonomy", "country", "description",
                 "effective_date", "ingestion_date", "reconciliation_status"))
conformed_companies = add_envelope(co, "effective_date")
print("companies:", conformed_companies.count())


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 4. Funding rounds — bitemporal · effective = resolved close date
# 
# `announced_date` and `amount_raised` come **resolved** from Stage B (earliest date, flagged
# amounts). `company_id` is remapped from the vendor company ID to canonical.


# CELL ********************

enr = preferred("funding_rounds", "funding_round", "vendor_round_id")
enr = enr.join(ccm, (enr["vendor_company_id"] == ccm["c_vid"]), "left").drop("c_vid", "c_src")
rec = spark.read.table(f"{RECONCILED_PREFIX}_funding_rounds").select(
        F.col("round_id").alias("canonical_id"),
        F.col("announced_date").alias("announced_resolved"),
        F.col("amount_raised").alias("amount_resolved"), "reconciliation_status")
fr = (enr.join(rec, "canonical_id", "left")
         .withColumn("effective_date", F.col("announced_resolved"))
         .withColumnRenamed("_ingestion_ts", "ingestion_date")
         .withColumnRenamed("canonical_id", "round_id")
         .select("round_id", "company_id", "round_type",
                 F.col("announced_resolved").alias("announced_date"),
                 F.col("amount_resolved").alias("amount_raised"), "currency", "instrument_type",
                 "pre_money_valuation", "post_money_valuation",
                 "effective_date", "ingestion_date", "reconciliation_status"))
conformed_funding_rounds = add_envelope(fr, "effective_date")
print("funding_rounds:", conformed_funding_rounds.count())


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 5. Investors — Type-2 SCD · effective = ingestion_date
# 
# Investors carry no natural business date, so `effective_date = ingestion_date`. `fund_size`
# comes resolved from Stage B.


# CELL ********************

enr = preferred("investors", "investor", "vendor_investor_id")
rec = spark.read.table(f"{RECONCILED_PREFIX}_investors").select(
        F.col("investor_id").alias("canonical_id"),
        F.col("fund_size").alias("fund_resolved"), "reconciliation_status")
iv = (enr.join(rec, "canonical_id", "left")
         .withColumnRenamed("_ingestion_ts", "ingestion_date")
         .withColumn("effective_date", F.col("ingestion_date"))
         .withColumnRenamed("canonical_id", "investor_id")
         .select("investor_id", "investor_type", "legal_name", "vintage_year",
                 F.col("fund_resolved").alias("fund_size"),
                 "geographic_focus", "sector_focus", "stage_focus",
                 "effective_date", "ingestion_date", "reconciliation_status"))
conformed_investors = add_envelope_low(iv)
print("investors:", conformed_investors.count())


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 6. Investments — bitemporal · effective = round close (fallback ingestion)
# 
# The central analytical asset. All three FKs (investor, round, company) are remapped to
# canonical. `effective_date` is the **resolved close date of the round** the investment
# participated in — joined from the conformed rounds we just built — falling back to
# ingestion if a round is missing.


# CELL ********************

enr = preferred("investments", "investment", "vendor_investment_id")
rcm = mapping.filter(F.col("entity_type") == "funding_round").select(
        F.col("source_system").alias("r_src"), F.col("vendor_id").alias("r_vid"), F.col("canonical_id").alias("round_id"))
icm = mapping.filter(F.col("entity_type") == "investor").select(
        F.col("source_system").alias("i_src"), F.col("vendor_id").alias("i_vid"), F.col("canonical_id").alias("investor_id"))
enr = (enr.join(rcm, (enr["vendor_round_id"] == rcm["r_vid"]), "left").drop("r_vid", "r_src")
          .join(icm, (enr["vendor_investor_id"] == icm["i_vid"]), "left").drop("i_vid", "i_src")
          .join(ccm, (enr["vendor_company_id"] == ccm["c_vid"]), "left").drop("c_vid", "c_src"))
rec = spark.read.table(f"{RECONCILED_PREFIX}_investments").select(
        F.col("investment_id").alias("canonical_id"), "reconciliation_status")
round_eff = conformed_funding_rounds.select(F.col("round_id").alias("re_round"),
                                            F.col("announced_date").alias("round_close"))
inv = (enr.join(rec, "canonical_id", "left")
          .join(round_eff, enr["round_id"] == round_eff["re_round"], "left").drop("re_round")
          .withColumnRenamed("_ingestion_ts", "ingestion_date"))
inv = (inv.withColumn("effective_date", F.coalesce(F.col("round_close"), F.col("ingestion_date")))
          .withColumnRenamed("canonical_id", "investment_id")
          .select("investment_id", "investor_id", "round_id", "company_id",
                  "participation_amount", "is_lead", "board_seat_taken",
                  "exit_date", "exit_type", "realised_return_multiple",
                  "effective_date", "ingestion_date", "reconciliation_status"))
conformed_investments = add_envelope(inv, "effective_date")
print("investments:", conformed_investments.count())


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 7. People · Deals · Documents — single-source pass-through
# 
# These come from the internal feed only, so they skip reconciliation
# (`reconciliation_status = clean`). People/deals use ingestion as `effective_date`;
# documents use `created_date`. All still get the envelope for uniform querying.


# CELL ********************

pe = (validated("internal", "people")
        .withColumnRenamed("_ingestion_ts", "ingestion_date")
        .withColumn("effective_date", F.col("ingestion_date"))
        .withColumn("reconciliation_status", F.lit("clean"))
        .select("person_id", "name", "current_affiliations", "historical_affiliations", "education",
                "effective_date", "ingestion_date", "reconciliation_status"))
conformed_people = add_envelope_low(pe)

de = (validated("internal", "deals")
        .withColumnRenamed("_ingestion_ts", "ingestion_date")
        .withColumn("effective_date", F.col("ingestion_date"))
        .withColumn("reconciliation_status", F.lit("clean"))
        .select("deal_id", "company_id", "stage", "stage_history", "analyst_owner", "partner_owner",
                "proposed_check_size", "target_round_id", "ic_date", "ic_outcome",
                "effective_date", "ingestion_date", "reconciliation_status"))
conformed_deals = add_envelope(de, "effective_date")

do = (validated("internal", "documents")
        .withColumnRenamed("_ingestion_ts", "ingestion_date")
        .withColumnRenamed("created_date", "effective_date")
        .withColumn("reconciliation_status", F.lit("clean"))
        .select("document_id", "document_type", "subject_company_ids", "author_person_id",
                "effective_date", "ingestion_date", "sensitivity_label", "reconciliation_status"))
conformed_documents = add_envelope(do, "effective_date")
print("people / deals / documents:", conformed_people.count(), conformed_deals.count(), conformed_documents.count())


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 8. Write all seven conformed tables + verify
# 
# Each writes to `conformed_lakehouse`. Verify row counts and that the two time axes +
# envelope populate with no nulls.


# CELL ********************

conformed = {
    "companies": conformed_companies, "funding_rounds": conformed_funding_rounds,
    "investors": conformed_investors, "investments": conformed_investments,
    "people": conformed_people, "deals": conformed_deals, "documents": conformed_documents,
}
print(f"{'table':28s} {'rows':>6s} {'eff_null':>9s} {'ing_null':>9s}")
print("-"*56)
for name, df in conformed.items():
    df.write.mode("overwrite").option("overwriteSchema", "true").format("delta").saveAsTable(f"{CONFORMED_PREFIX}_{name}")
    eff_null = df.filter(F.col("effective_date").isNull()).count()
    ing_null = df.filter(F.col("ingestion_date").isNull()).count()
    print(f"{(CONFORMED_PREFIX + '_' + name):28s} {df.count():6d} {eff_null:9d} {ing_null:9d}")
print("\nAll seven conformed tables written.")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 9. The SCD2 merge — how a new version is recorded
# 
# `scd2_merge` applies an incoming batch to a conformed table using **Delta MERGE** (an
# update-or-insert in one atomic operation). For any key whose tracked attributes changed,
# it does two things:
# 1. **Closes** the existing current row — sets `valid_to` to the change date and
#    `is_current = false` (history is preserved, not overwritten).
# 2. **Inserts** the new version — `valid_from` = change date, `valid_to` = sentinel,
#    `is_current = true`.
# 
# This uses the standard Delta SCD2 pattern: a *staged* frame where rows destined to insert
# carry a `NULL` merge-key (so they can't match and are inserted), while the same keys also
# appear with their real key (to match and close the old row).


# CELL ********************

from delta.tables import DeltaTable

def scd2_merge(table_name, updates, key_col, compare_cols, change_date_col):
    """Type-2 SCD merge. `updates` has the same business columns as the table (no envelope)."""
    tgt = DeltaTable.forName(spark, table_name)
    cur = tgt.toDF().filter(F.col("is_current") == True)

    cond = None
    for c in compare_cols:
        diff = F.col(f"u.{c}") != F.col(f"t.{c}")
        cond = diff if cond is None else (cond | diff)
    changed = (updates.alias("u").join(cur.alias("t"), F.col(f"u.{key_col}") == F.col(f"t.{key_col}"))
               .where(cond).select("u.*"))

    staged_insert = changed.withColumn("_mergeKey", F.lit(None).cast("string"))
    staged_close  = updates.withColumn("_mergeKey", F.col(key_col))
    staged = staged_insert.unionByName(staged_close)

    insert_vals = {c: f"staged.{c}" for c in updates.columns}
    insert_vals.update({"valid_from": f"staged.{change_date_col}", "valid_to": f"'{SENTINEL}'", "is_current": "true"})

    (tgt.alias("t").merge(staged.alias("staged"),
        f"t.{key_col} = staged._mergeKey AND t.is_current = true")
        .whenMatchedUpdate(set={"is_current": "false", "valid_to": f"staged.{change_date_col}"})
        .whenNotMatchedInsert(values=insert_vals)
        .execute())
    print(f"scd2_merge applied to {table_name}: {changed.count()} version change(s)")

print("scd2_merge defined.")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 10. Demonstrate versioning (the proof)
# 
# We have one batch, so nothing has changed yet. To prove the machinery works, we manufacture
# a synthetic **data correction**: take one real company and change its `legal_name` (as if a
# later vendor refresh corrected it), with a new `effective_date`. After `scd2_merge`, that
# company should have **two rows** — the old one closed (`is_current = false`, `valid_to` set),
# the new one open (`is_current = true`).


# CELL ********************

target_id = conformed_companies.select("company_id").first()["company_id"]
print(f"Correcting company {target_id} ...")

base = (spark.read.table(f"{CONFORMED_PREFIX}_companies")
        .filter((F.col("company_id") == target_id) & (F.col("is_current") == True))
        .drop("valid_from", "valid_to", "is_current"))
batch2 = (base.withColumn("legal_name", F.concat(F.col("legal_name"), F.lit(" (corrected)")))
              .withColumn("effective_date", F.lit("2026-01-01")))

scd2_merge(f"{CONFORMED_PREFIX}_companies", batch2, "company_id", ["legal_name"], "effective_date")

print("\nVersions of this company after merge:")
(spark.read.table(f"{CONFORMED_PREFIX}_companies")
    .filter(F.col("company_id") == target_id)
    .select("company_id", "legal_name", "valid_from", "valid_to", "is_current")
    .orderBy("valid_from").show(truncate=False))


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## 11. Outputs — WS2 nearly complete (pending Stage D)
# 
# Written to `conformed_lakehouse`:
# - 7 `conformed_*` tables — full entities with `effective_date`, `ingestion_date`,
#   `reconciliation_status`, and the SCD2 envelope. These are the trust boundary's product.
# 
# **This completes the conformed *load*.** Stage D (Notebook 04 — data quality assertions)
# adds the final gate: post-load checks (referential integrity across the conformed FKs,
# envelope sanity, row-count reconciliation) that fail loudly if anything is wrong. After
# that, WS2 is done and WS3 (Gold Warehouse star schema) reads these conformed tables.
# 
# **Scope reminder:** initial load = one version per entity; the cell above proves the SCD2
# merge records a second version correctly when a change arrives.

