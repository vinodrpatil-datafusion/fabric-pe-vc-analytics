# Conformed & Gold — Build Notebooks (WS2 + WS3)

PySpark notebooks that build and certify the **conformed layer** (WS2) and the **Gold
star schema** (WS3) of the PE/VC analytics platform. WS2 is the trust boundary between
raw vendor feeds and everything downstream; WS3 reshapes it for analytical querying and
the DirectLake semantic model. See [`../docs/architecture.md`](../docs/architecture.md)
§3 for the design WS2 implements, and DD-15 in
[`../docs/design_decisions.md`](../docs/design_decisions.md) for the Gold grain.

WS2 is built in four stages, A → D, output as Delta tables in `conformed_lakehouse`.
WS3 adds a fifth stage, E, output as Delta tables in `gold_lakehouse`. Each stage reads
the prior stage's output.

| Stage | Notebook | Does | Key output |
|---|---|---|---|
| **A** | `01_schema_validation.ipynb` | Validates each source feed's *structure* (required columns, non-null, PK uniqueness). Tags and quarantines bad rows **with a reason** instead of dropping them. | `stg_validated_<source>_<entity>` (+ `stg_quarantine_*` when non-empty) |
| **B** | `02_reconciliation.ipynb` | Resolves disagreements between the two external sources (`dealroom`, `capitaliq`) into one version per canonical entity. **Surfaces conflicts rather than silently picking winners.** | `reconciled_<entity>`, `reconciliation_log` |
| **C** | `03_bitemporal_load.ipynb` | Adds point-in-time integrity: `effective_date` (true-in-world) + `ingestion_date` (platform-learned), and a Type-2 SCD envelope (`valid_from`/`valid_to`/`is_current`) for version history. | `conformed_<entity>` (×7) |
| **D** | `04_data_quality_assertions.ipynb` | Post-load gate. Asserts referential integrity, envelope sanity, row-count reconciliation, and status domain; **raises on any hard failure** so bad data can't be promoted. | `dq_assertions_report` |
| **E** | `05_gold_star_schema.ipynb` | Reshapes certified `conformed_*` tables into one fact (`fact_investment`, investment grain) + three dimensions (`dim_company`, `dim_investor` — both Type-2; `dim_date`), point-in-time joined. Applies V-Order. Certifies with the same hard-fail assertion pattern as Stage D. | `gold_dim_date`, `gold_dim_company`, `gold_dim_investor`, `gold_fact_investment`, `gold_dq_assertions_report` |

## Reconciliation policy (Stage B)

| Conflict | Rule | Status | Logged as |
|---|---|---|---|
| temporal — `announced_date` > 30 days apart | auto-resolve to **earliest** | `conflict_resolved` | `auto_resolved` |
| value — `amount_raised` / `fund_size` > 5% apart | **flag** (money is not auto-decided) | `conflict_flagged` | `flagged_for_review` |
| existence — entity in one source, *company covered by both* | **flag** (genuine dispute) | `conflict_flagged` | `flagged_for_review` |
| existence — entity in one source, *coverage gap* | auto-resolve, take available | `conflict_resolved` | `auto_resolved` |
| sources agree | — | `clean` | — |

Stage B is **scored against an oracle**: the synthetic data generator (WS1) emits an
`expected_conflicts` ledger of every conflict it engineered. Notebook 02's final cells
join the produced `reconciliation_log` against that ledger and report recall + precision
(current build: **1.000 / 1.000**, 666/666 conflicts matched).

> **Scope note:** the oracle and the reconciliation share the same conflict definitions
> by design, so this is a **spec-conformance / regression check** — it proves the
> implementation faithfully applies the agreed rules and catches drift. It is not a claim
> that the algorithm discovers unknown conflicts.

## Bitemporal / SCD2 (Stage C)

- **Bitemporal** = two independent time axes per fact: `effective_date` (when it became
  true in the world) and `ingestion_date` (when the platform learned it). They differ
  routinely in investment data because of disclosure lag.
