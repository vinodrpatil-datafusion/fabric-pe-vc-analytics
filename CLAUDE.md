# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A Microsoft Fabric reference architecture for PE/VC investment analytics. It is a portfolio/demonstration project — not a production system. The repo contains:

- **`docs/`** — Architecture, data model, design decisions, governance (the canonical design authority)
- **`data-generator/`** — Python package that produces synthetic multi-source landing feeds
- **`sample-data/`** — Committed output from the generator (`seed=42`, `scale=small`)
- **`infrastructure/`** — Fabric workspace layout and deployment pipeline design docs

The Fabric workspaces, notebooks, pipelines, and semantic models referenced in docs are implemented in a live Fabric trial tenant. This repo tracks the code artefacts and design documents; the Fabric items themselves are managed through Fabric's Git integration.

## Data-generator commands

```bash
cd data-generator
pip install -r requirements.txt          # numpy, pandas, pyarrow

python generate.py --scale small --seed 42 --output ../sample-data
python validate_output.py
```

The generator writes **Parquet** when `pyarrow` is installed (required for Fabric shortcuts), otherwise CSV. Always regenerate with pyarrow installed.

Scale options: `small` (~1.2 MB), `medium` (~5 MB), `large` (~16 MB).

## Generator architecture

The generator models data flow as: **canonical oracle → per-source projections with controlled conflicts → landing files**.

| Module | Responsibility |
|---|---|
| `canonical.py` | Generates the "real world" ground truth for all entities |
| `sources.py` | Projects the canonical data into per-source feeds (dealroom, capitaliq) with noise and coverage draws |
| `conflicts.py` | Derives the `expected_conflicts` ledger — the oracle that WS2 reconciliation is scored against |
| `internal.py` | Generates internal-only feeds: people, deals, documents |
| `reference.py` | Vocabularies and `SOURCE_PROFILES` (tune conflict rates here) |
| `lineage.py` | Attaches landing metadata columns to every row |
| `io_utils.py` | Parquet/CSV writer; handles JSON-serialised nested columns |
| `names.py` | Curated PE/VC name banks (no faker dependency) |

To tune conflict rates, edit `SOURCE_PROFILES` in `reference.py`, then re-run `validate_output.py` to see the resulting rates.

## Key domain concepts

**Bitemporal modelling:** Every time-sensitive entity carries two dates: `effective_date` (when the fact became true in the world) and `ingestion_date` (when it became known to the platform). The landing feeds carry only source-reported dates (`announced_date`, `founded_date`); the conformed layer assigns `effective_date` and `ingestion_date` during Stage C load. This distinction matters — a round announced in March 2025 but closed in January 2025 must be queryable correctly for any historical point.

**Reconciliation conflict types** (matching `reconciliation_log.conflict_type`):
- `value_disagreement` — sources disagree on an attribute value (amount, lead investor)
- `temporal_disagreement` — sources report different dates for the same event
- `existence_disagreement` — one source covers an entity/edge, the other does not
  - `genuine_dispute` — both sources cover the company but disagree on an edge
  - `coverage_gap` — one source simply never covered the entity (not a real dispute)

The `expected_conflicts` ledger in `sample-data/reference/` records every conflict with its type and subtype. WS2's `02_reconciliation.py` is scored against it: did it detect genuine disputes, and correctly *not* flag coverage gaps?

**Entity identity:** Every entity has an internal UUID (`company_id`, `investor_id`, etc.) decoupled from vendor IDs. `vendor_id_mapping` holds the canonical-ID ↔ {source, vendor_id} cross-reference. Entity resolution (fuzzy matching) is assumed solved via this mapping table; the reconciliation layer focuses on *attribute* conflicts.

**Landing metadata columns** on every landing row: `_record_id`, `_source_system`, `_source_file`, `_ingestion_ts`, `_batch_id`, `_data_version`, `_is_synthetic`.

**Nested columns** (arrays, structs) are stored as JSON strings in landing files — parsed at conformed layer, not at landing.

## Data flow (single workspace, `pevc-dev`)

The target architecture documents four separate workspaces, workspace-per-layer
(`docs/architecture.md` §2, DD-10). The live trial tenant runs everything in **one
workspace, `pevc-dev`** instead (DD-14) — separation is by lakehouse/item, not by
workspace. Data flow:

```
External sources (DealRoom, Capital IQ)
  → OneLake shortcuts → pevc-dev/landing_lakehouse
      → pevc-dev/conformed_lakehouse  (Delta tables)
          Stage A: schema validation (quarantine failures)
          Stage B: multi-source reconciliation (surface conflicts)
          Stage C: bitemporal load (effective_date + ingestion_date)
      → pevc-dev/(Gold Lakehouse, once built) + DirectLake semantic model
      → pevc-dev/(AI retrieval layer, once built)
```

Fabric Warehouse is a documented, deferred extension (DD-05) — not provisioned at
portfolio scope. Analytical SQL access is via the Lakehouse SQL endpoint over Gold.

AI integration reads from the conformed layer only — never from raw landing feeds.

## Key design constraints

- `reconciliation_log` is a **WS2 output**, not a generator output
- `ground_truth_*` files are reconciliation oracles — **not** landing feeds, must not be passed to the conformed pipeline
- The bitemporal columns (`effective_date`, `ingestion_date`, `source_attribution`, `reconciliation_status`) are assigned by WS2, never present in landing data
- `pre_money_valuation` and `post_money_valuation` are explicitly nullable — do not fill or impute
- Internal deal data (`deals`, `documents`) is the most sensitive entity class — strictest sensitivity labels

## Reference docs

- `docs/data_model.md` — canonical schema for all eight domain entities
- `docs/architecture.md` — full architecture with component rationale
- `docs/design_decisions.md` — numbered decision log (DD-01 through DD-07+)
- `infrastructure/workspace_layout.md` — Fabric workspace names, items, RBAC
- `SYNTHETIC_DATA.md` — data contract, conflict model, and known calibration caveats
