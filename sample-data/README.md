# sample-data

Committed synthetic PE/VC dataset, small-scale profile (~0.5 MB total).

**This data is synthetic.** See `../SYNTHETIC_DATA.md` for full context.

## Contents

| File | Rows | Description |
|---|---|---|
| `funds.parquet` | 25 | Fund vehicles |
| `limited_partners.parquet` | 80 | LP investors |
| `lp_commitments.parquet` | ~200 | LP→fund commitments (M:N) |
| `portfolio_companies.parquet` | ~270 | Investee companies |
| `deals.parquet` | ~600 | Primary, follow-on, exit deals |
| `valuations.parquet` | ~5,500 | Quarterly NAV marks |
| `cashflows.parquet` | ~600 | Capital calls and distributions |

## Regeneration

```bash
cd ../data-generator
python generate.py --scale small --seed 42 --output ../sample-data
```

Deterministic output for `seed=42`. Lineage metadata (`_record_id`, `_batch_id`, etc.) differs between runs by design.

## Lineage columns

Every row carries seven `_`-prefixed metadata columns:
- `_record_id`, `_source_system`, `_source_file`, `_ingestion_ts`, `_batch_id`, `_data_version`, `_is_synthetic`

These survive Bronze → Silver → Gold promotion and align with Purview classification.
