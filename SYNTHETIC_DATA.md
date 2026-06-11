# Synthetic Data Notice

> All data under `sample-data/` is **synthetic**. It represents no real company, investor, person, deal, or transaction. Names, sectors, valuations, and outcomes are generated procedurally. Every landing row carries `_is_synthetic = true`.

## What this generates

Raw **multi-source landing feeds** for the Investment Analytics domain, aligned to `docs/data_model.md`. The generator simulates what external vendors and internal systems deliver *before* conformance — the conformed layer (WS2) reconciles and bitemporally models them.

This is **v2**. v1 generated a fund/LP/cashflow accounting model that did not match the published `data_model.md` (which is a deal-intelligence model: companies, rounds, investors, investments, people, internal deals, documents). v1 was replaced wholesale.

## Source model

Three feeds, mapping to `workspace_layout.md` → `ws-ingestion-dev/landing_lakehouse`:

| Feed | Represents | Entities |
|---|---|---|
| `landing/dealroom/` | External vendor (DealRoom-shaped) | companies, funding_rounds, investors, investments |
| `landing/capitaliq/` | External vendor (Capital IQ-shaped) | companies, funding_rounds, investors, investments |
| `landing/internal/` | The firm's own systems | people, deals (pipeline), documents |

Plus `reference/`:
- `vendor_id_mapping` — canonical ID ↔ {source, vendor_id}, per `architecture.md` §4. Entity resolution is treated as already solved (a maintained mapping table); WS2 reconciliation focuses on *attribute* conflicts, not fuzzy matching. **Explicit simplification.**
- `expected_conflicts` — oracle ledger of every cross-source conflict with its true type (and `genuine_dispute`/`coverage_gap` subtype for existence). Lets WS2 reconciliation be *scored*, not just executed.
- `ground_truth_*` — the canonical "real world" oracle. **Not a landing feed.** Provided so WS2 reconciliation can be *scored* (did it recover the truth?), not just executed.

## Conflicts (the point of the multi-source design)

The two external feeds disagree at controlled rates so `02_reconciliation.py` (WS2) has real work. The three conflict types match `reconciliation_log.conflict_type`:

| Conflict type | Mechanism | Observed (small, seed 42) |
|---|---|---|
| `existence_disagreement` (company) | Independent coverage draws per source | ~32% single-source (coverage-gap) |
| `value_disagreement` | Source-specific noise on `amount_raised`; lead-investor alteration | ~24% of shared rounds |
| `temporal_disagreement` | `announced_date` = true close + source-specific lag | ~38% of shared rounds |
| `existence_disagreement` (edge, **genuine**) | Edge dropped by one source when **both** cover the company | ~13% of edges |
| `existence_disagreement` (edge, coverage-gap) | Edge absent only because one source never covered the company | ~29% of edges |

Rates are tunable in `pevc_generator/reference.py` (`SOURCE_PROFILES`).

### Expected-conflicts ledger (reconciliation oracle)

`reference/expected_conflicts` labels every cross-source conflict by `entity_type`, `canonical_id`, `conflict_type` (within the `reconciliation_log` enum), and — for existence conflicts — an `existence_subtype` of `genuine_dispute` or `coverage_gap`. WS2's `02_reconciliation.py` is scored against this: did it detect the genuine disputes, and did it correctly *not* flag coverage gaps as disputes?

### Known calibration caveats (honest limitations)

1. **Company existence ~32% is high** for two premium vendors that in reality overlap tightly. Independent coverage draws overstate divergence. Acceptable for a demo (visible reconciliation work); tune `coverage` up and correlate the draws for stricter realism.
2. **Edge-existence conflation — RESOLVED.** Genuine edge disputes (~13%) are now distinct from coverage-driven gaps (~29%). Edge-drop is applied only to companies both sources cover, so a one-source edge on a both-covered company is unambiguously a dispute; the `expected_conflicts` ledger records the distinction.
3. **Entity resolution is assumed solved** via `vendor_id_mapping`. Real platforms must fuzzy-match across vendors. Documented as out of scope, consistent with `architecture.md` §4.

## Bitemporal boundary

The landing feeds carry only **source-reported** dates (`founded_date`, `announced_date`, `created_date`) and raw ingestion metadata (`_ingestion_ts`, `_batch_id`, …). The bitemporal columns specified in `data_model.md` — `effective_date`, `ingestion_date`, `source_attribution`, `reconciliation_status` — are assigned by the conformed **Stage C** load (WS2), **not** by this generator. This is deliberate: landing is raw (`architecture.md` §2.1).

`funding_rounds` carry `announced_date` only; the ground-truth `true_close_date` is the oracle for what `effective_date` should resolve to after reconciliation.

## Entities NOT generated here

- `reconciliation_log` — an **output** of WS2 `02_reconciliation.py`, not a source feed.
- LP relationships, fund-level TVPI/IRR — explicitly out of scope per `data_model.md` §5 (LP deferred; fund performance lives in the semantic model).

## Landing metadata columns

Every landing row carries:

| Column | Purpose |
|---|---|
| `_record_id` | Per-row UUID |
| `_source_system` | `dealroom` / `capitaliq` / `internal` |
| `_source_file` | Origin filename |
| `_ingestion_ts` | Generator run timestamp (UTC, ISO) |
| `_batch_id` | Run identifier (shared across the run) |
| `_data_version` | Schema version (`v2.0.0`) |
| `_is_synthetic` | Always `true` |

## Nested attributes

Arrays and structs (`sector_taxonomy`, `lead_investor_vendor_ids`, `current_affiliations`, `stage_history`, etc.) are stored as **JSON strings** in the landing files — realistic for raw vendor delivery, and parsed in the conformed layer.

## Reproducibility

Deterministic given `--seed`. Committed sample uses `seed=42`.

```bash
cd data-generator
python generate.py --scale small --seed 42 --output ../sample-data
python validate_output.py
```

**Format note:** the generator writes **Parquet** when `pyarrow` is available, otherwise **CSV**. The committed sample may be CSV if generated in a Parquet-less environment; regenerate locally with `pyarrow` installed to produce Parquet (what Fabric shortcuts expect).

## Licence

MIT (see `LICENSE`).
