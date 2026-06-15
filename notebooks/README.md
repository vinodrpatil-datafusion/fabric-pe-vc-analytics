# Conformed Layer — Build Notebooks (WS2)

PySpark notebooks that build and certify the **conformed layer** of the PE/VC analytics
platform — the trust boundary between raw vendor feeds and everything downstream
(Warehouse, semantic model, AI). See [`../docs/architecture.md`](../docs/architecture.md)
§3 for the design these implement.

The layer is built in four stages, A → D. Each stage's output is observable as Delta
tables in `conformed_lakehouse`; each later stage reads the prior stage's output.

| Stage | Notebook | Does | Key output |
|---|---|---|---|
| **A** | `01_schema_validation.ipynb` | Validates each source feed's *structure* (required columns, non-null, PK uniqueness). Tags and quarantines bad rows **with a reason** instead of dropping them. | `stg_validated_<source>_<entity>` (+ `stg_quarantine_*` when non-empty) |
| **B** | `02_reconciliation.ipynb` | Resolves disagreements between the two external sources (`dealroom`, `capitaliq`) into one version per canonical entity. **Surfaces conflicts rather than silently picking winners.** | `reconciled_<entity>`, `reconciliation_log` |
| **C** | `03_bitemporal_load.ipynb` | Adds point-in-time integrity: `effective_date` (true-in-world) + `ingestion_date` (platform-learned), and a Type-2 SCD envelope (`valid_from`/`valid_to`/`is_current`) for version history. | `conformed_<entity>` (×7) |
| **D** | `04_data_quality_assertions.ipynb` | Post-load gate. Asserts referential integrity, envelope sanity, row-count reconciliation, and status domain; **raises on any hard failure** so bad data can't be promoted. | `dq_assertions_report` |

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

## Running these notebooks

1. **Lakehouses:** the build uses `landing_lakehouse` (raw feeds + reference files) and
   `conformed_lakehouse` (all stage outputs). For each notebook, attach
   **`conformed_lakehouse` as the default** (writes land there) and `landing_lakehouse`
   as a secondary source.
2. **Reference path:** notebooks 02–04 have a `REFERENCE_FILES` parameter set to a
   placeholder ABFS path. Replace the workspace/lakehouse GUIDs with your own tenant's
   (right-click the `reference` folder → Properties to find them). It must end in
   `/Files/landing/reference`.
3. **Order:** run 01 → 02 → 03 → 04. Each depends on the prior stage's tables.

Parameter cells use **placeholder GUIDs** intentionally — no tenant identity is committed.

## Data

All data is **synthetic** (see [`../SYNTHETIC_DATA.md`](../SYNTHETIC_DATA.md)) and labelled
as such. Entity resolution is assumed solved via a `vendor_id_mapping` reference table;
the conformed layer's contribution is validation, reconciliation, and temporal integrity
on top of resolved identity.
