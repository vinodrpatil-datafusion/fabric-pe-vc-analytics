# data-generator

Synthetic PE/VC dataset generator. Produces seven referentially-consistent entities as Parquet (default) or CSV files, with lineage metadata columns on every row.

See `../SYNTHETIC_DATA.md` for full context on what is and isn't modelled.

## Quick start

```bash
# Install dependencies (no virtualenv required, but recommended)
pip install -r requirements.txt

# Generate small sample (~10 MB) into ../sample-data/
python generate.py --scale small --seed 42 --output ../sample-data

# Validate referential integrity and distribution realism
python validate_output.py
```

## CLI

```
python generate.py [--scale {small,medium,large}] [--seed INT] [--output PATH] [--format {parquet,csv,both}]
```

| Scale | Funds | LPs | Companies | Valuations | Approx size (Parquet) |
|---|---|---|---|---|---|
| small | 25 | 80 | ~270 | ~5,500 | ~0.5 MB |
| medium | 80 | 250 | ~1,200 | ~24,000 | ~3 MB |
| large | 250 | 600 | ~4,500 | ~90,000 | ~10 MB |

## Package layout

```
data-generator/
├── generate.py                CLI entrypoint
├── validate_output.py         Post-generation integrity and realism checks
├── requirements.txt
├── schemas/                   JSON Schema per entity
└── pevc_generator/
    ├── __init__.py
    ├── lineage.py             Lineage metadata + attach_lineage helper
    ├── reference.py           Distributions, weights, reference data
    ├── scale.py               Small/medium/large profile definitions
    ├── funds.py               Fund entity generation
    ├── lps.py                 LP entities and LP-fund commitments
    ├── companies.py           Portfolio companies with sector/geo skew
    └── deals.py               Deals, valuations, cashflows (the time-series heart)
```

## Reproducibility

Output is deterministic given a fixed `--seed`. The committed sample uses `seed=42`. Same seed + same scale = byte-identical Parquet output (modulo `_record_id`, `_ingestion_ts`, `_batch_id` which are intentionally per-run).

## Lineage columns

Every row carries the seven `_`-prefixed columns documented in `SYNTHETIC_DATA.md`. These are designed for Purview classification in WS7.

## Next workstream

WS2 ingests these files into a Fabric Lakehouse as the Bronze layer. See `../docs/architecture.md` (when published).
