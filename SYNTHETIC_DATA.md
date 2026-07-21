# Synthetic Data Notice

> All data under `sample-data/` is **synthetic**. It represents no real company, investor, person, deal, or transaction. Names, sectors, valuations, and outcomes are generated procedurally. Every landing row carries `_is_synthetic = true`.

## What this generates

Raw **multi-source landing feeds** for the Investment Analytics domain, aligned to `docs/data_model.md`. The generator simulates what external vendors and internal systems deliver *before* conformance — the conformed layer (WS2) reconciles and bitemporally models them.

This is **v2**. v1 generated a fund/LP/cashflow accounting model that did not match the published `data_model.md` (which is a deal-intelligence model: companies, rounds, investors, investments, people, internal deals, documents). v1 was replaced wholesale.

## Source model

Three feeds, mapping to `workspace_layout.md` → `landing_lakehouse` (as-built, present
in each of `pevc-dev`/`pevc-test`/`pevc-prod`; `ws-ingestion-dev` is the documented
production-target name):

| Feed | Represents | Entities |
|---|---|---|
| `landing/dealroom/` | External vendor (DealRoom-shaped) | companies, funding_rounds, investors, investments |
| `landing/capitaliq/` | External vendor (Capital IQ-shaped) | companies, funding_rounds, investors, investments |
| `landing/internal/` | The firm's own systems | people, deals (pipeline), documents, lp_documents, lp_document_manifest |

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
4. **A small number of funding rounds close before their company's `founded_date`** (~7% of rounds in the `seed=42`/`small` sample) — an uncorrelated-draw artifact between `canonical.py`'s company and round generation, not intentional test data. Downstream, WS3's Gold `fact_investment` cannot resolve a point-in-time `dim_company` version for the affected investments; its Stage E DQ check treats this as a soft `WARN`, not a hard failure — see `notebooks/05_gold_star_schema.ipynb` §8.

## LP document corpus (WS5 Stage A, DD-17)

`lp_documents` + `lp_document_manifest` (`data_model.md` §1.9–1.10) are the document
universe WS5's Foundry IQ leg indexes: quarterly letters, capital call notices, and
exit-notice memos. **Templated, not LLM-generated** (DD-13/DD-17 revision) — every
document is built from canonical ground truth already in `canonical.py`, so every fact
stated in one (an amount, a round type, an exit multiple) traces to a real underlying
row. No fabricated numeric precision, same discipline DD-16 applies to the IRR proxy.

Scoped to fund-type investors only (`investors.vintage_year` populated) — angels,
accelerators, and strategics don't raise from LPs. Volume derives organically from
each fund's actual investments (one capital call per participation, one memo per exit,
up to `MAX_LETTER_QUARTERS` trailing quarterly letters per fund) rather than a fixed
scale-profile count — see `pevc_generator/lp_documents.py`.

`lp_document_manifest` is the citation ground truth for Stage E's evaluation harness:
one row per `(document, entity_type, entity_id)` reference, so a retrieval agent's
cited entities can be checked against what a document actually references.
`validate_output.py` asserts every manifest reference resolves to ground truth.

## Bitemporal boundary

The landing feeds carry only **source-reported** dates (`founded_date`, `announced_date`, `created_date`) and raw ingestion metadata (`_ingestion_ts`, `_batch_id`, …). The bitemporal columns specified in `data_model.md` — `effective_date`, `ingestion_date`, `source_attribution`, `reconciliation_status` — are assigned by the conformed **Stage C** load (WS2), **not** by this generator. This is deliberate: landing is raw (`architecture.md` §2.1).

`funding_rounds` carry `announced_date` only; the ground-truth `true_close_date` is the oracle for what `effective_date` should resolve to after reconciliation.

## Entities NOT generated here

- `reconciliation_log` — an **output** of WS2 `02_reconciliation.py`, not a source feed.
- LP relationships, fund-level TVPI/IRR — explicitly out of scope per `data_model.md` §5 (LP deferred; fund performance lives in the semantic model). `lp_documents` (below) are a fund's own communications *addressed to* its LPs — no named LP entity or ownership share behind them, so this remains true.

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