- **Type-2 SCD** = on a change, the old row is kept and closed (`valid_to` set,
  `is_current = false`) and a new version inserted (`is_current = true`) — history is
  preserved, not overwritten. Implemented via Delta `MERGE`.

> **Single-snapshot caveat:** the synthetic dataset is one batch, so the initial load has
> one version per entity. Notebook 03's final cell **demonstrates** the SCD2 merge by
> applying a synthetic "data correction" and showing an entity gain a second version. A
> real recurring second batch is a future exercise.

## Gold star schema (Stage E)

One fact, three dimensions — grain and every trade-off decided in DD-15 before this
notebook was written:

- **`fact_investment`** — one row per current `investment_id` (~848 in the sample
  dataset). Round attributes (`round_type`, `instrument_type`, valuations) are
  degenerate columns on the fact; there's no separate `dim_round`.
- **`dim_company`**, **`dim_investor`** — both Type-2 (SCD2), carried forward from the
  conformed layer's existing `valid_from`/`valid_to`/`is_current` envelope.
- **`dim_date`** — generated calendar, day grain.
- **Point-in-time join:** each fact row's `company_sk`/`investor_sk` is resolved to the
  dimension version valid **at the investment's `effective_date`**, not whatever is
  current today — see notebook 05 §2/§6 (`pit_join`) and DD-15.
- **`sector_group`** doesn't exist in the conformed data (only the multi-valued
  `sector_taxonomy` array does) — it's derived in the notebook via a small taxonomy
  lookup mirroring `data-generator/pevc_generator/reference.py`'s `SECTOR_GROUPS`.
  Documented shortcut, not a claim that this is how a real vendor feed would deliver it.

> **No fund-performance-snapshot fact.** DD-15 explains why: the conformed layer has no
> periodic valuation source (only cost basis pre-exit, `realised_return_multiple`
> post-exit — ~35% of sample investments have exited). Fund/vintage rollups are DAX
> measures over `fact_investment` in S2, and any "NAV" measure S2 defines must be
> documented as a **proxy**, not a real fund NAV.

## Running these notebooks

1. **Lakehouses:** the build uses `landing_lakehouse` (raw feeds + reference files),
   `conformed_lakehouse` (WS2 stage outputs), and `gold_lakehouse` (WS3/Stage E
   output). For notebooks 01–04, attach **`conformed_lakehouse` as the default**
   (writes land there) and `landing_lakehouse` as a secondary source. For notebook 05,
   attach **`gold_lakehouse` as the default** and `conformed_lakehouse` as a secondary
   source — it reads no landing files directly.
2. **Reference path:** notebooks 02–04 have a `REFERENCE_FILES` parameter set to a
   placeholder ABFS path. Replace the workspace/lakehouse GUIDs with your own tenant's
   (right-click the `reference` folder → Properties to find them). It must end in
   `/Files/landing/reference`. Notebook 05 has no `REFERENCE_FILES` parameter — it only
   reads `conformed_*` tables.
3. **Order:** run 01 → 02 → 03 → 04 → 05. Each depends on the prior stage's tables.
4. **Cross-lakehouse reads on schema-enabled lakehouses:** if `conformed_lakehouse` has
   schemas enabled (tables shown under `Tables > dbo` rather than directly under
   `Tables` in the Lakehouse explorer), a secondary-attached lakehouse's tables aren't
   resolvable by bare name from the notebook's default catalog context. Notebook 05's
   `conformed()` helper qualifies reads as `conformed_lakehouse.dbo.<table>` for exactly
   this reason — if you hit `TABLE_OR_VIEW_NOT_FOUND` on an otherwise-correctly-attached
   lakehouse, this is the first thing to check.

Parameter cells use **placeholder GUIDs** intentionally — no tenant identity is committed.

## Data

All data is **synthetic** (see [`../SYNTHETIC_DATA.md`](../SYNTHETIC_DATA.md)) and labelled
as such. Entity resolution is assumed solved via a `vendor_id_mapping` reference table;
the conformed layer's contribution is validation, reconciliation, and temporal integrity
on top of resolved identity.
